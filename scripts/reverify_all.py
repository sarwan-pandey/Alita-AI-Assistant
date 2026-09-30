import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

failures = []
passed = 0

def check(condition, message):
    global passed
    if condition:
        passed += 1
        print(f"  [PASS] {message}")
    else:
        failures.append(message)
        print(f"  [FAIL] {message}")

print("=== REVERIFICATION: Assistant Name Rename (Alita -> MJ) ===")

# 1. backend/main.py
print("\n1. Verifying backend/main.py...")
with open('backend/main.py', 'r', encoding='utf-8') as f:
    main_txt = f.read()

check('"name": "MJ (Chatterbox Turbo)"' in main_txt, 'main.py: Voice named MJ (Chatterbox Turbo)')
check('"=== MJ Assistant Backend starting… ==="' in main_txt, 'main.py: Log header uses MJ')
check('title="MJ Assistant API"' in main_txt, 'main.py: API title is MJ Assistant API')
check('"hey MJ"' in main_txt and '"hey mj"' in main_txt, 'main.py: Wake phrases include MJ')
check('"MJ"' in main_txt and '"mj"' in main_txt, 'main.py: Wake single words include MJ')
check('def _strip_wake_word(transcript: str, custom_name: str = "MJ")' in main_txt, 'main.py: _strip_wake_word default is MJ')
check('elif turn.startswith("MJ:"):' in main_txt, 'main.py: _build_history handles MJ: turn')
check('session.transcript_buffer += f"\\nMJ: {full_response}"' in main_txt, 'main.py: Transcript buffer uses MJ:')
check('"name": "MJ Premium"' in main_txt, 'main.py: Subscription name is MJ Premium')

# 2. backend/engines/llm_engine.py
print("\n2. Verifying backend/engines/llm_engine.py...")
with open('backend/engines/llm_engine.py', 'r', encoding='utf-8') as f:
    llm_txt = f.read()

check('You are MJ — a warm, emotionally intelligent AI companion' in llm_txt, 'llm_engine.py: System prompt starts with "You are MJ"')
check('via the MJ Companion Bridge' in llm_txt, 'llm_engine.py: Phone bridge refers to MJ Companion Bridge')
check('MJ_SYSTEM = ALITA_SYSTEM' in llm_txt, 'llm_engine.py: MJ_SYSTEM alias defined')

# 3. backend/core/personality_engine.py & session_manager.py
print("\n3. Verifying backend core state...")
with open('backend/core/personality_engine.py', 'r', encoding='utf-8') as f:
    pers_txt = f.read()
check('custom_name: str = "MJ"' in pers_txt, 'personality_engine.py: custom_name default is MJ')
check('name = custom_name or "MJ"' in pers_txt, 'personality_engine.py: name fallback is MJ')

with open('backend/core/session_manager.py', 'r', encoding='utf-8') as f:
    sess_txt = f.read()
check('custom_name: str       = "MJ"' in sess_txt, 'session_manager.py: custom_name default is MJ')

# 4. backend/engines (proactive, lie_detector, macro_recorder, task_planner, phone_orchestrator)
print("\n4. Verifying backend engines...")
with open('backend/engines/proactive_agent.py', 'r', encoding='utf-8') as f:
    pro_txt = f.read()
check('"title": "MJ Says: Put That Phone Down! 📱"' in pro_txt, 'proactive_agent.py: "MJ Says: Put That Phone Down!"')
check('"title": "MJ Says: GO TO SLEEP! 😠"' in pro_txt, 'proactive_agent.py: "MJ Says: GO TO SLEEP!"')
check('"title": "MJ Misses You 💭"' in pro_txt, 'proactive_agent.py: "MJ Misses You"')

with open('backend/engines/lie_detector.py', 'r', encoding='utf-8') as f:
    lie_txt = f.read()
