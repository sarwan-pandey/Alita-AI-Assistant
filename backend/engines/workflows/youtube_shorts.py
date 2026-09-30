"""
YouTube Shorts Workflow V3 — Local video processing (no Opus Clip login).

Pipeline:
  1. Check daily limit (max 3/day)
  2. Find trending video via yt-dlp search (no browser needed)
  3. Download video with yt-dlp (no login)
  4. Cut best segment + convert to vertical 9:16 with FFmpeg (local)
  5. Generate optimized title + hashtags (total <= 100 chars)
  6. Upload to YouTube Studio (persistent browser)
  7. Update daily counter

Zero external service logins. Everything runs locally.
"""

import asyncio
import glob
import json
import logging
import os
import re
import subprocess
import time
import random
from datetime import date
from typing import Any, Dict, List

from engines.workflow_engine import (
    BaseWorkflow,
    WorkflowStep,
    StepResult,
)

logger = logging.getLogger("alita.workflow.shorts")

# ── Config ────────────────────────────────────────────────────────────────────

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
_WORK_DIR = os.path.join(os.path.expanduser("~"), ".alita", "shorts_workspace")
os.makedirs(_WORK_DIR, exist_ok=True)


def _load_config() -> Dict[str, Any]:
    try:
        with open(_CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {"blogger": {}, "youtube": {}, "headless": True, "daily_tracker": {}}


def _save_config(config: Dict[str, Any]):
    try:
        with open(_CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=4)
    except Exception:
        pass


def _check_daily_limit(config: Dict) -> bool:
    tracker = config.get("daily_tracker", {})
    today = date.today().isoformat()
    if tracker.get("last_date") != today:
        tracker["last_date"] = today
        tracker["blogs_posted"] = 0
        tracker["shorts_uploaded"] = 0
        config["daily_tracker"] = tracker
        _save_config(config)
    limit = config.get("youtube", {}).get("daily_limit", 3)
    return tracker.get("shorts_uploaded", 0) < limit


def _increment_counter():
    config = _load_config()
    tracker = config.get("daily_tracker", {})
    today = date.today().isoformat()
    if tracker.get("last_date") != today:
        tracker = {"last_date": today, "blogs_posted": 0, "shorts_uploaded": 0}
    tracker["shorts_uploaded"] = tracker.get("shorts_uploaded", 0) + 1
    config["daily_tracker"] = tracker
    _save_config(config)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1: Daily Limit Check
# ══════════════════════════════════════════════════════════════════════════════

class CheckShortsLimitStep(WorkflowStep):
    name = "Check Daily Limit"
    description = "Checking if daily shorts quota allows upload"
    timeout_s = 5

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        config = _load_config()
        if not _check_daily_limit(config):
            uploaded = config.get("daily_tracker", {}).get("shorts_uploaded", 3)
            return StepResult(
                success=False,
                message=f"Daily limit reached: {uploaded}/3 shorts uploaded today.",
            )
        uploaded = config.get("daily_tracker", {}).get("shorts_uploaded", 0)
        return StepResult(success=True, message=f"Quota OK ({uploaded}/3 used)")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2: Find Trending Video (yt-dlp search — no browser needed)
# ══════════════════════════════════════════════════════════════════════════════

class FindTrendingVideoStep(WorkflowStep):
    name = "Find Trending Video"
    description = "Searching YouTube for popular videos"
    timeout_s = 30

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        # If user provided a URL, use it directly
        source_url = context.get("source_url", "")
        if source_url and ("youtube.com" in source_url or "youtu.be" in source_url):
            return StepResult(
                success=True,
                message="Using provided video URL",
                data={"video_url": source_url},
            )

        niche = context.get("niche", context.get("topic", "trending"))

        try:
            # Use yt-dlp to search YouTube — no browser, no login
            search_query = f"ytsearch5:{niche} shorts"
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: subprocess.run(
                    [
                        "yt-dlp", "--flat-playlist", "--dump-json",
                        "--no-warnings", search_query
                    ],
                    capture_output=True, text=True, timeout=20
                )
            )

            if result.returncode == 0 and result.stdout.strip():
                videos = []
                for line in result.stdout.strip().split("\n"):
                    try:
                        data = json.loads(line)
                        videos.append({
                            "url": f"https://www.youtube.com/watch?v={data.get('id', '')}",
                            "title": data.get("title", ""),
                            "duration": data.get("duration", 0),
                            "view_count": data.get("view_count", 0),
                        })
                    except json.JSONDecodeError:
                        continue

                # Pick a random one from top results (variety)
                if videos:
                    # Prefer videos under 5 minutes (good for shorts source)
                    short_vids = [v for v in videos if v.get("duration", 999) < 300]
                    pick = random.choice(short_vids if short_vids else videos)

                    logger.info(f"[Shorts] Found: {pick['title'][:50]} ({pick['url']})")
                    return StepResult(
                        success=True,
                        message=f"Found: {pick['title'][:50]}",
                        data={
                            "video_url": pick["url"],
                            "source_title": pick["title"],
                        },
                    )

        except Exception as e:
            logger.warning(f"[Shorts] yt-dlp search failed: {e}")

        return StepResult(success=False, message="Could not find a trending video")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3: Download + Cut Short (yt-dlp + FFmpeg — fully local)
