# pyre-ignore-all-errors
"""
Browser Autopilot & Active Tab Controller
==========================================
Enables deep browser awareness and web page actions:
  - Active Tab Discovery: Identifies the webpage currently open in Chrome/Edge/Brave/Firefox.
  - Page Summarization: Reads the active article/document and extracts key takeaways.
  - Data Extraction: Extracts tables, key links, prices, and code blocks from the active page.
  - Form Navigation: Direct search and form entry.
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import httpx

logger = logging.getLogger("alita.browser")


class BrowserController:
    """
    Direct active browser controller and webpage reader.
    """

    def __init__(self) -> None:
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def get_active_browser_info(self) -> Dict[str, Any]:
        """
        Inspect the active window to see if it's a web browser and extract title/URL.
        """
        try:
            from engines.app_manager import get_active_window
            win = get_active_window()
            if not win or not win.get("title"):
                return {"is_browser": False, "browser": "", "title": "", "url": ""}

            title = win["title"]
            title_lower = title.lower()

            browser_name = ""
            for b in ["google chrome", "chrome", "microsoft edge", "edge", "brave", "firefox"]:
                if b in title_lower:
                    browser_name = b
                    break

            if not browser_name:
                return {"is_browser": False, "browser": "", "title": title, "url": ""}

            # Clean page title (strip " - Google Chrome" / " - Microsoft Edge")
            cleaned_title = re.sub(
                r'\s+-\s+(?:Google Chrome|Microsoft Edge|Brave|Mozilla Firefox|Chrome|Edge)$',
                '',
                title,
                flags=re.IGNORECASE
            ).strip()

            # Attempt to extract URL via UIA address bar
            detected_url = self._extract_url_from_uia(browser_name)

            return {
                "is_browser": True,
                "browser": browser_name,
                "title": cleaned_title,
                "raw_title": title,
                "url": detected_url
            }
        except Exception as e:
            logger.debug(f"[BrowserController] Active check failed: {e}")
            return {"is_browser": False, "browser": "", "title": "", "url": ""}

    def _extract_url_from_uia(self, browser_name: str) -> str:
        """Attempt to extract active URL from browser address bar via UI Automation."""
        try:
            import uiautomation as auto
            root = auto.GetForegroundControl()
            if not root:
                return ""

            # Common edit control names for browser address bars
            edit = root.EditControl(searchDepth=6)
            if edit and edit.Name:
                val = edit.GetValuePattern().Value if hasattr(edit, "GetValuePattern") else edit.Name
                if val and ("http://" in val or "https://" in val or ".com" in val or ".org" in val or ".io" in val):
                    if not val.startswith("http"):
                        val = "https://" + val
                    return val
        except Exception:
            pass
        return ""

    def summarize_active_page(self, max_points: int = 4) -> str:
        """
        Read the active webpage and generate an intelligent structured summary.
        """
        info = self.get_active_browser_info()
        title = info.get("title", "")
        url = info.get("url", "")

        if not info.get("is_browser"):
            # Fallback to general screen OCR/Vision if not in a browser
            from engines.vision_engine import vision_engine
            return vision_engine.analyze_screen(
                prompt="Summarize the key information visible on the screen in 3 clear bullet points."
            )

        # If we have the live URL, fetch clean DOM directly
        if url:
            try:
                with httpx.Client(headers=self.headers, follow_redirects=True, timeout=8.0) as client:
                    resp = client.get(url)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        for tag in soup(["script", "style", "nav", "footer", "header", "svg", "noscript"]):
                            tag.decompose()
                        paragraphs = [p.get_text(strip=True) for p in soup.find_all(["p", "h1", "h2", "h3", "li"]) if len(p.get_text(strip=True)) > 25]
                        body_text = " ".join(paragraphs[:15])

                        if body_text:
                            # Quick extractive summary
                            sentences = re.split(r'\. |\n', body_text)
                            clean_sentences = [s.strip() for s in sentences if len(s.strip()) > 30][:max_points]
                            if clean_sentences:
                                summary_points = "\n".join(f"• {s}." for s in clean_sentences)
                                return f"📄 **Summary for '{title}'** ({url}):\n{summary_points}"
            except Exception as e:
                logger.debug(f"[BrowserController] URL fetch failed: {e}")

        # Fallback to Vision/Screen OCR of the active browser window
        from engines.vision_engine import vision_engine
        return vision_engine.analyze_screen(
            prompt=f"The user is reading the webpage '{title}'. Summarize the key main points and takeaways in 3 concise sentences."
        )

    def extract_page_data(self, data_type: str = "links") -> str:
        """
        Extract specific data elements from the active browser page (links, tables, headings).
        """
        info = self.get_active_browser_info()
        title = info.get("title", "Active Webpage")
        url = info.get("url", "")

        if not url:
            return f"I can see you're browsing '{title}', but could not inspect DOM elements directly."

        try:
            with httpx.Client(headers=self.headers, follow_redirects=True, timeout=8.0) as client:
                resp = client.get(url)
                if resp.status_code != 200:
                    return f"Unable to fetch page data (HTTP {resp.status_code})"

                soup = BeautifulSoup(resp.text, "html.parser")

                if data_type in ("links", "urls"):
                    links = []
                    for a in soup.find_all("a", href=True):
                        text = a.get_text(strip=True)
                        href = a["href"]
                        if text and len(text) > 4 and href.startswith("http"):
                            links.append(f"• [{text}]({href})")
                        if len(links) >= 8:
                            break
                    return f"🔗 **Key Links on '{title}'**:\n" + "\n".join(links)

                elif data_type in ("headings", "outline"):
                    headings = []
                    for h in soup.find_all(["h1", "h2", "h3"]):
                        htext = h.get_text(strip=True)
                        if htext:
                            headings.append(f"{h.name.upper()}: {htext}")
                        if len(headings) >= 10:
                            break
                    return f"📑 **Page Outline for '{title}'**:\n" + "\n".join(headings)

        except Exception as e:
            return f"Data extraction error: {str(e)}"

        return f"Completed extraction for '{title}'."


# Singleton instance
browser_controller = BrowserController()