check('good\\s*night\\s*(?:mj|alita)' in lie_txt, 'lie_detector.py: Regex matches "good night mj"')
check('MJ Mood:' in lie_txt, 'lie_detector.py: Formats "MJ Mood"')

with open('backend/engines/macro_recorder.py', 'r', encoding='utf-8') as f:
    macro_txt = f.read()
check('teach\\s+(?:alita|mj)' in macro_txt, 'macro_recorder.py: Regex matches "teach mj"')

with open('backend/engines/task_planner.py', 'r', encoding='utf-8') as f:
    task_txt = f.read()
check('^(mj|alita|hey mj' in task_txt, 'task_planner.py: Strips "mj", "hey mj"')

with open('backend/engines/phone_orchestrator.py', 'r', encoding='utf-8') as f:
    phone_orc_txt = f.read()
check('"MJ Alarm"' in phone_orc_txt, 'phone_orchestrator.py: Default alarm label is MJ Alarm')
check('"MJ Timer"' in phone_orc_txt, 'phone_orchestrator.py: Default timer label is MJ Timer')

# 5. backend threads & router
print("\n5. Verifying backend threads & routers...")
with open('backend/threads/automation_handler.py', 'r', encoding='utf-8') as f:
    auto_txt = f.read()
check('hey\\s+(?:mj|alita)' in auto_txt, 'automation_handler.py: Prefix regex includes hey mj')
check('"maximize mj"' in auto_txt, 'automation_handler.py: Command list includes "maximize mj"')
check('"minimize mj"' in auto_txt, 'automation_handler.py: Command list includes "minimize mj"')
check('You are MJ, a system automation assistant' in auto_txt, 'automation_handler.py: System prompt says You are MJ')
check('You are MJ, a voice assistant' in auto_txt, 'automation_handler.py: Voice prompt says You are MJ')

with open('backend/threads/realtime_handler.py', 'r', encoding='utf-8') as f:
    rt_txt = f.read()
check('You are MJ, a smart voice assistant' in rt_txt, 'realtime_handler.py: Prompt says You are MJ')
check('User-Agent": "MJ/1.0"' in rt_txt, 'realtime_handler.py: User-Agent is MJ/1.0')

with open('backend/decision_router.py', 'r', encoding='utf-8') as f:
    dec_txt = f.read()
check('teach\\s+(?:alita|mj)' in dec_txt, 'decision_router.py: Matches teach mj')
check('dashboard|mj|alita' in dec_txt, 'decision_router.py: Matches maximize mj')
check('window|mj|alita' in dec_txt, 'decision_router.py: Matches minimize mj')
check('arise\\s+(?:alita|mj)' in dec_txt, 'decision_router.py: Matches wake up mj')

with open('backend/launch_overlay.py', 'r', encoding='utf-8') as f:
    launch_txt = f.read()
check('title="MJ Crystal Core"' in launch_txt, 'launch_overlay.py: Window title is MJ Crystal Core')
check('"🔮 Summon / Hide MJ (Alt+A)"' in launch_txt, 'launch_overlay.py: Tray menu has Summon / Hide MJ')
check('"❌ Exit MJ"' in launch_txt, 'launch_overlay.py: Tray menu has Exit MJ')
check('"MJ AI Assistant (Alt+A)"' in launch_txt, 'launch_overlay.py: Tray tooltip has MJ AI Assistant')

with open('backend/routers/payment_router.py', 'r', encoding='utf-8') as f:
    pay_txt = f.read()
check('"name": "MJ Premium"' in pay_txt, 'payment_router.py: Plan name is MJ Premium')

# 6. Frontend
print("\n6. Verifying frontend UI & components...")
with open('frontend/index.html', 'r', encoding='utf-8') as f:
    html_txt = f.read()
check('<title>MJ</title>' in html_txt, 'index.html: Page title is MJ')
check('content="MJ — An emotionally intelligent AI assistant."' in html_txt, 'index.html: Meta description is MJ')