# ══════════════════════════════════════════════════════════════════════════════

class DownloadAndCutStep(WorkflowStep):
    name = "Download & Create Short"
    description = "Downloading best 30s clip and converting to 9:16"
    timeout_s = 120

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        video_url = context.get("video_url", "")
        if not video_url:
            return StepResult(success=False, message="No video URL")

        timestamp = int(time.time())
        raw_path = os.path.join(_WORK_DIR, f"raw_{timestamp}.mp4")
        short_path = os.path.join(_WORK_DIR, f"short_{timestamp}.mp4")

        notify = context.get("_notify_fn")

        try:
            # ── Step A: Get video info + find best segment ───────────
            if notify:
                notify({"type": "workflow_progress", "message": "Analyzing video for best moment..."})

            info_result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: subprocess.run(
                    ["yt-dlp", "--dump-json", "--no-download", "--no-warnings", video_url],
                    capture_output=True, text=True, timeout=20
                )
            )

            duration = 120
            start_time = 10
            video_title = ""

            if info_result.returncode == 0 and info_result.stdout.strip():
                try:
                    info = json.loads(info_result.stdout)
                    duration = info.get("duration", 120)
                    video_title = info.get("title", "")

                    # Try to find highest-attention segment from YouTube heatmap
                    heatmap = info.get("heatmap", [])
                    if heatmap and len(heatmap) > 5:
                        start_time = self._find_peak_segment(heatmap, duration)
                        logger.info(f"[Shorts] Heatmap peak found at {start_time}s")
                    else:
                        # No heatmap — use chapters or smart guess
                        chapters = info.get("chapters", [])
                        if chapters and len(chapters) > 1:
                            # Pick most interesting chapter (skip first = intro)
                            best_ch = chapters[min(1, len(chapters) - 1)]
                            start_time = int(best_ch.get("start_time", duration * 0.25))
                        else:
                            # Default: skip intro (25% in), most content is there
                            start_time = max(5, int(duration * 0.25))

                except json.JSONDecodeError:
                    pass

            # Ensure we don't go past the end
            clip_len = 30
            if start_time + clip_len > duration:
                start_time = max(0, int(duration - clip_len - 2))

            end_time = start_time + clip_len

            logger.info(f"[Shorts] Downloading {start_time}s-{end_time}s ({clip_len}s clip)")

            # ── Step B: Download ONLY the 30s segment ────────────────
            if notify:
                notify({"type": "workflow_progress", "message": f"Downloading 30s clip ({start_time}s-{end_time}s)..."})

            dl_result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: subprocess.run(
                    [
                        "yt-dlp",
                        "-f", "best[height<=1080]",
                        "--download-sections", f"*{start_time}-{end_time}",
                        "--force-keyframes-at-cuts",
                        "-o", raw_path,
                        "--no-playlist",
                        "--no-warnings",
                        video_url,
                    ],
                    capture_output=True, text=True, timeout=60
                )
            )

            if dl_result.returncode != 0 or not os.path.exists(raw_path):
                possible = glob.glob(os.path.join(_WORK_DIR, f"raw_{timestamp}.*"))
                if possible:
                    raw_path = possible[0]
                else:
                    # Fallback: download full then cut (older yt-dlp versions)
                    logger.warning("[Shorts] Partial download failed, trying full download + cut")
                    return await self._fallback_download(
                        video_url, raw_path, short_path,
                        start_time, clip_len, notify
                    )

            raw_size = os.path.getsize(raw_path) / (1024 * 1024)
            logger.info(f"[Shorts] Downloaded clip: {raw_size:.1f} MB")

            # ── Step C: Convert to 9:16 vertical ─────────────────────
            if notify:
                notify({"type": "workflow_progress", "message": "Converting to 9:16 vertical..."})

            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-i", raw_path,
                # Vertical: scale + center-crop to 9:16 (1080x1920)
                "-vf", (
                    "scale=1080:1920:force_original_aspect_ratio=increase,"
                    "crop=1080:1920,"
                    "setsar=1"
                ),
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                "-t", str(clip_len),
                short_path,
            ]

            await asyncio.get_event_loop().run_in_executor(
                None, lambda: subprocess.run(
                    ffmpeg_cmd, capture_output=True, text=True, timeout=60
                )
            )

            # Clean up raw
            try:
                os.remove(raw_path)
            except Exception:
                pass

            if os.path.exists(short_path) and os.path.getsize(short_path) > 10000:
                short_size = os.path.getsize(short_path) / (1024 * 1024)
                msg = f"Short ready: {clip_len}s clip, {short_size:.1f}MB, 9:16 vertical"
                if video_title:
                    context["source_title"] = video_title
                return StepResult(
                    success=True, message=msg,
                    data={"short_path": short_path, "clip_duration": clip_len},
                )

            return StepResult(success=False, message="FFmpeg conversion failed")

        except Exception as e:
            for f in [raw_path, short_path]:
                try:
                    os.remove(f)
                except Exception:
                    pass
            return StepResult(success=False, message=f"Failed: {e}")

    def _find_peak_segment(self, heatmap: list, duration: float) -> int:
        """Find the 30s window with highest total attention from YouTube heatmap."""
        if not heatmap:
            return max(5, int(duration * 0.25))

        # Heatmap entries: {"start_time": float, "end_time": float, "value": float}
        # Find the peak attention point
        best_start = 0
        best_score = 0.0

        for i, entry in enumerate(heatmap):
            t = entry.get("start_time", 0)
            # Sum attention values in a 30s window from this point
            window_score = 0.0
            for j in range(i, len(heatmap)):
                jt = heatmap[j].get("start_time", 0)
                if jt - t > 30:
                    break
                window_score += heatmap[j].get("value", 0)

            if window_score > best_score:
                best_score = window_score
                best_start = int(t)

        # Don't start at 0 (usually intro/logo)
        return max(3, best_start)

    async def _fallback_download(self, url, raw_path, short_path,
                                  start, clip_len, notify) -> StepResult:
        """Fallback: download full video then cut with FFmpeg."""
        if notify:
            notify({"type": "workflow_progress", "message": "Downloading video (fallback)..."})

        dl = await asyncio.get_event_loop().run_in_executor(
            None, lambda: subprocess.run(
                ["yt-dlp", "-f", "best[height<=1080]", "--max-filesize", "100M",
                 "-o", raw_path, "--no-playlist", "--no-warnings", url],
                capture_output=True, text=True, timeout=90
            )
        )

        if not os.path.exists(raw_path):
            possible = glob.glob(raw_path.rsplit(".", 1)[0] + ".*")
            if possible:
                raw_path = possible[0]
            else:
                return StepResult(success=False, message="Download failed")

        ffmpeg_cmd = [
            "ffmpeg", "-y", "-ss", str(start), "-i", raw_path,
            "-t", str(clip_len),
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", short_path,
        ]

        await asyncio.get_event_loop().run_in_executor(
            None, lambda: subprocess.run(ffmpeg_cmd, capture_output=True, timeout=60)
        )

        try:
            os.remove(raw_path)
        except Exception:
            pass

        if os.path.exists(short_path) and os.path.getsize(short_path) > 10000:
            sz = os.path.getsize(short_path) / (1024 * 1024)
            return StepResult(
                success=True,
                message=f"Short ready (fallback): {clip_len}s, {sz:.1f}MB",
                data={"short_path": short_path, "clip_duration": clip_len},
            )
        return StepResult(success=False, message="FFmpeg failed")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4: Generate Optimized Title (<=100 chars including hashtags)
