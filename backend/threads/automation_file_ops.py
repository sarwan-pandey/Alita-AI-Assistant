"""
Alita Automation — File Operations (automation_file_ops.py)
===========================================================
Secure filesystem manipulation and fuzzy discovery:
- create_file, read_file, write_file, delete_file
- list_directory, create_folder, copy_item, move_item
- search_files, find_file_smart, fuzzy_find_path, _safe_path
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

log = logging.getLogger("Alita.automation_file_ops")


def _safe_path(path: str) -> str:
    """
    Expand and validate a path using ALLOWLIST approach.
    Only allows access within safe user directories.
    Blocks system directories and sensitive config files.
    """
    expanded = os.path.abspath(os.path.expanduser(path))
    home = os.path.expanduser("~")
    path_lower = expanded.lower().replace("/", "\\")
    home_lower = home.lower().replace("/", "\\")

    allowed_dirs = [
        os.path.join(home_lower, d) for d in [
            "desktop", "documents", "downloads", "pictures", "videos",
            "music", "projects", "repos", "code", "work",
            "onedrive", "onedrive - personal",
        ]
    ]

    blocked_patterns = [
        "windows", "program files", "programdata", "system32",
        ".ssh", ".gnupg", ".aws", ".azure", ".kube",
        ".env", ".git", ".keys", "appdata\\roaming",
        "appdata\\local\\microsoft", "ntuser",
    ]
    for pattern in blocked_patterns:
        if pattern in path_lower:
            raise PermissionError(
                f"Access blocked for security: {expanded}. "
                f"Allowed directories: Desktop, Documents, Downloads, Pictures, Videos, Music, Projects"
            )

    in_allowed = any(path_lower.startswith(d) for d in allowed_dirs)
    if not in_allowed:
        raise PermissionError(
            f"Access outside allowed directories: {expanded}. "
            f"Allowed directories: Desktop, Documents, Downloads, Pictures, Videos, Music, Projects"
        )

    return expanded


def _normalize_name(name: str) -> str:
    """Normalize a filename for fuzzy comparison: lowercase, strip separators."""
    import re
    return re.sub(r'[_\-\s.]+', '', name.lower())


def _levenshtein(a: str, b: str) -> int:
    """Simple Levenshtein distance for short strings."""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[len(b)]


def fuzzy_find_path(path: str) -> str:
    """Find a file/folder even if STT mishears the name."""
    expanded = os.path.abspath(os.path.expanduser(path))
    if os.path.exists(expanded):
        return expanded

    parent = os.path.dirname(expanded)
    target_name = os.path.basename(expanded)

    if not os.path.isdir(parent):
        return expanded

    target_normed = _normalize_name(target_name)
    try:
        entries = os.listdir(parent)
    except OSError:
        return expanded

    for entry in entries:
        if _normalize_name(entry) == target_normed:
            found = os.path.join(parent, entry)
            log.info("[FuzzyFind] Normalized match: '%s' -> '%s'", target_name, entry)
            return found

    target_no_ext = _normalize_name(os.path.splitext(target_name)[0])
    for entry in entries:
        entry_no_ext = _normalize_name(os.path.splitext(entry)[0])
        if entry_no_ext == target_no_ext:
            found = os.path.join(parent, entry)
            log.info("[FuzzyFind] Name-only match: '%s' -> '%s'", target_name, entry)
            return found

    best_match = None
    best_distance = 999
    for entry in entries:
        entry_normed = _normalize_name(os.path.splitext(entry)[0])
        dist = _levenshtein(target_normed, entry_normed)
        max_dist = 2 if len(target_normed) <= 6 else 3
        if dist < best_distance and dist <= max_dist:
            best_distance = dist
            best_match = entry

    if best_match:
        found = os.path.join(parent, best_match)
        log.info("[FuzzyFind] Fuzzy match (dist=%d): '%s' -> '%s'", best_distance, target_name, best_match)
        return found

    return expanded


def create_file(path: str, content: str = "") -> dict:
    """Create a new file with optional content and verify creation."""
    try:
        path = _safe_path(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        verified = os.path.exists(path)
        return {"status": "success", "action": "created", "path": path, "verified": verified}
    except PermissionError as e:
        return {"status": "error", "error": str(e), "verified": False}
    except Exception as e:
        return {"status": "error", "error": str(e), "verified": False}


def read_file(path: str) -> dict:
    """Read a file's contents."""
    try:
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            path = fuzzy_find_path(path)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read(10000)
        return {"status": "success", "path": path, "content": content, "size": os.path.getsize(path)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def write_file(path: str, content: str) -> dict:
    """Write content to a file (overwrite) and verify."""
    try:
        path = _safe_path(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        verified = os.path.exists(path) and os.path.getsize(path) >= len(content.encode("utf-8"))
        return {"status": "success", "action": "written", "path": path, "bytes": len(content), "verified": verified}
    except PermissionError as e:
        return {"status": "error", "error": str(e), "verified": False}
    except Exception as e:
        return {"status": "error", "error": str(e), "verified": False}


def delete_file(path: str) -> dict:
    """Delete a file or directory."""
    try:
        path = _safe_path(path)
        if not os.path.exists(path):
            path = fuzzy_find_path(path)
        if os.path.isfile(path):
            os.remove(path)
            return {"status": "success", "action": "deleted", "path": path}
        elif os.path.isdir(path):
            shutil.rmtree(path)
            return {"status": "success", "action": "deleted_folder", "path": path}
        else:
            return {"status": "error", "error": f"Not found: {path}"}
    except PermissionError as e:
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def list_directory(path: str = "~") -> dict:
    """List files in a directory."""
    try:
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            return {"status": "error", "error": f"Not a directory: {path}"}
        items = []
        for name in os.listdir(path)[:50]:
            full = os.path.join(path, name)
            is_dir = os.path.isdir(full)
            size = os.path.getsize(full) if os.path.isfile(full) else 0
            items.append({"name": name, "is_dir": is_dir, "size": size})
        return {"status": "success", "path": path, "count": len(items), "items": items}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def create_folder(path: str) -> dict:
    """Create a new folder and verify."""
    try:
        path = os.path.expanduser(path)
        os.makedirs(path, exist_ok=True)
        verified = os.path.isdir(path)
        return {"status": "success", "action": "folder_created", "path": path, "verified": verified}
    except Exception as e:
        return {"status": "error", "error": str(e), "verified": False}


def copy_item(source: str, destination: str) -> dict:
    """Copy a file or folder from source to destination."""
    try:
        src = _safe_path(source)
        dst = _safe_path(destination)

        if not os.path.exists(src):
            src = fuzzy_find_path(src)

        if not os.path.exists(src):
            return {"status": "error", "error": f"Source not found: {src}"}

        if os.path.isdir(dst):
            dst = os.path.join(dst, os.path.basename(src))

        if os.path.isfile(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            return {"status": "success", "action": "copied_file",
                    "source": src, "destination": dst,
                    "size": os.path.getsize(dst)}
        elif os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
            return {"status": "success", "action": "copied_folder",
                    "source": src, "destination": dst}
        else:
            return {"status": "error", "error": f"Unknown item type: {src}"}
    except PermissionError as e:
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def move_item(source: str, destination: str) -> dict:
    """Move a file or folder from source to destination."""
    try:
        src = _safe_path(source)
        dst = _safe_path(destination)

        if not os.path.exists(src):
            src = fuzzy_find_path(src)

        if not os.path.exists(src):
            return {"status": "error", "error": f"Source not found: {src}"}

        if os.path.isdir(dst):
            dst = os.path.join(dst, os.path.basename(src))

        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        return {"status": "success", "action": "moved",
                "source": src, "destination": dst}
    except PermissionError as e:
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def search_files(query: str, file_type: str = "", days: int = 0) -> dict:
    """Search for files by name, type, and modification time."""
    try:
        home = os.path.expanduser("~")
        search_dirs = [
            os.path.join(home, "Desktop"),
            os.path.join(home, "Documents"),
            os.path.join(home, "Downloads"),
            os.path.join(home, "Pictures"),
            os.path.join(home, "Videos"),
        ]

        query_lower = query.lower()
        ext_filter = None
        if file_type:
            ft = file_type.lower().strip(".")
            ext_map = {
                "pdf": [".pdf"], "document": [".doc", ".docx", ".txt", ".rtf"],
                "image": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"],
                "photo": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"],
                "video": [".mp4", ".avi", ".mkv", ".mov", ".wmv"],
                "audio": [".mp3", ".wav", ".flac", ".aac", ".ogg"],
                "excel": [".xls", ".xlsx", ".csv"],
                "ppt": [".ppt", ".pptx"],
            }
            ext_filter = ext_map.get(ft, [f".{ft}"])

        time_cutoff = None
        if days > 0:
            time_cutoff = (datetime.now() - timedelta(days=days)).timestamp()

        results = []
        for search_dir in search_dirs:
            if not os.path.exists(search_dir):
                continue
            for root, dirs, files in os.walk(search_dir):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                depth = root.replace(search_dir, '').count(os.sep)
                if depth > 3:
                    dirs.clear()
                    continue
                for fname in files:
                    fpath = os.path.join(root, fname)
                    if query_lower and query_lower not in fname.lower():
                        continue
                    if ext_filter and not any(fname.lower().endswith(ext) for ext in ext_filter):
                        continue
                    if time_cutoff:
                        try:
                            if os.path.getmtime(fpath) < time_cutoff:
                                continue
                        except OSError:
                            continue
                    try:
                        results.append({
                            "name": fname,
                            "path": fpath,
                            "size": os.path.getsize(fpath),
                            "modified": datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%Y-%m-%d %H:%M"),
                        })
                    except OSError:
                        pass
                    if len(results) >= 20:
                        break
                if len(results) >= 20:
                    break
        return {"status": "success", "query": query, "count": len(results), "files": results}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def find_file_smart(name: str, location: str = "") -> dict:
    """Fuzzy file search — finds files by partial name, even without extension."""
    try:
        home = os.path.expanduser("~")
        all_dirs = ["Desktop", "Documents", "Downloads", "Pictures", "Videos"]

        location_map = {
            "desktop": "Desktop", "downloads": "Downloads", "download": "Downloads",
            "documents": "Documents", "document": "Documents", "docs": "Documents",
            "pictures": "Pictures", "photos": "Pictures", "images": "Pictures",
            "videos": "Videos", "video": "Videos", "music": "Music",
        }
        loc_key = location.lower().strip() if location else ""
        if loc_key and loc_key in location_map:
            primary = location_map[loc_key]
            ordered = [primary] + [d for d in all_dirs if d != primary]
        else:
            ordered = all_dirs

        search_dirs = [os.path.join(home, d) for d in ordered]
        name_lower = name.lower().strip()
        candidates = []

        for search_dir in search_dirs:
            if not os.path.exists(search_dir):
                continue
            for root, dirs, files in os.walk(search_dir):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                depth = root.replace(search_dir, '').count(os.sep)
                if depth > 3:
                    dirs.clear()
                    continue
                for fname in files:
                    fpath = os.path.join(root, fname)
                    fname_lower = fname.lower()
                    fname_no_ext = os.path.splitext(fname_lower)[0]

                    if fname_lower == name_lower:
                        score = 100
                    elif fname_no_ext == name_lower:
                        score = 90
                    elif fname_no_ext.startswith(name_lower):
                        score = 80
                    elif name_lower in fname_no_ext:
                        score = 70
                    else:
                        ratio = SequenceMatcher(None, name_lower, fname_no_ext).ratio()
                        if ratio >= 0.55:
                            score = int(ratio * 65)
                        else:
                            continue

                    candidates.append({
                        "name": fname,
                        "path": fpath,
                        "score": score,
                        "size": os.path.getsize(fpath) if os.path.exists(fpath) else 0,
                    })
                    if len(candidates) >= 50:
                        break
                if len(candidates) >= 50:
                    break

        candidates.sort(key=lambda x: x["score"], reverse=True)
        top = candidates[:5]
        return {
            "status": "success" if top else "not_found",
            "query": name,
            "best_match": top[0] if top else None,
            "candidates": top,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