with open('frontend/src/App.jsx', 'r', encoding='utf-8') as f:
    app_txt = f.read()
check('const [activeView, setActiveView] = useState("mj")' in app_txt, 'App.jsx: Default activeView is "mj"')
check('new Notification("MJ Reminder"' in app_txt, 'App.jsx: Notification title is MJ Reminder')
check('activeView === "mj"' in app_txt, 'App.jsx: Active view checks for mj')
check('>MJ<' in app_txt or '\n            MJ\n' in app_txt, 'App.jsx: Toggle button label is MJ')
check('<span className="auth-logo-text">MJ</span>' in app_txt, 'App.jsx: Auth logo is MJ')

with open('frontend/src/components/audio/AudioCapture.jsx', 'r', encoding='utf-8') as f:
    audio_txt = f.read()
check('/\\bm\\s*\\.?\\s*j\\b/gi' in audio_txt, 'AudioCapture.jsx: Wake normalizer handles "m.j." / "m j"')
check('/\\bemjay\\b/gi' in audio_txt, 'AudioCapture.jsx: Wake normalizer handles "emjay"')
check('"$1 MJ"' in audio_txt, 'AudioCapture.jsx: Normalizes to "MJ"')
check('"mj"' in audio_txt, 'AudioCapture.jsx: Fast commands include "mj"')
check('"MJ is speaking · say \'stop\' or press Esc"' in audio_txt, 'AudioCapture.jsx: Speaking status says MJ')

with open('frontend/src/components/ui/DynamicIsland.jsx', 'r', encoding='utf-8') as f:
    dyn_txt = f.read()
check('"MJ Speaking"' in dyn_txt, 'DynamicIsland.jsx: State text is MJ Speaking')
check('<span className="island-title">MJ</span>' in dyn_txt, 'DynamicIsland.jsx: Island title is MJ')

with open('frontend/src/components/ui/CinematicSubtitles.jsx', 'r', encoding='utf-8') as f:
    sub_txt = f.read()
check('"✨ MJ"' in sub_txt, 'CinematicSubtitles.jsx: Assistant badge is ✨ MJ')

with open('frontend/src/components/ui/PricingPage.jsx', 'r', encoding='utf-8') as f:
    price_txt = f.read()
check('"MJ Premium"' in price_txt, 'PricingPage.jsx: Tier is MJ Premium')
check('Choose Your <span style={S.brand}>MJ</span> Plan' in price_txt, 'PricingPage.jsx: Heading says MJ')

with open('frontend/src/components/ui/TierGate.jsx', 'r', encoding='utf-8') as f:
    tier_txt = f.read()
check('<h2 className="pricing-title">MJ Premium</h2>' in tier_txt, 'TierGate.jsx: Title is MJ Premium')
check('MJ Emotional Intelligence' in tier_txt, 'TierGate.jsx: Feature list says MJ Emotional Intelligence')

with open('frontend/src/components/ui/VoiceModelChanger.jsx', 'r', encoding='utf-8') as f:
    voice_txt = f.read()
check('chatterbox_turbo_mj' in voice_txt, 'VoiceModelChanger.jsx: Active default voice is chatterbox_turbo_mj')

with open('frontend/src/components/ui/FloatingDock.jsx', 'r', encoding='utf-8') as f:
    dock_txt = f.read()
check('"Interrupt MJ (Barge-in)"' in dock_txt, 'FloatingDock.jsx: Tooltip says Interrupt MJ')

with open('frontend/src/components/ui/HolographicOverlay.jsx', 'r', encoding='utf-8') as f:
    holo_txt = f.read()
check('"MJ AI Assistant • Click to mute/unmute' in holo_txt, 'HolographicOverlay.jsx: Title says MJ AI Assistant')

with open('frontend/src/components/ui/SpatialDrawer.jsx', 'r', encoding='utf-8') as f:
    draw_txt = f.read()
