"""
Blog Publisher Workflow V2 — SEO-optimized content + images + daily limits.

Pipeline:
  1. Check daily limit (max 3 blogs/day)
  2. Generate SEO-optimized blog with professional structure
  3. Fetch topic-relevant images from Unsplash (free)
  4. AI detection loop — humanize until 95+ score
  5. Publish on Blogger with images embedded
  6. Update daily counter

Key improvements over V1:
  - SEO: meta description, keyword density, proper H2/H3 hierarchy
  - Images: 2-3 royalty-free images from Unsplash per post
  - Daily limits: enforces 3 posts/day cap
  - Shared browser: one login, all steps reuse the same session
"""

import asyncio
import json
import logging
import os
import re
import time
from datetime import date
from typing import Any, Dict, List

from engines.workflow_engine import (
    BaseWorkflow,
    WorkflowStep,
    LoopStep,
    StepResult,
)

logger = logging.getLogger("alita.workflow.blog")

# ── Config ────────────────────────────────────────────────────────────────────

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


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
    except Exception as e:
        logger.warning(f"[BlogWorkflow] Config save failed: {e}")


def _check_daily_limit(config: Dict[str, Any], kind: str = "blogs") -> bool:
    """Returns True if under daily limit, False if limit reached."""
    tracker = config.get("daily_tracker", {})
    today = date.today().isoformat()

    # Reset counter if new day
    if tracker.get("last_date") != today:
        tracker["last_date"] = today
        tracker["blogs_posted"] = 0
        tracker["shorts_uploaded"] = 0
        config["daily_tracker"] = tracker
        _save_config(config)

    limit = config.get("blogger", {}).get("daily_limit", 3)
    current = tracker.get("blogs_posted", 0)
    return current < limit


def _increment_daily_counter(kind: str = "blogs"):
    config = _load_config()
    tracker = config.get("daily_tracker", {})
    today = date.today().isoformat()
    if tracker.get("last_date") != today:
        tracker["last_date"] = today
        tracker["blogs_posted"] = 0
        tracker["shorts_uploaded"] = 0
    tracker["blogs_posted"] = tracker.get("blogs_posted", 0) + 1
    config["daily_tracker"] = tracker
    _save_config(config)


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1: Check Daily Limit
# ══════════════════════════════════════════════════════════════════════════════

class CheckDailyLimitStep(WorkflowStep):
    name = "Check Daily Limit"
    description = "Checking if daily blog quota allows posting"
    timeout_s = 5

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        config = _load_config()
        if not _check_daily_limit(config, "blogs"):
            tracker = config.get("daily_tracker", {})
            posted = tracker.get("blogs_posted", 3)
            return StepResult(
                success=False,
                message=f"Daily limit reached: {posted}/3 blogs posted today. Try tomorrow!",
            )
        posted = config.get("daily_tracker", {}).get("blogs_posted", 0)
        return StepResult(
            success=True,
            message=f"Daily quota OK ({posted}/3 used)",
            data={"_config": config},
        )


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2: Generate SEO Blog Content
# ══════════════════════════════════════════════════════════════════════════════

