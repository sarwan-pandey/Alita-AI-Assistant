"""
Alita Decision Router V2 — Classifies user queries into 3 task types.

Uses keyword matching (fast) with LLM fallback (smart) to route queries
to the appropriate handler thread.

Routes:
  - "general"    → Conversation, Q&A, knowledge
  - "realtime"   → Time, weather, news, live data
  - "automation"  → System control, files, apps, commands

V2 Improvements:
  - Anti-false-positive guard: "open question" no longer triggers automation
  - Conversational exclusion list prevents action verbs in questions from
    being misclassified
  - Require specific targets (app names, file paths) for automation matches
  - All patterns pre-compiled into single alternation regex for O(1) matching
"""

import re
import logging

log = logging.getLogger("alita.router")


# ── Conversational EXCLUSION — these phrases contain action verbs but
#    are NOT commands. Check BEFORE automation patterns. ────────────────────
CONVERSATIONAL_EXCLUSIONS = [
    # Questions about how to do things
    r"\b(how\s+to\s+(open|close|start|write|create|delete|save|install|send|find|unlock|lock|call|dial|set\s+alarm|set\s+timer|take\s+photo))\b",
    r"\b(can\s+you\s+(explain|tell|describe|help|suggest))\b",
    r"\b(explain|describe|clarify)\b",
    r"\b(analyze|analyse)\s+(this|the|that|a|an)?\b",
    r"\b(what\s+(is|are|does|should|would|could|will|happens))\b",
    r"\b(do\s+you\s+(know|think|like|have|want|remember|understand))\b",
    r"\b(tell\s+me\s+(about|how|why|what|who|when|more))\b",
    # Conversational uses of action verbs
    r"\b(open\s+(question|mind|heart|book|discussion|ended|source|minded|marriage))\b",
    r"\b(close\s+(to|friend|call|enough|relationship|attention|minded|by|at))\b",
    r"\b(start\s+(thinking|feeling|learning|wondering|believing|over|from|with))\b",
    r"\b(play\s+(a\s+role|fair|safe|nice|along|dead|hard|important|an?\s+\w+\s+role))\b",
    r"\b(call\s+(it|this|that|me|him|her|them|yourself|upon|off|out|into\s+question))\b",
    # "write about X?" = asking about writing, not commanding to write
    r"\b(write\s+(down|up|about)\s+.+\?)\b",
    # Questions ending with ?
    r"(should\s+i|could\s+you|would\s+you|will\s+you|can\s+i)\s+.+\?",
]

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
    # ── File operations (specific — not just "file") ──────────────────
    r"\b(create\s+file|make\s+file|write\s+file|read\s+file|delete\s+file|remove\s+file)\b",
    r"\b(create\s+folder|make\s+folder|make\s+directory|new\s+folder|delete\s+folder)\b",
    r"\b(list\s+files|show\s+files|what\s+files|files\s+in|folder\s+contents)\b",
    r"\b(save\s+to|write\s+to|append\s+to|edit\s+file|modify\s+file)\b",

    # ── App control (V2: require KNOWN app name after verb) ───────────
    # Instead of "open\s+\w+" (matches "open question"), require known apps
    r"\b(open|launch|start)\s+(notepad|chrome|firefox|edge|excel|word|powerpoint|spotify|"
    r"vscode|vs\s+code|calculator|paint|terminal|explorer|settings|discord|telegram|"
    r"whatsapp|teams|slack|zoom|brave|opera|vlc|blender|figma|postman|obs|notion|"
    r"skype|steam|powershell|cmd|command\s+prompt|browser|file\s+explorer|"
    r"task\s+manager|control\s+panel|snipping\s+tool|store|microsoft\s+store)\b",

    r"\b(close|kill)\s+(notepad|chrome|firefox|edge|excel|word|powerpoint|spotify|"
    r"vscode|vs\s+code|calculator|paint|terminal|explorer|discord|telegram|whatsapp|"
    r"teams|slack|zoom|brave|this|the\s+window|the\s+app|all\s+windows)\b",

    r"\b(run\s+command|execute|command\s+prompt)\b",

    # ── BROAD INTENT SIGNALS — catch natural phrasing without exact app names ──
    # "open the/my/that X app/software/program/editor"
    r"\b(open|launch|start)\s+(the\s+|my\s+|that\s+)?\w+\s+(app|software|program|editor|player|manager)\b",
    # "open X" where X looks like an app (single/double word, no question words)
    r"\b(open|launch|start)\s+(?!a\s+|an\s+|the\s+door|the\s+box|up\s+|my\s+mind|your\s+)([a-z]+)\b",
    # "close/quit/exit X" (broader — if they say close, it's likely an app)
    r"\b(close|quit|exit)\s+(?!the\s+door|my\s+eyes|enough)([a-z]+)\b",

    # ── Shorthand app/platform names ──────────────────────────────────
    r"\b(open|launch|play\s+on|search\s+on|go\s+to)\s+(yt|insta|ig|wp|tg|fb|linkedin|li|gh|github)\b",
    r"\b(yt|youtube)\s+(pe|par|pr)\s+(search|play|dekho|chalao|bajao)\b",  # Hindi: "yt pe search karo"

    # ── Browser Autopilot & Active Page Actions ───────────────────────
    r"\b(summarize\s+(this\s+)?(page|webpage|tab|article|website)|what\s+is\s+this\s+(page|article)\s+about)\b",
    r"\b(extract\s+(links|headings|data|tables|outline)\s+(from\s+this\s+page)?)\b",
    r"\b(page\s+summary|webpage\s+summary|article\s+summary|read\s+this\s+webpage)\b",

    # ── Folder navigation ─────────────────────────────────────────────
    r"\b(navigate\s+to|go\s+to\s+(the\s+)?(downloads?|documents?|desktop|pictures?|photos?|videos?|music|home))\b",
    r"\b(open\s+(the\s+)?(downloads?|documents?|desktop|pictures?|photos?|videos?|music)\s*(folder)?)\b",
    r"\b(show\s+(me\s+)?(my\s+)?(downloads?|documents?|desktop|pictures?|photos?|videos?|music))\b",

    # ── Keyboard shortcuts / in-app interaction ───────────────────────
    r"\b(press\s+\w+|ctrl\s*\+|alt\s*\+|shift\s*\+|send\s+keys?)\b",
    r"\b(new\s+file|save\s+(the\s+)?file|save\s+as|undo|redo|select\s+all|refresh|reload)\b",
    r"\b(close\s+(this|the)?\s*(window|tab)|minimize|maximize|fullscreen|full\s+screen)\b",

    # ── File/folder creation (specific) ───────────────────────────────
    r"\b(create|make|new)\s+(a\s+)?(file|folder|directory|document|text\s+file|python\s+file|html\s+file)\b",
    r"\b(banao|bana\s+do|naya)\s+(file|folder)\b",  # Hindi

    # ── Hindi/Hinglish app control (with known targets) ───────────────
    r"\b(notepad|chrome|excel|word|calculator|paint|spotify|discord|telegram|whatsapp)\s+(kholo|khole|khol\s+do)\b",
    r"\b(kholo|khole|open\s+karo)\s+(notepad|chrome|excel|word|calculator|paint|spotify|discord|telegram|whatsapp)\b",
    r"\b(band\s+karo|band\s+kar\s+do|close\s+karo)\s+\w+\b",
    r"\b(chalu\s+karo|start\s+karo|launch\s+karo|run\s+karo|chalao)\b",
    # Broad Hindi: "X kholo" / "X chalu karo" (any app name before Hindi verb)
    r"\b\w+\s+(kholo|khole|khol\s+do|chalu\s+karo|band\s+karo)\b",

    # ── Hindi file/folder ops ─────────────────────────────────────────
    r"\b(file|folder)\s+(banao|bana\s+do|delete\s+karo|hatao|copy\s+karo|move\s+karo)\b",
    r"\b(save\s+karo|save\s+kar\s+do|bachao)\b",

    # ── Hindi folder navigation ───────────────────────────────────────
    r"\b(desktop|downloads?|documents?)\s+(kholo|dikhao|me\s+jao)\b",

    # ── System controls ───────────────────────────────────────────────
    r"\b(volume\s+(up|down)|increase\s+volume|decrease\s+volume|set\s+volume)\b",
    r"\b(mute|unmute|toggle\s+mute|sound\s+off|sound\s+on|awaz\s+band)\b",
    r"\b(brightness|increase\s+brightness|decrease\s+brightness|dim\s+screen)\b",
    r"\b(dark\s+mode|night\s+mode|light\s+mode)\b",
    r"\b(lock\s+screen|lock\s+computer|lock\s+pc)\b",
    r"\b(empty\s+recycle|recycle\s+bin|clear\s+recycle)\b",
    r"\b(wifi\s+on|wifi\s+off|toggle\s+wifi|enable\s+wifi|disable\s+wifi)\b",
    r"\b(screenshot|take\s+screenshot)\b",

    # ── Install / Uninstall ───────────────────────────────────────────
    r"\b(install\s+\w+|uninstall\s+\w+|download\s+\w+)\b",
    r"\b(install\s+status|what.s\s+installing|check\s+download|task\s+status)\b",

    # ── System info ───────────────────────────────────────────────────
    r"\b(battery|disk\s+space|ram\s+usage|cpu\s+usage|system\s+info|storage)\b",
    r"\b(running\s+processes|task\s+manager|ip\s+address|hostname)\b",

    # ── Macro Workflows ───────────────────────────────────────────────
    r"\b(work\s+mode|chill\s+mode|study\s+mode|focus\s+mode|coding\s+mode|developer\s+mode|presentation\s+mode|meeting\s+mode)\b",
    r"\b(start\s+work\s+mode|start\s+coding\s+mode|start\s+study\s+mode|enable\s+work\s+mode|enable\s+chill\s+mode)\b",

    # ── Smart Search ──────────────────────────────────────────────────
    r"\b(find\s+file|search\s+file|locate\s+file|where\s+is.*file)\b",

    # ── Music Control + MOOD-AWARE MUSIC (NEW) ────────────────────────
    r"\b(play\s+music|pause\s+music|stop\s+music|resume\s+music|next\s+song|previous\s+song|skip\s+song)\b",
    r"\b(play\s+on\s+spotify|play\s+on\s+youtube|gaana\s+bajao|music\s+play|play\s+song)\b",
    # Broad "play X" — catches "play arijit", "play something chill", "play lofi"
    r"\bplay\s+(?!a\s+role|fair|safe|nice|along|dead|hard|important|an?\s+\w+\s+role)\w+",
    # Mood-based music triggers
    r"\b(play|bajao|chalao).*(mood|feeling|vibe|chill|relax|energetic|sad|happy|romantic|party)\b",
    r"\b(mood|feeling|vibe).*(music|song|gaana|sangeet)\b",
    # Play on shorthand platforms
    r"\bplay\s+.+\s+on\s+(yt|youtube|spotify|gaana|jiosaavn)\b",

    # ── Smart Reminders ───────────────────────────────────────────────
    r"\b(remind\s+me|set\s+reminder|create\s+reminder)\b",
    r"\b(show\s+reminders|list\s+reminders|my\s+reminders)\b",

    # ── Clipboard ─────────────────────────────────────────────────────
    r"\b(clipboard\s+history|what\s+did\s+i\s+copy|last\s+copied)\b",
    r"\b(copy\s+to\s+clipboard|paste\s+from\s+history)\b",

    # ── Song Recognition ──────────────────────────────────────────────
    r"\b(what|which)\s+(is\s+)?(this\s+|the\s+)?(song|music|tune|track)\b",
    r"\b(what|which)\s+(song|music|tune|track)\s+(is\s+)?(this|playing|that)?\b",
    r"\b(identify|recognize|name|detect|find|tell\s+me)\s+(this\s+|the\s+)?(song|music|tune|track)\b",
    r"\b(what('s|\s+is)\s+(playing|this\s+playing|this\s+song)|what\s+am\s+i\s+listening|shazam|konsa\s+gaana|ye\s+gaana)\b",
    r"\b(ye\s+kya\s+baj|gaana\s+bata|song\s+bata|gaana\s+pehchaan)\b",
    r"\b(recognize\s+this|identify\s+this|shazam\s+this)\b",

    # ── WhatsApp / Messaging ─────────────────────────────────────────
    r"\b(send.*whatsapp|whatsapp.*message|message.*whatsapp)\b",
    r"\b(send.*message\s+to|whatsapp\s+pe\s+bhejo)\b",
    r"\b(share.*file.*whatsapp|send.*file.*whatsapp|whatsapp\s+file)\b",

    # ── File Sharing ──────────────────────────────────────────────────
    r"\b(send|share|bhejo|forward)\s+.*(file|document|photo|image|video|pdf|resume|report).*\s+(to|on|via)\b",
    r"\b(send|share)\s+.*\s+(telegram|discord|email|mail)\b",

    # ── Shutdown/restart/sleep ────────────────────────────────────────
    r"\b(shut\s*down|shutdown|restart\s+(computer|pc|system)|reboot|sleep\s+mode|hibernate)\b",
    r"\b(turn\s+off\s+(computer|pc|system)|cancel\s+shutdown)\b",

    # ── Network diagnostics ──────────────────────────────────────────
    r"\b(ping\s+\w+|traceroute|ip\s+address|my\s+ip|ipconfig|nslookup|dns\s+lookup)\b",
    r"\b(flush\s+dns|active\s+connections|netstat|external\s+ip|public\s+ip)\b",

    # ── Hindi system ops ─────────────────────────────────────────────
    r"\b(bluetooth\s+chalu|bluetooth\s+band|shutdown\s+karo|restart\s+karo|sleep\s+karo)\b",
    r"\b(volume\s+badhao|volume\s+kam|awaz\s+badhao|awaz\s+kam)\b",
    r"\b(screenshot\s+lo|screen\s+capture)\b",

    # ── Retry / Verify / Redo (must re-execute, NOT go to general LLM) ──
    r"^(do\s+it\s+again|try\s+again|retry|redo|redo\s+it|repeat\s+it|repeat\s+that)$",
    r"^(check\s+again|verify|verify\s+it|reverify|re-verify|re\s+verify)$",
    r"^(is\s+it\s+done|did\s+it\s+(open|close|work|start)|check\s+if\s+it\s+(opened|closed|worked))$",
    r"^(phir\s+se\s+karo|dubara\s+karo|fir\s+se|wapas\s+karo|dobara)$",  # Hindi retry

    # ── Mobile / Phone / Android Automation ───────────────────────────
    r"\b(on\s+my\s+phone|on\s+the\s+phone|for\s+the\s+phone|for\s+my\s+phone|for\s+phone|phone\s+pe|phone\s+par|phone\s+mein|phone\s+me)\b",
    r"\b(on\s+my\s+mobile|my\s+mobile|for\s+the\s+mobile|for\s+mobile|mobile\s+pe|mobile\s+par|mobile\s+mein|mobile\s+me)\b",
    r"\b(unlock\s+(?:my\s+)?(?:phone|mobile)|lock\s+(?:my\s+)?(?:phone|mobile)|phone\s+(?:ko\s+)?unlock|phone\s+(?:ko\s+)?lock)\b",
    r"\b(phone\s+(pe|par|mein|me)\s+(kholo|khole|open|start|launch|chalao|bhejo|send|type|likh))\b",
    r"\b(open|launch|start)\s+.+\s+(on\s+phone|on\s+mobile|on\s+android)\b",
    r"\b(phone\s+battery|mobile\s+battery|phone\s+charge|mobile\s+charge)\b",
    r"\b(phone\s+(status|state|info|detail)|mobile\s+(status|state|info|detail))\b",
    r"\b((?:phone|mobile)\s+notifications?|(?:latest|recent|show|check|see|my)\s+(?:my\s+)?(?:phone\s+|mobile\s+)?notifications?)\b",
    r"\b(reply\s+(to|on)\s+.+\s+notification|notification\s+(ka|ko|pe)\s+reply)\b",
    r"\b(swipe|tap|scroll|click)\s+.+\s+(on\s+phone|on\s+mobile|phone\s+pe|phone\s+par)\b",
    r"\b(phone\s+screen|mobile\s+screen|phone\s+ka\s+screen|android\s+screen)\b",
    r"\b(phone\s+pe\s+message|phone\s+se\s+message|phone\s+pe\s+call|call\s+from\s+phone)\b",
    r"\b(companion|android\s+companion|phone\s+companion)\b",
    r"\b(install\s+on\s+phone|uninstall\s+from\s+phone|phone\s+pe\s+install)\b",
    r"\b(take\s+photo|take\s+selfie|phone\s+camera|open\s+camera\s+on\s+phone)\b",
    r"\b(phone\s+volume|mobile\s+volume|phone\s+brightness|mobile\s+brightness)\b",
    r"\b(phone\s+wifi|mobile\s+wifi|phone\s+bluetooth|mobile\s+bluetooth)\b",
    r"\b(phone\s+pe\s+dikhao|phone\s+pe\s+dekho|phone\s+pe\s+padho)\b",

    # ── Phone Calls ──────────────────────────────────────────────────
    r"\b(call\s+\w+|dial\s+\w+|ring\s+\w+|make\s+(?:a\s+)?call|phone\s+call)\b",
    r"\b(call\s+karo|call\s+laga|phone\s+karo|call\s+lagao)\b",
    r"\b(end\s+call|hang\s+up|cut\s+(?:the\s+)?call|disconnect\s+call|call\s+kat|call\s+kaat)\b",
    r"\b(answer|pick\s+up|accept|receive|uthao)\s+(?:the\s+)?(?:call|phone)\b",
    r"\b(reject|decline|ignore|cut)\s+(?:the\s+)?(?:call|incoming)\b",
    r"\b(call\s+(?:uthao|utha\s+lo|pick\s+karo|cut\s+karo))\b",
    r"\b(speaker\s+(?:on|off|chalu|band)|loudspeaker)\b",

    # ── WiFi / Bluetooth / Connectivity ──────────────────────────────
    r"\b(wifi|bluetooth|bt|hotspot|tethering|airplane|flight\s+mode|hawa\s+jahaz)\s+(on|off|chalu|band|enable|disable|toggle)\b",
    r"\b(turn\s+(?:on|off)\s+(?:wifi|bluetooth|hotspot|airplane|mobile\s+data))\b",
    r"\b(connect|disconnect)\s+(?:wifi|bluetooth|bt)\b",
    r"\b(wifi|bluetooth)\s+(?:chalu|band|connect|disconnect)\s+karo\b",

    # ── DND / Silent / Ringer ────────────────────────────────────────
    r"\b(do\s+not\s+disturb|dnd|silent\s+mode|vibrate\s+mode|ringer)\s*(on|off|enable|disable)?\b",
    r"\b(phone\s+(?:ko\s+)?(?:silent|vibrate|chup)\s+(?:karo|kar\s+do))\b",

    # ── URL / Web Navigation ────────────────────────────────────────
    r"\b(open|go\s+to|visit|navigate\s+to)\s+(?:https?://)?[\w.-]+\.(?:com|org|net|io|dev|in)\b",
    r"\b(open|go\s+to)\s+(?:the\s+)?(?:website|site|url|link)\b",

    # ── Notification Management ─────────────────────────────────────
    r"\b(clear|dismiss|remove|delete)\s+(?:all\s+)?(?:notifications?|notifs?)\b",
    r"\b(notifications?\s+(?:hatao|saaf\s+karo|delete\s+karo|clear\s+karo))\b",

    # ── Navigation (Google Maps) ────────────────────────────────────
    r"\b(navigate|directions?|route)\s+(?:to|for)\s+.+\b",
    r"\b(how\s+to\s+(?:get|go|reach))\s+(?:to\s+)?.+\b",

    # ── Auto Rotate ─────────────────────────────────────────────────
    r"\b(auto\s*rotate|screen\s+rotation)\s+(on|off|enable|disable)\b",

    # ── UPI / Payments ───────────────────────────────────────────────
    r"\b(send|pay|transfer)\s+(?:rs\.?|inr|rupees?|\d+|one|two|three|four|five|six|seven|eight|nine|ten|twenty|fifty|hundred|thousand)\s+.*\b",
    r"\b(send|pay|transfer)\s+.+\s+(?:rupees?|rs\.?|paise|bucks)\b",
    r"\b(gpay|phonepe|paytm|upi)\b.*?\b(\d+|to|ko|pe|par|karo|bhejo|pay|transfer)\b",
    r"\b(send|pay|transfer)\s+(?:money|cash|paisa|paise)\b",
    r"\b.+\s+ko\s+.*?(?:rupees?|rs\.?|\d+)\s+(?:bhejo|transfer|pay|send)\b",

    # ── SMS / Text ───────────────────────────────────────────────────
    r"\b(send\s+(?:an?\s+)?sms|send\s+(?:a\s+)?text|text\s+to|sms\s+to|sms\s+bhejo|text\s+karo)\b",

    # ── Volume (phone-specific) ──────────────────────────────────────
    r"\b(phone\s+volume|mobile\s+volume|volume\s+(?:badha|kam|up|down)|awaaz\s+(?:badha|kam))\b",
    r"\b(mute\s+phone|phone\s+mute|silent\s+mode|phone\s+silent|unmute\s+phone)\b",
    r"\b(max\s+volume|full\s+volume|volume\s+full|volume\s+max|puri\s+awaaz)\b",

    # ── Media Playback (phone) ───────────────────────────────────────
    r"\b(pause\s+(?:phone\s+)?music|resume\s+(?:phone\s+)?music|phone\s+music\s+(?:play|pause))\b",
    r"\b(next\s+song|skip\s+(?:song|track)|previous\s+(?:song|track)|agla\s+gaana|pichla\s+gaana)\b",
    r"\b(gaana\s+(?:roko|chalao|bajao)|song\s+roko)\b",

    # ── Flashlight / Torch ───────────────────────────────────────────
    r"\b(flashlight|torch)\s+(on|off|chalu|band|jalao|bujhao)\b",
    r"\b(turn\s+(?:on|off)\s+(?:flashlight|torch))\b",

    # ── Alarm & Timer ────────────────────────────────────────────────
    r"\b(set\s+(?:an?\s+)?alarm|alarm\s+(?:set|laga|lagao|baja)|wake\s+me\s+up)\b",
    r"\b(set\s+(?:a\s+)?timer|timer\s+(?:set|laga|lagao)|start\s+timer|countdown)\b",

    # ── Camera / Photo ───────────────────────────────────────────────
    r"\b(open\s+camera|camera\s+(?:kholo|open))\b",
    r"\b(take|click|capture|snap)\s+(?:a\s+)?(?:photo|picture|selfie|pic|snap|image)\b",
    r"\b(photo|selfie|picture)\s+(?:lo|lelo|click\s+karo|capture\s+karo|kheencho)\b",

    # ── Clipboard ────────────────────────────────────────────────────
    r"\b(copy\s+to\s+phone|phone\s+(?:pe|clipboard)|clipboard\s+sync|paste\s+from\s+phone)\b",
    r"\b(phone\s+(?:se|ka)\s+(?:copy|paste|clipboard))\b",

    # ── Brightness (phone) ───────────────────────────────────────────
    r"\b(phone\s+brightness|mobile\s+brightness|brightness\s+(?:set|badha|kam))\b",
    r"\b(screen\s+brightness\s+(?:up|down|max|min|low|high))\b",

    # ── Lock / Screenshot (phone) ────────────────────────────────────
    r"\b(lock\s+(?:my\s+)?phone|phone\s+lock\s+karo|lock\s+screen)\b",
    r"\b(phone\s+screenshot|mobile\s+screenshot|screenshot\s+on\s+phone)\b",
]

