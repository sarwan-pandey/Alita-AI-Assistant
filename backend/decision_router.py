"""
Alita Decision Router — Classifies user queries into 3 task types.

Uses keyword matching (fast) with LLM fallback (smart) to route queries
to the appropriate handler thread.

Routes:
  - "general"    → Conversation, Q&A, knowledge
  - "realtime"   → Time, weather, news, live data
  - "automation"  → System control, files, apps, commands
"""

import re
import logging

log = logging.getLogger("alita.router")

# ── Keyword patterns for fast classification ──────────────────────────────

REALTIME_PATTERNS = [
    # Time
    r"\b(what\s+time|current\s+time|time\s+now|date\s+today|what\s+day|what\s+date)\b",
    r"\b(kitne\s+baje|samay\s+kya|aaj\s+ka\s+din|tarikh)\b",  # Hindi
    # Weather
    r"\b(weather|temperature|forecast|rain|sunny|humidity|mausam|garmi|sardi)\b",
    # News / Search
    r"\b(latest\s+news|headlines|search\s+for|look\s+up|google|trending)\b",
    # Math
    r"\b(calculate|what\s+is\s+\d|solve|math|equation|plus|minus|multiply|divide)\b",
    r"\b(\d+\s*[\+\-\*\/\^]\s*\d+)\b",
    # Daily Briefing
    r"\b(good\s+morning|daily\s+briefing|brief\s+me|start\s+my\s+day|morning\s+update)\b",
    r"\b(subah|suprabhat|good\s+evening.*brief)\b",  # Hindi greetings
]