class GenerateSEOBlogStep(WorkflowStep):
    name = "Generate SEO Blog Content"
    description = "Writing SEO-optimized blog with professional structure"
    timeout_s = 90

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        topic = context.get("topic", "")
        if not topic:
            return StepResult(success=False, message="No topic provided")

        prompt = f"""You are a professional SEO blog writer. Write a comprehensive, SEO-optimized blog post.

TOPIC: {topic}

STRUCTURE (follow exactly):
1. Start with: # [SEO-optimized title with primary keyword]
2. Second line: META_DESC: [compelling meta description, 150-160 chars, includes keyword]
3. Third line: KEYWORDS: [5-7 comma-separated SEO keywords]

Then write the blog body with this structure:
## Introduction (2-3 paragraphs)
- Hook the reader with a surprising fact, question, or bold statement
- Explain why this topic matters RIGHT NOW
- Preview what they'll learn

## [H2 Section 1 — Primary keyword variation]
- 2-3 professional paragraphs with data/examples
- Include a relevant statistic or study reference

## [H2 Section 2 — Secondary keyword]
- 2-3 paragraphs with practical insights
- Add a real-world example or case study

### [H3 Sub-section — Long-tail keyword]
- Detailed breakdown of a specific aspect

## [H2 Section 3 — Related keyword]
- Expert perspective with actionable advice

## Key Takeaways
- 3-5 bullet points summarizing the main insights

## Final Thoughts
- Personal reflection, not a summary
- End with a thought-provoking question for engagement

WRITING RULES:
- FIRST PERSON throughout (I, my, we)
- Conversational but professional tone
- Use contractions: don't, I'm, it's, isn't, we've
- Start 2+ paragraphs with "And", "But", "So", "Look,"
- Include 3-4 rhetorical questions
- Use em dashes — like this — for asides
- Mix short punchy sentences. With longer, more flowing ones that carry the reader forward.
- Add 1-2 analogies or metaphors
- Include parenthetical asides (like quick notes to the reader)
- Target 1000-1500 words
- Keyword density: use primary keyword 4-6 times naturally

BANNED WORDS: delve, tapestry, landscape, multifaceted, in conclusion, realm, it's worth noting, in today's, pivotal, plethora, navigate, foster, embark, leverage
BANNED OPENINGS: "In today's...", "In the realm of...", "Ever wondered..."

IMAGE MARKERS — place exactly 3 of these in the text where images should go:
[IMAGE: description of relevant image to find on Unsplash]

Example: [IMAGE: AI robot working alongside doctors in modern hospital]

Write the complete blog now:"""

        try:
            text = await _generate_with_llm(prompt)
            if not text or len(text.strip()) < 200:
                return StepResult(success=False, message="LLM returned empty/short content")

            # Parse structured output
            lines = text.strip().split("\n")
            title = lines[0].lstrip("# ").strip()

            meta_desc = ""
            keywords = []
            body_start = 1
            for i, line in enumerate(lines[1:5], 1):
                if line.startswith("META_DESC:"):
                    meta_desc = line.replace("META_DESC:", "").strip()
                    body_start = i + 1
                elif line.startswith("KEYWORDS:"):
                    keywords = [k.strip() for k in line.replace("KEYWORDS:", "").split(",")]
                    body_start = i + 1

            body = "\n".join(lines[body_start:]).strip()

            # Extract image markers
            image_descs = re.findall(r'\[IMAGE:\s*(.+?)\]', body)
            # Remove markers from body (will be replaced with actual images)
            body_clean = body  # Keep markers for now, replace in publish step

            logger.info(
                f"[BlogWorkflow] Generated SEO blog: '{title[:40]}' | "
                f"{len(body)} chars | {len(keywords)} keywords | {len(image_descs)} images"
            )

            return StepResult(
                success=True,
                message=f"Generated: '{title[:40]}' ({len(body)} chars, {len(image_descs)} images)",
                data={
                    "blog_title": title,
                    "blog_body": body_clean,
                    "blog_meta_desc": meta_desc,
                    "blog_keywords": keywords,
                    "image_descriptions": image_descs,
                },
            )
        except Exception as e:
            return StepResult(success=False, message=f"Generation failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3: Fetch Images from Unsplash
# ══════════════════════════════════════════════════════════════════════════════

class FetchImagesStep(WorkflowStep):
    name = "Fetch Topic Images"
    description = "Finding royalty-free images from Unsplash"
    timeout_s = 30

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        image_descs = context.get("image_descriptions", [])
        if not image_descs:
            return StepResult(success=True, message="No images needed", data={"image_urls": []})

        image_urls = []
        for desc in image_descs[:3]:  # Max 3 images
            url = await self._search_unsplash(desc)
            if url:
                image_urls.append({"desc": desc, "url": url})

        logger.info(f"[BlogWorkflow] Found {len(image_urls)} images")
        return StepResult(
            success=True,
            message=f"Found {len(image_urls)} images",
            data={"image_urls": image_urls},
        )

    async def _search_unsplash(self, query: str) -> str:
        """Search Unsplash for a free image. Returns direct image URL."""
        try:
            import httpx

            # Unsplash Source API — free, no API key needed
            # Returns a 1600x900 image matching the query
            clean_query = re.sub(r'[^\w\s]', '', query).strip().replace(' ', ',')
            url = f"https://source.unsplash.com/1600x900/?{clean_query}"

            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.head(url)
                # Unsplash redirects to the actual image URL
                final_url = str(resp.url)
                if "images.unsplash.com" in final_url:
                    return final_url

            # Fallback: use the source URL directly (it redirects)
            return url

        except Exception as e:
            logger.warning(f"[BlogWorkflow] Unsplash search failed for '{query[:30]}': {e}")
            return ""


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4: AI Detection Loop
# ══════════════════════════════════════════════════════════════════════════════

class AICheckLoopStep(LoopStep):
    name = "AI Detection Quality Loop"
    description = "Checking and improving human-likeness score"
    max_iterations = 5
    timeout_s = 120

    async def loop_body(self, context: Dict[str, Any]) -> StepResult:
        body = context.get("blog_body", "")
        # Strip image markers for scoring
        clean = re.sub(r'\[IMAGE:\s*.+?\]', '', body)

        score = self._heuristic_score(clean)
        context["ai_score"] = score

        notify = context.get("_notify_fn")
        if notify:
            notify({
                "type": "workflow_progress",
                "message": f"Human-likeness score: {score}%",
            })

        if score >= 95:
            return StepResult(success=True, message=f"Score {score}% — passed!", data={"ai_score": score})

        # Humanize
        humanized = await self._humanize(body, score)
        context["blog_body"] = humanized
        return StepResult(
            success=True,
            message=f"Score {score}% — humanizing...",
            data={"ai_score": score, "blog_body": humanized},
        )

    async def should_stop(self, context: Dict[str, Any], result: StepResult) -> bool:
        return context.get("ai_score", 0) >= 95

    def _heuristic_score(self, text: str) -> int:
        """Local heuristic AI detector — fast and offline."""
        score = 65

        # Human markers (positive)
        checks = [
            (r"\bI\b", 3, "first person"),
            (r"\b(I'm|I've|don't|can't|won't|isn't|we're|it's|that's|here's)\b", 6, "contractions"),
            (r"\?", 4, "questions"),
            (r"^(And|But|So|Look,|Here's the thing)", 4, "casual openers"),
            (r"—|–", 3, "em dashes"),
            (r"\(.+?\)", 3, "parentheticals"),
            (r"\b(honestly|frankly|personally|actually|literally)\b", 3, "hedging"),
        ]
        for pattern, pts, _ in checks:
            if re.search(pattern, text, re.M):
                score += pts

        # AI markers (negative)
        ai_words = [
            "delve", "tapestry", "multifaceted", "it's worth noting",
            "in conclusion", "in the realm of", "landscape of",
            "pivotal", "plethora", "leverage", "foster",
        ]
        for word in ai_words:
            if word in text.lower():
                score -= 6

        # Sentence variety
        sentences = re.split(r'[.!?]+', text)
        lengths = [len(s.split()) for s in sentences if s.strip()]
        if lengths and len(lengths) > 3:
            avg = sum(lengths) / len(lengths)
            variance = sum((l - avg) ** 2 for l in lengths) / len(lengths)
            if variance > 40:
                score += 5
            elif variance < 10:
                score -= 5

        return min(100, max(0, score))

    async def _humanize(self, text: str, current_score: int) -> str:
        prompt = f"""This blog scored {current_score}% human-likeness (needs 95%+).
Rewrite to sound MORE human. Keep all facts, structure, headings, and [IMAGE:] markers.

Changes to make:
- More contractions (don't, I'm, it's, we've)
- More first person (I, my, we)
- Add rhetorical questions
- Start some paragraphs with And, But, So
- Use sentence fragments. Short ones.
- Add dashes — for asides
- Remove any formal/robotic phrases
- Keep the same word count

Text:
{text}

Rewritten:"""
        try:
            result = await _generate_with_llm(prompt)
            if result and len(result.strip()) > 200:
                return result.strip()
        except Exception:
            pass
        return text


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5: Publish on Blogger
# ══════════════════════════════════════════════════════════════════════════════

class PublishBloggerStep(WorkflowStep):
    name = "Publish on Blogger"
    description = "Publishing SEO blog with images on Blogger"
    timeout_s = 90

    async def execute(self, context: Dict[str, Any]) -> StepResult:
        title = context.get("blog_title", "Untitled")
        body = context.get("blog_body", "")
        image_urls = context.get("image_urls", [])

        if not body:
            return StepResult(success=False, message="No blog content")

        config = _load_config()
        blogger_cfg = config.get("blogger", {})
        blog_id = blogger_cfg.get("blog_id", "")

        # Replace [IMAGE: ...] markers with actual <img> tags
        html_body = self._build_html(body, image_urls)

        try:
            from engines.browser_agent import BrowserAgent

            async with BrowserAgent(headless=config.get("headless", True), profile_name="blogger") as agent:

                # Navigate to correct blog
                if blog_id:
                    page = await agent.new_page(f"https://www.blogger.com/blog/post/new/{blog_id}")
                else:
                    page = await agent.new_page("https://www.blogger.com")

                await page.wait_for_timeout(4000)

                # Auto-detect blog ID on first run
                if not blog_id:
                    blog_id = await self._detect_blog_id(page)
                    if blog_id:
                        config.setdefault("blogger", {})["blog_id"] = blog_id
                        _save_config(config)
                        await page.goto(f"https://www.blogger.com/blog/post/new/{blog_id}",
                                        wait_until="domcontentloaded")
                        await page.wait_for_timeout(3000)

                if "accounts.google.com" in page.url:
                    return StepResult(
                        success=False,
                        message="Not logged into Google. Log in to Chrome once, Alita will remember.",
                    )

                # Click "New post" if on dashboard
                new_btn = await page.query_selector('a:has-text("New post"), button:has-text("New post")')
                if new_btn:
                    await new_btn.click()
                    await page.wait_for_timeout(2000)

                # Fill title
                title_el = await page.query_selector(
                    'input[aria-label="Title"], [placeholder="Title"]')
                if title_el:
                    await title_el.fill(title)

                # Switch to HTML mode for proper formatting
                html_btn = await page.query_selector(
                    'button[aria-label="HTML"], '
                    '[data-tooltip="HTML view"]'
                )
                if html_btn:
                    await html_btn.click()
                    await page.wait_for_timeout(1000)

                # Fill body with HTML content
                body_el = await page.query_selector(
                    'textarea, '
                    '[role="textbox"][contenteditable="true"], '
                    '.post-body-container [contenteditable]'
                )
                if body_el:
                    tag = await body_el.evaluate("el => el.tagName.toLowerCase()")
                    if tag == "textarea":
                        await body_el.fill(html_body)
                    else:
                        await page.evaluate(
                            """(html) => {
                                const el = document.querySelector('[role="textbox"][contenteditable="true"]');
                                if (el) el.innerHTML = html;
                            }""", html_body)

                # Add labels/tags
                labels = blogger_cfg.get("default_labels", [])
                keywords = context.get("blog_keywords", [])
                all_labels = list(set(labels + keywords[:3]))
                labels_btn = await page.query_selector(
                    '[aria-label="Labels"], button:has-text("Labels")')
                if labels_btn and all_labels:
                    await labels_btn.click()
                    await page.wait_for_timeout(500)
                    label_input = await page.query_selector('input[aria-label="Label"]')
                    if label_input:
                        await label_input.fill(", ".join(all_labels))
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(500)

                # Publish
                await page.wait_for_timeout(1000)
                pub_btn = await page.query_selector('button:has-text("Publish"), [aria-label="Publish"]')
                if pub_btn:
                    await pub_btn.click()
                    await page.wait_for_timeout(2000)
                    confirm = await page.query_selector('button:has-text("Confirm"), button:has-text("Publish")')
                    if confirm:
                        await confirm.click()
                        await page.wait_for_timeout(3000)

                    # Increment daily counter
                    _increment_daily_counter("blogs")

                    post_url = page.url
                    return StepResult(
                        success=True,
                        message=f"✅ Published on Blogger! (ID: {blog_id})",
                        data={"published_url": post_url, "blog_id": blog_id},
                    )

                return StepResult(success=False, message="Publish button not found — check Blogger login")

        except Exception as e:
            return StepResult(success=False, message=f"Publish failed: {e}")

    def _build_html(self, body: str, image_urls: List[Dict]) -> str:
        """Convert markdown body + images to HTML for Blogger."""
        html = body

        # Replace [IMAGE: desc] markers with actual img tags
        for img in image_urls:
            marker = f'[IMAGE: {img["desc"]}]'
            img_html = (
                f'<div style="text-align:center;margin:20px 0;">'
                f'<img src="{img["url"]}" alt="{img["desc"]}" '
                f'style="max-width:100%;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.1);" />'
                f'<p style="color:#666;font-size:0.85em;margin-top:6px;">{img["desc"]}</p>'
                f'</div>'
            )
            html = html.replace(marker, img_html, 1)

        # Remove any remaining image markers
        html = re.sub(r'\[IMAGE:\s*.+?\]', '', html)

        # Markdown to HTML
        html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.M)
        html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.M)
        html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.M)
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.M)

        # Wrap paragraphs
        parts = html.split("\n\n")
        result = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if p.startswith(("<h", "<div", "<li", "<ul", "<ol")):
                result.append(p)
            elif "<li>" in p:
                result.append(f"<ul>{p}</ul>")
            else:
                result.append(f"<p>{p}</p>")

        return "\n\n".join(result)

    async def _detect_blog_id(self, page) -> str:
        url = page.url
        m = re.search(r'blogger\.com/blog/(?:posts|pages)/(\d+)', url)
        if m:
            return m.group(1)
        link = await page.query_selector('a[href*="/blog/posts/"]')
        if link:
            href = await link.get_attribute("href") or ""
            m = re.search(r'/blog/posts/(\d+)', href)
            if m:
                return m.group(1)
        content = await page.content()
        m = re.search(r'"blogId"\s*:\s*"(\d+)"', content)
        return m.group(1) if m else ""


# ══════════════════════════════════════════════════════════════════════════════
# COMPLETE WORKFLOW
# ══════════════════════════════════════════════════════════════════════════════

class BlogPublishWorkflow(BaseWorkflow):
    name = "Blog Publisher"
    description = "SEO blog → Images → AI quality → Publish on Blogger"

    def get_steps(self) -> List[WorkflowStep]:
        return [
            CheckDailyLimitStep(),
            GenerateSEOBlogStep(),
            FetchImagesStep(),
            AICheckLoopStep(),
            PublishBloggerStep(),
        ]


# ══════════════════════════════════════════════════════════════════════════════
# LLM HELPERS
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
            lambda: ollama_chat(
                prompt=prompt,
                system="You are a professional SEO blog writer.",
                max_tokens=4000,
                temperature=0.8,
            ),
        )
        return result or ""
    except Exception as e:
        logger.error("[BlogWorkflow] Ollama LLM failed: %s", e)
        return ""