check('"MJ AI Assistant"' in draw_txt, 'SpatialDrawer.jsx: Object says MJ AI Assistant')

with open('frontend/src/hooks/useOfflineLLM.js', 'r', encoding='utf-8') as f:
    off_txt = f.read()
check('"You are MJ, a helpful AI assistant' in off_txt, 'useOfflineLLM.js: Prompt says You are MJ')

with open('frontend/src/store/useSubscriptionStore.js', 'r', encoding='utf-8') as f:
    sub_store_txt = f.read()
check('"MJ Emotional AI"' in sub_store_txt, 'useSubscriptionStore.js: Feature name is MJ Emotional AI')

# 7. Android Companion App
print("\n7. Verifying Android Companion strings & services...")
with open('android_companion/app/src/main/res/values/strings.xml', 'r', encoding='utf-8') as f:
    str_txt = f.read()
check('<string name="app_name">MJ Companion</string>' in str_txt, 'strings.xml: app_name is MJ Companion')
check('<string name="accessibility_service_label">MJ Automation Service</string>' in str_txt, 'strings.xml: accessibility_service_label is MJ Automation Service')
check('Enables MJ AI Assistant on your PC' in str_txt, 'strings.xml: accessibility description says MJ AI Assistant')
check('<string name="notification_listener_label">MJ Message Bridge</string>' in str_txt, 'strings.xml: notification_listener_label is MJ Message Bridge')
check('<string name="foreground_service_channel_name">MJ Companion Bridge</string>' in str_txt, 'strings.xml: channel name is MJ Companion Bridge')
check('Maintains real-time connection with MJ Desktop' in str_txt, 'strings.xml: channel desc says MJ Desktop')

with open('android_companion/app/src/main/res/layout/activity_main.xml', 'r', encoding='utf-8') as f:
    act_txt = f.read()
check('android:text="MJ COMPANION"' in act_txt, 'activity_main.xml: Header title is MJ COMPANION')
check('Apps > MJ Companion >' in act_txt, 'activity_main.xml: Restricted settings hint says MJ Companion')
check('[READY] MJ Companion initialized.' in act_txt, 'activity_main.xml: Initial log text says MJ Companion')

with open('android_companion/app/src/main/java/ai/alita/companion/AlitaPhoneBridgeService.kt', 'r', encoding='utf-8') as f:
    kt_txt = f.read()
check('Connecting to MJ PC...' in kt_txt, 'AlitaPhoneBridgeService.kt: Notification says Connecting to MJ PC...')
check('Connected to MJ PC!' in kt_txt, 'AlitaPhoneBridgeService.kt: Notification says Connected to MJ PC!')
check('.setContentTitle("MJ Desktop Companion")' in kt_txt, 'AlitaPhoneBridgeService.kt: Notification title is MJ Desktop Companion')
check('?: "MJ Alarm"' in kt_txt, 'AlitaPhoneBridgeService.kt: Default alarm is MJ Alarm')
check('?: "MJ Timer"' in kt_txt, 'AlitaPhoneBridgeService.kt: Default timer is MJ Timer')

with open('android_companion/app/src/main/java/ai/alita/companion/MainActivity.kt', 'r', encoding='utf-8') as f:
    main_kt_txt = f.read()
check('"Enable \'MJ Automation Service\'"' in main_kt_txt, 'MainActivity.kt: Toast says Enable MJ Automation Service')
check('"Enable \'MJ Message Bridge\'"' in main_kt_txt, 'MainActivity.kt: Toast says Enable MJ Message Bridge')

print("\n" + "="*50)
print(f"RESULTS: {passed} passed, {len(failures)} failed")
if failures:
    print("FAILURES:")
    for f in failures:
        print(f" - {f}")
    sys.exit(1)
else:
    print("ALL 61 REVERIFICATION CHECKS PASSED PERFECTLY!")
    sys.exit(0)