# ── Vision & Screen Understanding Patterns ──────────────────────────────────
VISION_PATTERNS = [
    # Explicit screen perception queries (English & variations)
    r"\b(?:what.*screen|see.*screen|look.*screen|watch.*screen|check.*screen|inspect.*screen|read.*screen|describe.*screen|analyze.*screen|on\s+(?:my|the)\s+screen)\b",
    r"\bwhat\s+do\s+you\s+see\b",
    r"\bwhat\s+(?:are\s+you\s+seeing|are\s+you\s+see)\b",
    r"\bwhat\s+am\s+i\s+looking\s+at\b",
    r"\bexplain\s+(?:this\s+)?error|what\s+is\s+this\s+error\b",
    # Hindi screen perception queries
    r"\bscreen\s+(?:par\s+kya|pe\s+kya|dekho|padho|batao)\b",
    r"\bmeri\s+screen\s+(?:dekho|dekhiye|par\s+kya)\b",
]

# ── Song Recognition Patterns (High Priority) ───────────────────────────────
SONG_PATTERNS = [
    r"\b(what|which)\s+(is\s+)?(this\s+|the\s+)?(song|music|tune|track)\b",
    r"\b(what|which)\s+(song|music|tune|track)\s+(is\s+)?(this|playing|that)?\b",
    r"\b(identify|recognize|name|detect|find|tell\s+me)\s+(this\s+|the\s+)?(song|music|tune|track)\b",
    r"\b(what('s|\s+is)\s+(playing|this\s+playing|this\s+song)|what\s+am\s+i\s+listening|shazam|konsa\s+gaana|ye\s+gaana)\b",
    r"\b(ye\s+kya\s+baj|kya\s+baj\s+raha|gaana\s+bata|song\s+bata|gaana\s+pehchaan)\b",
    r"\b(recognize\s+this|identify\s+this|shazam\s+this)\b",
]


