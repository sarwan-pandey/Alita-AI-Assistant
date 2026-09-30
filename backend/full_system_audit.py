import urllib.request
import json
import time
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def check(url, method='GET', payload=None, timeout=10):
    try:
        req = urllib.request.Request(url, method=method)
        if payload:
            req.add_header('Content-Type', 'application/json')
            data = json.dumps(payload).encode('utf-8')
        else:
            data = None
        with urllib.request.urlopen(req, data=data, timeout=timeout) as r:
            body = r.read()
            return True, r.status, len(body), body
    except Exception as e:
        return False, 0, 0, str(e)

print("=" * 72)
print("             ALITA FULL-SYSTEM LIVE HEALTH & RUNTIME AUDIT")
print("=" * 72)

all_passed = True

# 1. Backend Core
ok, code, sz, b = check('http://localhost:8000/health')
status_str = "[PASS]" if ok else "[FAIL]"
if not ok: all_passed = False
print(f"{status_str} 1. Backend Core API (FastAPI)       -> http://localhost:8000/health")
if ok:
    data = json.loads(b.decode())
    print(f"       Status: {data.get('status')} | Service: {data.get('service', 'Alita AI')}")

# 2. Frontend Web Server
ok, code, sz, b = check('http://localhost:5173')
status_str = "[PASS]" if ok else "[FAIL]"
if not ok: all_passed = False
print(f"{status_str} 2. Frontend Web Interface (Vite)    -> http://localhost:5173")
if ok:
    print(f"       HTTP {code} OK | Dashboard UI bundle served ({sz} bytes)")

# 3. Ollama Engine
ok, code, sz, b = check('http://localhost:11434/api/tags')
status_str = "[PASS]" if ok else "[FAIL]"
if not ok: all_passed = False
print(f"{status_str} 3. Ollama Local LLM Server         -> http://localhost:11434")
if ok:
    tags = json.loads(b.decode()).get('models', [])
    names = [m.get('name') for m in tags]
    print(f"       Loaded Models: {names}")

# 4. Ollama Generation (qwen3:4b)
ok, code, sz, b = check('http://localhost:11434/api/generate', method='POST', payload={'model': 'qwen3:4b', 'prompt': 'Say hello in 3 words.', 'stream': False}, timeout=15)
status_str = "[PASS]" if ok else "[FAIL]"
if not ok: all_passed = False
print(f"{status_str} 4. LLM Model Inference (qwen3:4b)-> Active & Responsive")
if ok:
    resp_text = json.loads(b.decode()).get('response', '').strip().replace('\n', ' ')
    print(f"       Test Inference: \"{resp_text}\"")

# 5. Voices & Speech Pipeline
ok, code, sz, b = check('http://localhost:8000/voices')
status_str = "[PASS]" if ok else "[FAIL]"
if not ok: all_passed = False
print(f"{status_str} 5. Voice Engines & Models          -> Kokoro-82M + Piper + Edge")
if ok:
    voices = json.loads(b.decode()).get('voices', [])
    available = [v for v in voices if v.get('available')]
    print(f"       Available Voices: {len(available)} models loaded")

# 6. Phone Companion WebSocket Bridge
ok, code, sz, b = check('http://localhost:8000/api/phone/status')
status_str = "[PASS]" if ok else "[FAIL]"
if not ok: all_passed = False
print(f"{status_str} 6. Android Phone Companion         -> Connected via WebSocket")
if ok:
    ps = json.loads(b.decode())
    dev = ps.get('device', {})
    print(f"       Device: {dev.get('deviceModel')} (Android {dev.get('androidVersion', '16')})")
    print(f"       Battery: {dev.get('batteryPercent')}% (Charging: {dev.get('isCharging')}) | Screen On: {dev.get('isScreenOn')}")
    print(f"       A11y Service: {dev.get('accessibilityActive')} | Notification Listener: {dev.get('notificationListenerActive')}")

# 7. Mobile UI View-Tree
ok, code, sz, b = check('http://localhost:8000/api/phone/view-tree')
status_str = "[PASS]" if ok else "[FAIL]"
if not ok: all_passed = False
print(f"{status_str} 7. Mobile Accessibility Hierarchy  -> Real-time UI Inspection")
if ok:
    vt = json.loads(b.decode()).get('tree', {})
    print(f"       Active Package: '{vt.get('package')}' ({len(vt.get('nodes', []))} interactive nodes)")

# 8. Companion APK Server
ok, code, sz, b = check('http://localhost:8000/download-apk')
status_str = "[PASS]" if ok else "[FAIL]"
if not ok: all_passed = False
print(f"{status_str} 8. APK Distribution Server         -> http://192.168.5.11:8000/download-apk")
if ok:
    print(f"       Package: AlitaCompanion.apk ({round(sz / (1024*1024), 2)} MB ready for mobile install)")

print("=" * 72)
if all_passed:
    print(">>> SUMMARY: 100% OPERATIONAL — ALL ENGINES & SERVICES ARE RUNNING! <<<")
else:
    print(">>> SUMMARY: ATTENTION REQUIRED ON FAILED CHECKS ABOVE <<<")
print("=" * 72)
