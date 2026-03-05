"""
YouTube Search Router — Searches YouTube using yt-dlp (free, no API key).

Endpoint: GET /api/youtube-search?q=keyword&max=5
Returns: list of {title, thumbnail, channel, duration, url, view_count}

Uses caching to avoid excessive lookups (5-minute TTL).
"""

import asyncio
import json
import logging
import time
import shutil
from typing import Optional
from fastapi import APIRouter, Query

log = logging.getLogger("Alita.youtube")

youtube_router = APIRouter(prefix="/api", tags=["youtube"])

# Simple in-memory cache
_cache: dict[str, tuple[float, list]] = {}
CACHE_TTL = 300  # 5 minutes


def _yt_dlp_available() -> bool:
    return shutil.which("yt-dlp") is not None


async def _search_youtube(query: str, max_results: int = 5) -> list[dict]:
    """Search YouTube using yt-dlp and return video metadata."""
    cache_key = f"{query.lower().strip()}:{max_results}"
    now = time.time()

    # Check cache
    if cache_key in _cache:
        ts, data = _cache[cache_key]
        if now - ts < CACHE_TTL:
            log.info("YouTube cache hit for: %s", query[:30])
            return data

    if not _yt_dlp_available():
        log.warning("yt-dlp not found in PATH — returning empty results")
        return []

    try:
        search_url = f"ytsearch{max_results}:{query}"
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-download",
            "--flat-playlist",
            "--no-warnings",
            "--quiet",
            search_url,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)

        if proc.returncode != 0:
            log.error("yt-dlp error: %s", stderr.decode()[:200])
            return []

        results = []
        for line in stdout.decode().strip().split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                results.append({
                    "title": data.get("title", "Untitled"),
                    "thumbnail": (
                        data.get("thumbnail")
                        or data.get("thumbnails", [{}])[-1].get("url", "")
                    ),
                    "channel": data.get("channel", data.get("uploader", "Unknown")),
                    "duration": _format_duration(data.get("duration")),
                    "url": data.get("url") or f"https://www.youtube.com/watch?v={data.get('id', '')}",
                    "view_count": _format_views(data.get("view_count")),
                })
            except (json.JSONDecodeError, KeyError) as e:
                log.debug("Skip malformed yt-dlp entry: %s", e)
                continue

        # Cache results
        _cache[cache_key] = (now, results)
        log.info("YouTube search: '%s' → %d results", query[:30], len(results))
        return results

    except asyncio.TimeoutError:
        log.warning("yt-dlp timed out for: %s", query[:30])
        return []
    except Exception as e:
        log.error("YouTube search error: %s", e)
        return []


def _format_duration(seconds) -> str:
    if not seconds:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02}:{s:02}"
    return f"{m}:{s:02}"


def _format_views(count) -> str:
    if not count:
        return ""
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M views"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K views"
    return f"{count} views"


@youtube_router.get("/youtube-search")
async def youtube_search(
    q: str = Query(..., min_length=1, description="Search keyword"),
    max: int = Query(5, ge=1, le=10, description="Max results"),
):
    """Search YouTube for videos related to the query."""
    results = await _search_youtube(q, max)
    return {"query": q, "results": results, "count": len(results)}