# ── Browser Autopilot Patterns (High Priority) ───────────────────────────────
BROWSER_PATTERNS = [
    r"\b(summarize\s+(?:this\s+)?(?:page|webpage|tab|article|website)|what\s+is\s+this\s+(?:page|article|website)\s+about)\b",
    r"\b(extract\s+(?:all\s+|the\s+)?(links|headings|data|tables|outline)\s*(?:from\s+(?:this\s+)?(?:page|webpage|site|tab))?)\b",
    r"\b(page\s+summary|webpage\s+summary|article\s+summary|read\s+this\s+webpage)\b",
    r"\b(give\s+me\s+(?:the\s+)?(?:page\s+outline|headings))\b",
]


# ── Custom Voice Macro Patterns (High Priority) ──────────────────────────────
MACRO_PATTERNS = [
    r"\b(remember\s+(this\s+)?(routine|macro|workflow)|save\s+(macro|routine|workflow)|teach\s+(?:alita|mj))\b",
    r"\b(list\s+(my\s+)?(macros|routines)|show\s+(my\s+)?(macros|routines)|delete\s+(macro|routine))\b",
    r"\b(start|run|launch|execute|activate)\s+([a-zA-Z0-9_\s\-]+)\s+(mode|routine|macro|session)\b",
]


# ── UI Mode / Expansion Patterns (High Priority) ──────────────────────────────
UI_MODE_PATTERNS = [
    r"\b(maximize\s+(?:yourself|display|ui|screen|window|dashboard|mj|alita)|full\s*screen|expand\s+(?:display|ui|window)|bada\s+karo)\b",
    r"\b(minimize\s+(?:yourself|display|ui|screen|window|mj|alita)|collapse\s+(?:display|ui|window)|hide\s+(?:yourself|ui|display)|chota\s+karo|overlay\s+mode)\b",
    r"\b(arise\s+(?:alita|mj)|wake\s+up\s+(?:alita|mj)|(?:alita|mj)\s+awake)\b",
]


