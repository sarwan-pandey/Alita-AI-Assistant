import json
import urllib.request
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

results = []

def check(name, url, method="GET", payload=None):
    try:
        req = urllib.request.Request(url, method=method)
        if payload:
            req.add_header("Content-Type", "application/json")
            data = json.dumps(payload).encode("utf-8")
        else:
            data = None
        with urllib.request.urlopen(req, data=data, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            parsed = json.loads(body) if (body.startswith("{") or body.startswith("[")) else body[:100]
            results.append((name, True, parsed))
    except Exception as e:
        results.append((name, False, str(e)))

# 1. Check Backend Health
check("Backend API Core (/health)", "http://localhost:8000/health")

# 2. Check Phone Status
check("Live Phone Companion (/api/phone/status)", "http://localhost:8000/api/phone/status")

# 3. Check Phone View-Tree extraction
check("Phone Screen View-Tree (/api/phone/view-tree)", "http://localhost:8000/api/phone/view-tree")

# 4. Check Frontend Web Server
check("Frontend UI Server (:5173)", "http://localhost:5173")

# 5. Check Voice Pipeline
check("Voice Engine Router (/voices)", "http://localhost:8000/voices")

print("=" * 65)
print("ALITA FULL SYSTEM COMPREHENSIVE RUNTIME AUDIT")
print("=" * 65)
all_ok = True
for name, ok, val in results:
    if not ok:
        all_ok = False
    status = "[ONLINE / PASS]" if ok else "[FAILED]"
    print(f"{status} {name}")
    if isinstance(val, dict):
        if isinstance(val.get("device"), dict):
            dev = val["device"]
            print(f"   ├── Device Model: {dev.get('deviceModel')}")
            print(f"   ├── Battery: {dev.get('batteryPercent')}% (Charging: {dev.get('isCharging')})")
            print(f"   ├── Screen On: {dev.get('isScreenOn')}")
            print(f"   ├── A11y Active: {dev.get('accessibilityActive')}")
            print(f"   ├── Notif Listener: {dev.get('notificationListenerActive')}")
            print(f"   └── Active Package: {dev.get('currentPackage')}")
        elif "tree" in val:
            nodes = val.get("tree", {}).get("nodes", [])
            pkg = val.get("tree", {}).get("package", "unknown")
            print(f"   └── Live View-Tree Nodes: {len(nodes)} interactive elements in '{pkg}'")
        elif "status" in val:
            print(f"   └── Status: {val.get('status')}")

print("=" * 65)
if all_ok:
    print(">>> 100% OPERATIONAL: All core services & mobile companion are LIVE! <<<")
else:
    print(">>> WARNING: Some services reported issues. <<<")
print("=" * 65)
