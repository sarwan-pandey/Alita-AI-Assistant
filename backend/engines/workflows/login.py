"""
Login Helper — Log in to Blogger and YouTube with DIFFERENT emails.

Opens a browser for each service separately:
  Step 1: Log in with your BLOGGER email
  Step 2: Log in with your YOUTUBE email

Each login is saved permanently in its own profile.

Usage:
    python -m engines.workflows.login
"""

import asyncio
import json
import os
import re
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


def _load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {"blogger": {}, "youtube": {}, "headless": True, "daily_tracker": {}}


def _save_config(config):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)


async def run_login():
    from engines.browser_agent import BrowserAgent

    config = _load_config()

    print("=" * 60)
    print("  Alita Login Setup (Multi-Account)")
    print("=" * 60)
    print()
    print("  You'll log in TWICE — once for each service:")
    print("    1. Blogger (your blogger email)")
    print("    2. YouTube (your youtube email)")
    print()
    print("  Each gets its own saved profile.")
    print("  You'll NEVER need to log in again after this.")
    print()

    # ══════════════════════════════════════════════════════════════════
    # BLOGGER LOGIN
    # ══════════════════════════════════════════════════════════════════
    print("=" * 60)
    print("  STEP 1: BLOGGER LOGIN")
    print("=" * 60)
    print()
    print("  A browser will open. Log in with your BLOGGER email.")
    print("  After logging in and seeing your blog, press Enter here.")
    print()

    async with BrowserAgent(headless=False, profile_name="blogger") as agent:
        page = await agent.new_page("https://accounts.google.com")
        await page.wait_for_timeout(2000)

        print("  [Waiting] Log in to your BLOGGER Google account...")
        print("  DO NOT close the browser! Just log in and come back here.")
        print("  Press Enter when done -->", end=" ")
        await asyncio.get_event_loop().run_in_executor(None, input)

        # Open a NEW page for Blogger (original page may be closed/redirected)
        print()
        print("  Checking Blogger...")
        try:
            page2 = await agent.new_page("https://www.blogger.com")
            await page2.wait_for_timeout(5000)
            try:
                await page2.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            url = page2.url
            print(f"  URL: {url}")

            blog_id = ""
            if "accounts.google.com" not in url:
                m = re.search(r'blogger\.com/blog/(?:posts|pages|post/new)/(\d+)', url)
                if m:
                    blog_id = m.group(1)

                if not blog_id:
                    try:
                        link = await page2.query_selector('a[href*="/blog/posts/"]')
                        if link:
                            href = await link.get_attribute("href") or ""
                            m = re.search(r'/blog/posts/(\d+)', href)
                            if m:
                                blog_id = m.group(1)
                    except Exception:
                        pass

                if not blog_id:
                    try:
                        content = await page2.content()
                        m = re.search(r'"blogId"\s*:\s*"(\d+)"', content)
                        if m:
                            blog_id = m.group(1)
                    except Exception:
                        pass

                if blog_id:
                    config.setdefault("blogger", {})["blog_id"] = blog_id
                    config["blogger"]["blog_url"] = url
                    print(f"  [OK] Blog ID: {blog_id}")
                else:
                    print("  [!] Blog ID not auto-detected.")
                    print("  Look at the URL in the browser. It looks like:")
                    print("    https://www.blogger.com/blog/posts/1234567890")
                    print("                                       ^^^^^^^^^^")
                    user_id = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: input("  Enter Blog ID (or press Enter to skip): ").strip()
                    )
                    if user_id and user_id.isdigit():
                        config.setdefault("blogger", {})["blog_id"] = user_id
                        print(f"  [OK] Blog ID saved: {user_id}")
            else:
                print("  [!] Still on Google login page. Login may not have worked.")
                print("  Enter Blog ID manually (or press Enter to skip): ", end="")
                user_id = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input().strip()
                )
                if user_id and user_id.isdigit():
                    config.setdefault("blogger", {})["blog_id"] = user_id

        except Exception as e:
            print(f"  [!] Error checking Blogger: {e}")
            print("  Enter Blog ID manually (or press Enter to skip): ", end="")
            user_id = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input().strip()
            )
            if user_id and user_id.isdigit():
                config.setdefault("blogger", {})["blog_id"] = user_id

    print()
    print("  Blogger session saved!")
    print()

    # ══════════════════════════════════════════════════════════════════
    # YOUTUBE LOGIN
    # ══════════════════════════════════════════════════════════════════
    print("=" * 60)
    print("  STEP 2: YOUTUBE LOGIN")
    print("=" * 60)
    print()
    print("  A NEW browser will open. Log in with your YOUTUBE email.")
    print("  After logging in, press Enter here.")
    print()

    async with BrowserAgent(headless=False, profile_name="youtube") as agent:
        page = await agent.new_page("https://accounts.google.com")
        await page.wait_for_timeout(2000)

        print("  [Waiting] Log in to your YOUTUBE Google account...")
        print("  DO NOT close the browser! Just log in and come back here.")
        print("  Press Enter when done -->", end=" ")
        await asyncio.get_event_loop().run_in_executor(None, input)

        # Open a NEW page for YouTube Studio
        print()
        print("  Checking YouTube Studio...")
        try:
            page2 = await agent.new_page("https://studio.youtube.com")
            await page2.wait_for_timeout(5000)
            try:
                await page2.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            url = page2.url
            print(f"  URL: {url}")

            channel_name = ""
            if "accounts.google.com" not in url:
                try:
                    ch_el = await page2.query_selector(
                        '#channel-title, .channel-name, [class*="channel-name"]')
                    if ch_el:
                        channel_name = (await ch_el.text_content() or "").strip()
                except Exception:
                    pass

                if not channel_name:
                    try:
                        content = await page2.content()
                        m = re.search(r'"channelName"\s*:\s*"([^"]+)"', content)
                        if m:
                            channel_name = m.group(1)
                        m2 = re.search(r'"externalChannelId"\s*:\s*"([^"]+)"', content)
                        if m2:
                            config.setdefault("youtube", {})["channel_id"] = m2.group(1)
                    except Exception:
                        pass

                if channel_name:
                    config.setdefault("youtube", {})["channel_name"] = channel_name
                    print(f"  [OK] Channel: {channel_name}")
                else:
                    print("  [!] Channel name not auto-detected.")
                    user_ch = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: input("  Enter Channel Name (or Enter to skip): ").strip()
                    )
                    if user_ch:
                        config.setdefault("youtube", {})["channel_name"] = user_ch
            else:
                print("  [!] Still on login page.")
                user_ch = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("  Enter Channel Name (or Enter to skip): ").strip()
                )
                if user_ch:
                    config.setdefault("youtube", {})["channel_name"] = user_ch

        except Exception as e:
            print(f"  [!] Error checking YouTube: {e}")
            user_ch = await asyncio.get_event_loop().run_in_executor(
                None, lambda: input("  Enter Channel Name (or Enter to skip): ").strip()
            )
            if user_ch:
                config.setdefault("youtube", {})["channel_name"] = user_ch

    print()
    print("  YouTube session saved!")
    print()

    # ══════════════════════════════════════════════════════════════════
    # SAVE & SUMMARY
    # ══════════════════════════════════════════════════════════════════
    _save_config(config)

    print("=" * 60)
    print("  SETUP COMPLETE!")
    print("=" * 60)
    print()
    print(f"  Blogger Blog ID:  {config.get('blogger', {}).get('blog_id', 'Not set')}")
    print(f"  YouTube Channel:  {config.get('youtube', {}).get('channel_name', 'Not set')}")
    print()
    print("  Profiles saved at:")
    print(f"    Blogger: ~/.alita/browser_profiles/blogger/")
    print(f"    YouTube: ~/.alita/browser_profiles/youtube/")
    print()
    print("  Each profile keeps its own login forever.")
    print("  You will NEVER need to log in again!")
    print()
    print("  Ready to use:")
    print('    "Create a blog about AI and publish"')
    print('    "Create a YouTube short from trending videos"')
    print()


if __name__ == "__main__":
    asyncio.run(run_login())