# ══════════════════════════════════════════════════════════════════════════════

class GenerateOptimizedTitleStep(WorkflowStep):
    name = "Generate Optimized Title"
    description = "Creating SEO title + hashtags (<=100 chars total)"
    timeout_s = 30

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        topic = context.get("topic", context.get("niche", "trending"))
        source_title = context.get("source_title", "")

        prompt = f"""Generate a YouTube Shorts title with hashtags.

Source video topic: {topic}
Source title: {source_title}

STRICT RULES:
1. Total length (title + hashtags) MUST be under 100 characters
2. Title should be catchy, emotional, and clickable
3. Use 2-3 hashtags maximum
4. First hashtag must be #Shorts
5. Add 1-2 niche-relevant hashtags
6. Use emojis (1-2 max) for engagement
7. No clickbait — just engaging and honest

FORMAT (single line, nothing else):
[title text] #Shorts #Tag1 #Tag2

EXAMPLES:
This AI Can Read Your Mind 🤯 #Shorts #AI #Tech
5 Foods That Burn Fat While You Sleep 🔥 #Shorts #Health
Why Nobody Talks About This Python Trick 🐍 #Shorts #Coding

Generate one title now:"""

        try:
            title_line = await _generate_with_llm(prompt)
            title_line = title_line.strip().strip('"').strip("'")
            title_line = title_line.split("\n")[0].strip()

            # Enforce 100 char limit
            if len(title_line) > 100:
                parts = title_line.rsplit("#", 3)
                if len(parts) > 1:
                    base = parts[0].strip()
                    hashtags = " #" + " #".join(p.strip() for p in parts[1:])
                    max_base = 100 - len(hashtags)
                    if max_base > 20:
                        base = base[:max_base - 3].rstrip() + "..."
                        title_line = base + hashtags
                    else:
                        title_line = title_line[:97] + "..."
                else:
                    title_line = title_line[:97] + "..."

            # Ensure #Shorts is present
            if "#Shorts" not in title_line and "#shorts" not in title_line:
                if len(title_line) + 8 <= 100:
                    title_line += " #Shorts"

            logger.info(f"[Shorts] Title ({len(title_line)} chars): {title_line}")

            # Generate description
            desc = (
                f"{source_title}\n\n"
                f"Follow for more amazing content!\n\n"
                f"#Shorts #YouTube #{topic.replace(' ', '').title()}\n"
                f"#Trending #Viral"
            )

            return StepResult(
                success=True,
                message=f"Title: {title_line[:50]} ({len(title_line)} chars)",
                data={"yt_title": title_line, "yt_description": desc},
            )
        except Exception as e:
            fallback = f"{topic.title()[:60]} #Shorts #Trending"
            if len(fallback) > 100:
                fallback = fallback[:97] + "..."
            return StepResult(
                success=True,
                message="Using fallback title",
                data={"yt_title": fallback, "yt_description": f"#{topic} #Shorts"},
            )


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5: Upload to YouTube
# ══════════════════════════════════════════════════════════════════════════════