# ── Pre-compiled single alternation regex per category ────────────────────

def _build_combined_regex(patterns: list[str]) -> re.Pattern:
    """Combine multiple regex patterns into a single alternation regex."""
    combined = "|".join(f"(?:{p})" for p in patterns)
    return re.compile(combined, re.IGNORECASE)


_AUTOMATION_RE = _build_combined_regex(AUTOMATION_PATTERNS)
_SONG_RE = _build_combined_regex(SONG_PATTERNS)
_BROWSER_RE = _build_combined_regex(BROWSER_PATTERNS)
_MACRO_RE = _build_combined_regex(MACRO_PATTERNS)
_UI_MODE_RE = _build_combined_regex(UI_MODE_PATTERNS)
_REALTIME_RE = _build_combined_regex(REALTIME_PATTERNS)
_VISION_RE = _build_combined_regex(VISION_PATTERNS)
_EXCLUSION_RE = _build_combined_regex(CONVERSATIONAL_EXCLUSIONS)


def classify_query(text: str) -> str:
    """
    Classify a user query into: 'vision', 'automation', 'realtime', or 'general'.

    V2: Checks conversational exclusions BEFORE automation patterns
    to prevent "how to open notepad" from being treated as "open notepad".
    """
    text_lower = text.lower().strip()

    # ── Check vision requests FIRST (Screen understanding) ────────────
    if _VISION_RE.search(text_lower):
        log.info("Router: VISION — matched screen analysis pattern")
        return "vision"

    # ── Check Song Recognition (Highest Priority Automation) ──────────
    if _SONG_RE.search(text_lower):
        log.info("Router: AUTOMATION — matched song recognition pattern")
        return "automation"

    # ── Check UI Mode / Expansion Commands ───────────────────────────
    if _UI_MODE_RE.search(text_lower):
        log.info("Router: AUTOMATION — matched UI mode command")
        return "automation"

    # ── Check Browser Autopilot (High Priority Automation) ────────────
    if _BROWSER_RE.search(text_lower):
        log.info("Router: AUTOMATION — matched browser autopilot pattern")
        return "automation"

    # ── Check Voice Macros (High Priority Automation) ─────────────────
    if _MACRO_RE.search(text_lower):
        log.info("Router: AUTOMATION — matched voice macro pattern")
        return "automation"

    # ── Check exclusions — prevent false automation matches ───────────
    if _EXCLUSION_RE.search(text_lower):
        if _REALTIME_RE.search(text_lower):
            log.info("Router: REALTIME — matched despite conversational context")
            return "realtime"
        log.info("Router: GENERAL — conversational exclusion matched")
        return "general"

    # ── Check Semantic Target Binder (Slot-based Intent Resolution) ──
    try:
        from engines.semantic_target_binder import semantic_target_binder
        from engines.world_model import world_model
        sem = semantic_target_binder.resolve(text_lower, world_model.get_snapshot())
        if sem.get("action") in ("play_media", "open_app", "close_app", "system_control", "communicate") and sem.get("confidence", 0) >= 0.8:
            log.info("Router: AUTOMATION — Semantic target resolved: action=%s, app=%s, device=%s",
                     sem.get("action"), sem.get("app"), sem.get("target_device"))
            return "automation"
    except Exception as _sem_e:
        log.debug("Semantic router check error: %s", _sem_e)

    # ── Check automation (highest priority for commands) ───────────────
    if _AUTOMATION_RE.search(text_lower):
        log.info("Router: AUTOMATION — matched combined pattern")
        return "automation"

    # ── Check realtime ────────────────────────────────────────────────
    if _REALTIME_RE.search(text_lower):
        log.info("Router: REALTIME — matched combined pattern")
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

- general: casual conversation, Q&A, jokes, knowledge, opinions, greetings,
  questions about how to do things, explanations, descriptions
- realtime: time, weather, news, web search, calculations, live data, current events
- automation: file operations, open/close apps, system info, commands, screenshots,
  keyboard shortcuts (press ctrl+s, save, undo), folder navigation (go to downloads),
  file/folder creation, volume/brightness control, minimize/maximize, any system action

IMPORTANT: Questions ABOUT actions (like "how to open notepad") are GENERAL, not automation.
Only actual commands ("open notepad") are automation.

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
