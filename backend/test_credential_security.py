"""
test_credential_security.py — Test Zero-Plaintext Credential Leak Guarantee
"""

import asyncio
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from engines.phone_orchestrator import PhoneOrchestrator


def test_no_plaintext_credentials_in_backend_code():
    """Test 8: Verify no hardcoded credentials exist in backend Python source files."""
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    forbidden_secret = "Abhi2003@"

    found_in = []
    for root, dirs, files in os.walk(backend_dir):
        # Exclude venv and cache directories
        dirs[:] = [d for d in dirs if d not in ("venv", ".venv", "__pycache__", ".git", "chroma_data")]
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                # Skip test files
                if file.startswith("test_"):
                    continue
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        if forbidden_secret in content:
                            found_in.append(os.path.relpath(file_path, backend_dir))
                except Exception:
                    pass

    assert len(found_in) == 0, f"Credential found in backend source files: {found_in}"
    print("✅ Test 8 Passed: Zero plaintext credentials found in backend Python source files")


def test_unlock_command_payload_has_no_credential():
    """Test 9: Verify unlock command dispatched to companion bridge contains NO credential/pin field."""
    po = PhoneOrchestrator()
    po.device_info["connected"] = True
    dispatched_commands = []

    async def mock_sender(cmd_dict, timeout=8.0):
        dispatched_commands.append(cmd_dict)
        cmd = cmd_dict.get("command")
        if cmd == "unlock":
            po.device_info["isLocked"] = False
            return {"success": True, "isLocked": False, "verifiedUnlocked": True}
        if cmd == "get_state":
            return {"success": True, "isLocked": po.device_info.get("isLocked", True), "isScreenOn": True}
        return {"success": True}

    po.set_bridge_sender(mock_sender)

    res = asyncio.run(po.unlock_screen())
    assert res.get("success") is True

    # Find the unlock command in dispatched_commands
    unlock_cmd = next((c for c in dispatched_commands if c.get("command") == "unlock"), None)
    assert unlock_cmd is not None, "No unlock command dispatched"
    assert "pin" not in unlock_cmd, f"Unlock payload must not contain 'pin' field: {unlock_cmd}"
    assert "password" not in unlock_cmd, f"Unlock payload must not contain 'password' field: {unlock_cmd}"

    print(f"✅ Test 9 Passed: Unlock payload sent to bridge is clean: {unlock_cmd}")


if __name__ == "__main__":
    test_no_plaintext_credentials_in_backend_code()
    test_unlock_command_payload_has_no_credential()
    print("ALL CREDENTIAL SECURITY TESTS PASSED!")