AUTOMATION_PATTERNS = [
    # File operations
    r"\b(create\s+file|make\s+file|write\s+file|read\s+file|delete\s+file|remove\s+file)\b",
    r"\b(create\s+folder|make\s+folder|make\s+directory|new\s+folder|delete\s+folder)\b",
    r"\b(list\s+files|show\s+files|what\s+files|files\s+in|folder\s+contents)\b",
    r"\b(save\s+to|write\s+to|append\s+to|edit\s+file|modify\s+file)\b",
    # App control
    r"\b(open\s+\w+|launch\s+\w+|start\s+\w+|close\s+\w+|kill\s+\w+|shut\s*down)\b",
    r"\b(open\s+chrome|open\s+notepad|open\s+browser|open\s+calculator|open\s+terminal)\b",
    r"\b(run\s+command|execute|terminal|cmd|powershell|command\s+prompt)\b",
    # Folder navigation
    r"\b(navigate\s+to|go\s+to\s+(the\s+)?(downloads?|documents?|desktop|pictures?|photos?|videos?|music|home))\b",
    r"\b(open\s+(the\s+)?(downloads?|documents?|desktop|pictures?|photos?|videos?|music)\s*(folder)?)\b",
    r"\b(show\s+(me\s+)?(my\s+)?(downloads?|documents?|desktop|pictures?|photos?|videos?|music))\b",
    # Keyboard shortcuts / in-app interaction
    r"\b(press\s+\w+|ctrl\s*\+|alt\s*\+|shift\s*\+|send\s+keys?)\b",
    r"\b(new\s+file|save\s+(the\s+)?file|save\s+as|undo|redo|select\s+all|refresh|reload)\b",
    r"\b(close\s+(this|the)?\s*(window|tab)|minimize|maximize|fullscreen|full\s+screen)\b",
    # File/folder creation (universal)
    r"\b(create|make|new)\s+(a\s+)?(file|folder|directory|document|text\s+file|python\s+file|html\s+file)\b",
    r"\b(banao|bana\s+do|naya)\s+(file|folder)\b",  # Hindi
    # ── Hindi/Hinglish file & folder operations ──────────────────────
    r"\b(file|folder|directory)\s+(kholo|kholna|khole|kholke|khol\s+do)\b",
    r"\b(kholo|khole|open\s+karo|kholke\s+dikhao)\s+.*(file|folder)\b",
    r"\b(file|folder)\s+(banao|bana\s+do|bana\s+de|create\s+karo)\b",
    r"\b(naya|nayi|nai|new)\s+(file|folder|document)\s*(banao|bana|bana\s+do)?\b",
    r"\b(file|folder)\s+(delete\s+karo|delete\s+kar\s+do|hata\s+do|hatao|mita\s+do|mitao|remove\s+karo)\b",
    r"\b(file|folder)\s+(copy\s+karo|copy\s+kar\s+do|move\s+karo|move\s+kar\s+do)\b",
    r"\b(ye|yeh|is|isko|iss)\s+(file|folder)\s*(ko)?\s*(kholo|delete|copy|move|rename|hatao|hata)\b",
    r"\b(rename\s+karo|naam\s+badlo|naam\s+badal\s+do)\b",
    r"\b(dikhao|dikha\s+do|batao)\s+.*(files?|folders?|documents?)\b",
    r"\b(save\s+karo|save\s+kar\s+do|save\s+karke|bachao|bacha\s+lo)\b",
    r"\b(read\s+karo|padho|padh\s+ke\s+sunao|file\s+padho)\b",
    # ── Hindi/Hinglish app control ────────────────────────────────────
    r"\b(kholo|kholna|khole)\s+\w+\b",  # "kholo chrome", "kholo notepad"
    r"\b\w+\s+(kholo|khole|khol\s+do)\b",  # "chrome kholo", "calculator khol do"
    r"\b(band\s+karo|band\s+kar\s+do|close\s+karo|bund\s+karo)\s+\w*\b",
    r"\b\w+\s+(band\s+karo|band\s+kar\s+do|close\s+karo)\b",
    r"\b(chalu\s+karo|start\s+karo|launch\s+karo|run\s+karo|chalao)\b",
    r"\b(app|application|software)\s+(kholo|band|install|uninstall|chalao)\b",
    r"\b(settings|setting)\s+(kholo|dikhao|open\s+karo)\b",
    # ── Hindi/Hinglish folder navigation ──────────────────────────────
    r"\b(desktop|downloads?|documents?|pictures?|photos?|videos?|music)\s+(kholo|dikhao|me\s+jao|dikha\s+do|pe\s+jao)\b",
    r"\b(desktop|downloads?|documents?)\s+(folder)?\s*(kholna|khole|me\s+le\s+jao)\b",
    r"\b(jao|le\s+jao|chalo)\s+.*(desktop|downloads?|documents?|pictures?)\b",
    # ── Hindi/Hinglish system control ─────────────────────────────────
    r"\b(volume|brightness|screen|awaz)\s+(badhao|kam\s+karo|zyada|increase|decrease|badha|ghata)\b",
    r"\b(awaz\s+band|mute\s+karo|unmute\s+karo|sound\s+band|sound\s+chalu)\b",
    r"\b(screen\s+lock|lock\s+karo|computer\s+lock)\b",
    r"\b(wifi\s+chalu|wifi\s+band|bluetooth\s+chalu|bluetooth\s+band)\b",
    r"\b(screenshot\s+lo|screenshot\s+le\s+lo|screen\s+capture)\b",
    r"\b(clipboard\s+dikhao|copy\s+kiya\s+tha|paste\s+karo)\b",
    r"\b(search\s+karo|dhundho|dhundh|talash\s+karo|khoj)\s+.*(file|folder)?\b",
    # In-app search / compound search
    r"\b(search\s+(for\s+)?.*\s+in\s+\w+|find\s+.*\s+in\s+(store|settings|chrome|edge|browser))\b",
    r"\b(search\s+.*\s+on\s+(youtube|amazon|github|wikipedia))\b",
    r"\b(windows\s+search|search\s+(on\s+)?(my\s+)?(computer|pc|system))\b",
    # Install / Uninstall / Download
    r"\b(install\s+\w+|uninstall\s+\w+|download\s+\w+|get\s+app)\b",
    r"\b(install\s+status|what.s\s+installing|check\s+download|task\s+status)\b",
    # System info
    r"\b(battery|disk\s+space|ram\s+usage|cpu\s+usage|system\s+info|storage)\b",
    r"\b(running\s+processes|task\s+manager|ip\s+address|hostname)\b",
    # Screenshot / clipboard
    r"\b(screenshot|take\s+screenshot|clipboard|copy\s+to|paste)\b",
    # Hindi automation
    r"\b(file\s+banao|folder\s+banao|chrome\s+kholo|app\s+kholo|band\s+karo)\b",
    # ── System Shortcuts ──────────────────────────────────────────────
    r"\b(volume\s+up|volume\s+down|increase\s+volume|decrease\s+volume|set\s+volume)\b",
    r"\b(mute|unmute|toggle\s+mute|sound\s+off|sound\s+on|awaz\s+band)\b",
    r"\b(brightness|increase\s+brightness|decrease\s+brightness|dim\s+screen)\b",
    r"\b(dark\s+mode|night\s+mode|light\s+mode|theme\s+change)\b",
    r"\b(lock\s+screen|lock\s+computer|lock\s+pc|screen\s+lock)\b",
    r"\b(empty\s+recycle|recycle\s+bin|trash|clear\s+recycle)\b",
    r"\b(wifi\s+on|wifi\s+off|toggle\s+wifi|turn.*wifi|enable\s+wifi|disable\s+wifi)\b",
    # ── Smart Search ──────────────────────────────────────────────────
    r"\b(find\s+file|search\s+file|locate\s+file|where\s+is.*file)\b",
    r"\b(find\s+the|find\s+my|look\s+for.*\.\w+|search\s+for.*file)\b",
    r"\b(find.*pdf|find.*document|find.*photo|find.*image|find.*video)\b",
    # ── Music Control ─────────────────────────────────────────────────
    r"\b(play\s+music|pause\s+music|stop\s+music|resume\s+music|next\s+song)\b",
    r"\b(previous\s+song|skip\s+song|gaana\s+bajao|music\s+play|play\s+song)\b",
    r"\b(play\s+on\s+spotify|play\s+on\s+youtube|open\s+spotify)\b",
    # ── Smart Reminders ───────────────────────────────────────────────
    r"\b(remind\s+me|set\s+reminder|create\s+reminder|add\s+reminder)\b",
    r"\b(show\s+reminders|list\s+reminders|my\s+reminders|delete\s+reminder)\b",
    r"\b(yaad\s+dila|reminder\s+set|reminder\s+lagao)\b",  # Hindi
    # ── Clipboard History ─────────────────────────────────────────────
    r"\b(clipboard\s+history|what\s+did\s+i\s+copy|last\s+copied|recent\s+copies)\b",
    r"\b(paste\s+from\s+history|show\s+clipboard|copied\s+earlier)\b",
    # ── Habit Tracker ─────────────────────────────────────────────────
    r"\b(i\s+drank|i\s+exercised|i\s+walked|i\s+meditated|i\s+studied|i\s+read)\b",
    r"\b(log\s+habit|track\s+habit|my\s+habits|habit\s+stats|show\s+streak)\b",
    r"\b(maine.*piya|maine.*kiya|habit\s+tracker)\b",  # Hindi
    # ── Mood Journal ──────────────────────────────────────────────────
    r"\b(mood\s+journal|my\s+mood|mood\s+history|how.*i.*feeling\s+lately)\b",
    r"\b(emotional\s+state|mood\s+trend|show\s+my\s+emotions|mood\s+stats)\b",
    # ── Screen Reader ─────────────────────────────────────────────────
    r"\b(read.*screen|what.*on.*screen|describe.*screen|screen\s+reader)\b",
    r"\b(ocr|read\s+text|extract\s+text.*screen|screen.*padho)\b",  # Hindi
    # ── Song Recognition (flexible — catches natural variations) ────
    r"(what|which)\s+(song|music|tune)\s+(is\s+)?(this|playing|that)",
    r"(identify|recognize|name)\s+(this\s+)?(song|music|tune)",
    r"(song|music|tune)\s+(is\s+)?(this|playing)",
    r"(what('s|s|\s+is)\s+(this|the)\s+(song|music|tune))",
    r"(what.*playing|what.*listening|shazam|konsa\s+gaana|ye\s+gaana)",
    r"(ye\s+kya\s+baj|kya\s+baj\s+raha|gaana\s+bata|song\s+bata|pehchaan)",
    r"(what('s|s)?\s+the\s+name\s+of\s+this)",
    r"(tell\s+me\s+the\s+song|bata\s+ye\s+gaana)",
    r"\b(play\s+(the\s+)?(previous|last)\s+song)\b",
    # ── Context Memory ────────────────────────────────────────────────
    r"\b(remember\s+when|what\s+did\s+we\s+talk|recall.*conversation)\b",
    r"\b(past\s+conversation|yesterday.*said|what.*i.*tell\s+you)\b",
    r"\b(do\s+you\s+remember|yaad\s+hai|pichli\s+baat)\b",  # Hindi
    # ── WhatsApp / Messaging ─────────────────────────────────────────
    r"\b(send.*whatsapp|whatsapp.*message|message.*whatsapp|whatsapp\s+bhejo)\b",
    r"\b(send.*message\s+to|text\s+\w+\s+on\s+whatsapp|whatsapp\s+pe\s+bhejo)\b",
    r"\b(share.*file.*whatsapp|send.*file.*whatsapp|whatsapp\s+file)\b",
    # ── Intelligent File Sharing (multi-app) ──────────────────────────
    r"\b(send|share|bhejo|forward)\s+.*(file|document|photo|image|video|pdf|resume|report).*\s+(to|on|via)\b",
    r"\b(send|share)\s+.*\s+(telegram|discord|email|mail)\b",
    r"\b(write\s+something\s+about|write\s+about).*\s+(send|share|bhejo)\b",
    r"\b(find\s+(my|the)\s+\w+\s*(file)?|locate\s+\w+\s*file)\b",
    r"\b(message|msg)\s+\w+\s+on\s+(telegram|discord)\b",
    # ── File sharing with location hints ──────────────────────────────
    r"\b(send|share|bhejo)\s+.*(file|document).*\s+(on|from|which\s+is\s+on)\s+(desktop|downloads|documents)\b",
    # ── Natural "send this to X" patterns ─────────────────────────────
    r"\b(send|share)\s+(this|the|ye|yeh|it|isko)\s+.*(to|ko)\s+\w+\s+(on|via|pe)\s+(whatsapp|telegram|discord)\b",
    r"\b(send|share)\s+(this|it)\s+(to|on)\b",
    # ── Phone number as contact ───────────────────────────────────────
    r"\b(send|share|bhejo)\s+.*\s+(to|on)\s+\d{10,}\b",
    # ── Hindi file sharing patterns ───────────────────────────────────
    r"\b(ye\s+file|ye\s+bhejo|isko\s+bhejo|file\s+bhejo|bhejo\s+.*pe)\b",
    r"\b(desktop\s+pe|downloads?\s+me|documents?\s+me)\s+.*(file|hai)\b",
    # ── Advanced OS Operations ───────────────────────────────────────
    # Process management
    r"\b(kill\s+process|end\s+task|terminate\s+process|process\s+info|process\s+details|set\s+priority|high\s+priority)\b",
    # Network diagnostics
    r"\b(ping\s+\w+|ping\s+test|traceroute|tracert|ip\s+address|my\s+ip|ipconfig|ip\s+config|nslookup|dns\s+lookup)\b",
    r"\b(flush\s+dns|clear\s+dns|active\s+connections|netstat|network\s+connections|external\s+ip|public\s+ip)\b",
    r"\b(network\s+diagnostic|network\s+test|connectivity\s+test)\b",
    # Scheduled tasks
    r"\b(scheduled?\s+task|cron\s+job|list\s+tasks|show\s+tasks|schedule\s+command)\b",
    # Startup apps
    r"\b(startup\s+app|startup\s+program|boot\s+app|auto\s+start|show\s+startup|list\s+startup|run\s+on\s+startup)\b",
    # Disk analysis
    r"\b(disk\s+usage|disk\s+space|drive\s+space|storage\s+space|free\s+space|how\s+much\s+space)\b",
    r"\b(largest\s+files?|biggest\s+files?|disk\s+health|drive\s+health|smart\s+status|folder\s+size)\b",
    # Bluetooth
    r"\b(bluetooth\s+(on|off|toggle|enable|disable|chalu|band|status)|turn.*(bluetooth))\b",
    # Display management
    r"\b(screen\s+resolution|display\s+resolution|change\s+resolution|refresh\s+rate|rotate\s+screen)\b",
    r"\b(connected\s+monitors?|monitor\s+info|display\s+info|list\s+monitors?)\b",
    # Power plans
    r"\b(power\s+plan|power\s+mode|high\s+performance|balanced\s+mode|power\s+saver|energy\s+mode)\b",
    # Environment variables
    r"\b(environment\s+variable|env\s+var|system\s+variable|path\s+variable|set\s+env)\b",
    # Windows services
    r"\b(windows?\s+service|start\s+service|stop\s+service|restart\s+service|list\s+services?|running\s+services?)\b",
    # System sounds
    r"\b(play\s+sound|system\s+sound|notification\s+sound|play\s+beep|beep\s+sound)\b",
    # Shutdown/restart/sleep/hibernate
    r"\b(shut\s*down|shutdown|restart\s+(computer|pc|system)|reboot|sleep\s+mode|hibernate)\b",
    r"\b(put\s+to\s+sleep|cancel\s+shutdown|abort\s+shutdown|schedule\s+shutdown|log\s*off|sign\s+(out|off))\b",
    r"\b(turn\s+off\s+(computer|pc|system)|switch\s+off\s+(computer|pc))\b",
    # Hindi advanced ops
    r"\b(bluetooth\s+chalu|bluetooth\s+band|shutdown\s+karo|restart\s+karo|sleep\s+karo)\b",
    r"\b(disk\s+dikhao|space\s+dikhao|kitna\s+space|process\s+maro)\b",
]