class YouTubeUploadStep(WorkflowStep):
    name = "Upload to YouTube"
    description = "Uploading short to YouTube Studio"
    timeout_s = 120

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        short_path = context.get("short_path", "")
        if not short_path or not os.path.exists(short_path):
            return StepResult(success=False, message="No video file found")

        title = context.get("yt_title", "Trending #Shorts")
        description = context.get("yt_description", "#Shorts")

        try:
            from engines.browser_agent import BrowserAgent
            config = _load_config()

            async with BrowserAgent(headless=config.get("headless", True), profile_name="youtube") as agent:
                page = await agent.new_page("https://studio.youtube.com")
                await page.wait_for_timeout(4000)

                if "accounts.google.com" in page.url:
                    return StepResult(
                        success=False,
                        message="Not logged in. Run: python -m engines.workflows.login",
                    )

                # Click Create -> Upload
                create_btn = await page.query_selector(
                    '#create-icon, button:has-text("Create"), [aria-label="Create"]')
                if create_btn:
                    await create_btn.click()
                    await page.wait_for_timeout(1000)
                    upload_opt = await page.query_selector(
                        'tp-yt-paper-item:has-text("Upload"), #text-item-0')
                    if upload_opt:
                        await upload_opt.click()
                        await page.wait_for_timeout(2000)

                # Upload file
                file_input = await page.query_selector('input[type="file"]')
                if not file_input:
                    return StepResult(success=False, message="Upload interface not found")

                await file_input.set_input_files(short_path)
                logger.info(f"[Shorts] Uploading: {os.path.basename(short_path)}")
                await page.wait_for_timeout(4000)

                # Fill title
                title_box = await page.query_selector(
                    '#textbox[aria-label*="title"], '
                    'div#title-textarea div[contenteditable="true"]'
                )
                if title_box:
                    await title_box.click()
                    await page.keyboard.press("Control+a")
                    await page.keyboard.type(title)

                # Fill description
                desc_boxes = await page.query_selector_all('div[contenteditable="true"]')
                if len(desc_boxes) > 1:
                    await desc_boxes[1].click()
                    await page.keyboard.press("Control+a")
                    await page.keyboard.type(description)

                # Not made for kids
                not_kids = await page.query_selector(
                    'tp-yt-paper-radio-button[name="NOT_MADE_FOR_KIDS"]')
                if not_kids:
                    await not_kids.click()

                # Click Next 3 times
                for _ in range(3):
                    await page.wait_for_timeout(1500)
                    next_btn = await page.query_selector('#next-button')
                    if next_btn:
                        await next_btn.click()

                await page.wait_for_timeout(2000)

                # Set Public
                public_btn = await page.query_selector(
                    'tp-yt-paper-radio-button[name="PUBLIC"]')
                if public_btn:
                    await public_btn.click()

                # Publish
                done_btn = await page.query_selector('#done-button')
                if done_btn:
                    await done_btn.click()
                    await page.wait_for_timeout(5000)

                    _increment_counter()

                    # Try get video URL
                    link = await page.query_selector('a[href*="youtu"]')
                    video_url = ""
                    if link:
                        video_url = await link.get_attribute("href") or ""

                    # Clean up local file
                    try:
                        os.remove(short_path)
                    except Exception:
                        pass

                    return StepResult(
                        success=True,
                        message=f"Uploaded to YouTube! Title: {title[:40]}",
                        data={"youtube_url": video_url},
                    )

                return StepResult(success=False, message="Publish button not found")

        except Exception as e:
            return StepResult(success=False, message=f"Upload failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# COMPLETE WORKFLOW
# ══════════════════════════════════════════════════════════════════════════════

class YouTubeShortsWorkflow(BaseWorkflow):
    name = "YouTube Shorts Creator"
    description = "Find trending → Download → Cut short → Optimize title → Upload"

    def get_steps(self) -> List[WorkflowStep]:
        return [
            CheckShortsLimitStep(),
            FindTrendingVideoStep(),
            DownloadAndCutStep(),
            GenerateOptimizedTitleStep(),
            YouTubeUploadStep(),
        ]


# ══════════════════════════════════════════════════════════════════════════════
# LLM HELPER
# ══════════════════════════════════════════════════════════════════════════════

async def _generate_with_llm(prompt: str) -> str:
    """Generate text using local Ollama (Qwen3-8B)."""
    try:
        import asyncio
        from ollama_client import ollama_chat  # type: ignore[import]

        # ollama_chat is synchronous — run in thread pool to stay async
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: ollama_chat(prompt=prompt, max_tokens=200, temperature=0.7),
        )
        return result or ""
    except Exception as e:
        logger.warning("[YouTubeShortsWorkflow] Ollama LLM failed: %s", e)
        return ""

