"""
Workflow Setup - First-time configuration and login verification.

Run this ONCE before using blog/shorts workflows.
It verifies that the browser can access Blogger and YouTube
using your Chrome login.

Usage:
    python -m engines.workflows.setup
"""

import asyncio
import json
import logging
import os
import sys

# Fix Windows console encoding for unicode
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Add parent dirs to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("alita.setup")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def _load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {"blogger": {}, "youtube": {}, "headless": False, "daily_tracker": {}}


def _save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)


async def run_setup():
    """Interactive setup - opens browser VISIBLY so user can log in if needed."""
    import re
    from engines.browser_agent import BrowserAgent

    config = _load_config()

    print("=" * 60)
    print("  [SETUP] Alita Workflow Setup")
    print("=" * 60)
    print()
    print("This will open a browser using your Chrome profile to verify")
    print("that you're logged into Blogger and YouTube.")
    print()

    # -- Step 1: Check Blogger ----------------------------------------
    print("-" * 40)
    print("[STEP 1] Checking Blogger login...")
    print("-" * 40)

    async with BrowserAgent(headless=False) as agent:  # VISIBLE so user can log in
        page = await agent.new_page("https://www.blogger.com")
        await page.wait_for_timeout(5000)

        url = page.url
        if "accounts.google.com" in url:
            print("[!] Not logged into Google!")
            print("    -> Please log in to your Google account in the browser window.")
            print("    -> Waiting 60 seconds for you to log in...")
            for i in range(60):
                await page.wait_for_timeout(1000)
                if "blogger.com" in page.url and "accounts.google.com" not in page.url:
                    print("    [OK] Logged in!")
                    break
            else:
                print("    [TIMEOUT] Please run setup again after logging in.")
                return

        # Detect blog — wait for all redirects to finish
        await page.wait_for_load_state("networkidle", timeout=15000)
        await page.wait_for_timeout(2000)
        url = page.url
        print(f"  Blogger URL: {url}")

        blog_id = ""
        # Check URL for blog ID
        m = re.search(r'blogger\.com/blog/(?:posts|pages|post/new)/(\d+)', url)
        if m:
            blog_id = m.group(1)

        if not blog_id:
            try:
                # Check for blog links in DOM
                link = await page.query_selector('a[href*="/blog/posts/"]')
                if link:
                    href = await link.get_attribute("href") or ""
                    m = re.search(r'/blog/posts/(\d+)', href)
                    if m:
                        blog_id = m.group(1)
            except Exception:
                pass  # Page may still be navigating

        if not blog_id:
            try:
                content = await page.content()
                m = re.search(r'"blogId"\s*:\s*"(\d+)"', content)
                if m:
                    blog_id = m.group(1)
            except Exception:
                pass

        if blog_id:
            config.setdefault("blogger", {})["blog_id"] = blog_id
            config["blogger"]["blog_url"] = url
            print(f"[OK] Blogger: Blog ID = {blog_id}")
            print(f"     URL: {url}")
        else:
            print("[WARN] Could not detect Blog ID. Do you have a blog on Blogger?")
            print("       Create one at https://www.blogger.com and run setup again.")

    # -- Step 2: Check YouTube ----------------------------------------
    print()
    print("-" * 40)
    print("[STEP 2] Checking YouTube Studio login...")
    print("-" * 40)

    async with BrowserAgent(headless=False) as agent:
        page = await agent.new_page("https://studio.youtube.com")
        await page.wait_for_timeout(5000)

        url = page.url
        if "accounts.google.com" in url:
            print("[!] Not logged into YouTube!")
            print("    -> Please log in the browser window...")
            print("    -> Waiting 60 seconds...")
            for i in range(60):
                await page.wait_for_timeout(1000)
                if "studio.youtube.com" in page.url:
                    print("    [OK] Logged in!")
                    break

        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)
        print(f"  YouTube URL: {page.url}")

        # Detect channel name
        channel_name = ""
        try:
            ch_el = await page.query_selector(
                '#channel-title, .channel-name, '
                '[class*="channel-name"], '
                'ytcp-account-settings .display-name'
            )
            if ch_el:
                channel_name = (await ch_el.text_content() or "").strip()
        except Exception:
            pass

        if not channel_name:
            try:
                content = await page.content()
                m = re.search(r'"channelName"\s*:\s*"([^"]+)"', content)
                if m:
                    channel_name = m.group(1)
                # Also try external channel ID
                m2 = re.search(r'"externalChannelId"\s*:\s*"([^"]+)"', content)
                if m2:
                    config.setdefault("youtube", {})["channel_id"] = m2.group(1)
                    print(f"  YouTube Channel ID: {m2.group(1)}")
            except Exception:
                pass

        if channel_name:
            config.setdefault("youtube", {})["channel_name"] = channel_name
            print(f"[OK] YouTube: Channel = {channel_name}")
        else:
            print("[WARN] Could not detect channel name (but upload should still work)")
            print(f"       Studio URL: {page.url}")

    # -- Save config --------------------------------------------------
    _save_config(config)

    print()
    print("=" * 60)
    print("  [DONE] Setup Complete!")
    print("=" * 60)
    print()
    print(f"  Blogger Blog ID:    {config.get('blogger', {}).get('blog_id', 'Not detected')}")
    print(f"  YouTube Channel:    {config.get('youtube', {}).get('channel_name', 'Not detected')}")
    print(f"  Config saved to:    {CONFIG_PATH}")
    print(f"  Browser profile:    ~/.alita/browser_profile/")
    print()
    print("  You can now use voice commands like:")
    print('    "Create a blog about AI in healthcare and publish"')
    print('    "Create a short from trending videos and upload to YouTube"')
    print()
    print("  Daily limits: 3 blogs + 3 shorts per day")
    print()


if __name__ == "__main__":
    asyncio.run(run_setup())