def classify_query(text: str) -> str:
    """
    Classify a user query into: 'general', 'realtime', or 'automation'.
    Uses keyword matching for speed.
    """
    text_lower = text.lower().strip()

    # ── Check automation first (highest priority — system actions) ─────
    for pattern in AUTOMATION_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            log.info("Router: AUTOMATION — matched pattern: %s", pattern[:40])
            return "automation"

    # ── Check realtime ────────────────────────────────────────────────
    for pattern in REALTIME_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            log.info("Router: REALTIME — matched pattern: %s", pattern[:40])
            return "realtime"

    # ── Default to general conversation ───────────────────────────────
    log.info("Router: GENERAL — no special pattern matched")
    return "general"


def classify_with_llm(text: str, llm_fn) -> str:
    """
    Use LLM to classify ambiguous queries. Fallback when keyword matching
    isn't confident enough.
    """
    prompt = f"""Classify this user query into exactly one category.
Reply with ONLY one word: general, realtime, or automation.

- general: casual conversation, Q&A, jokes, knowledge, opinions, greetings
- realtime: time, weather, news, web search, calculations, live data, current events
- automation: file operations, open/close apps, system info, commands, screenshots, 
  keyboard shortcuts (press ctrl+s, save, undo), folder navigation (go to downloads), 
  file/folder creation, volume/brightness control, minimize/maximize, any system action

Query: "{text}"
Category:"""

    try:
        result = llm_fn(prompt)
        category = result[0].strip().lower().split()[0] if result else "general"
        if category in ("general", "realtime", "automation"):
            return category
    except Exception:
        pass
    return "general"
