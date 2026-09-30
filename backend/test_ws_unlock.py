import asyncio
import websockets
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

async def test_unlock():
    uri = "ws://localhost:8000/ws?token=local_perpetual_admin_token"
    test_phrases = ["Unlock my phone", "I want you to unlock my phone", "phone unlock karo"]
    
    for phrase in test_phrases:
        async with websockets.connect(uri) as ws:
            await ws.recv()  # greeting
            payload = {"type": "text_message", "text": phrase}
            print(f"\n--- Testing Phrase: '{phrase}' ---")
            await ws.send(json.dumps(payload))
            
            tokens = []
            for _ in range(12):
                try:
                    res = await asyncio.wait_for(ws.recv(), timeout=8)
                    data = json.loads(res)
                    if data.get("type") == "llm_token":
                        tokens.append(data.get("token", ""))
                    if data.get("is_final") and any("unlocked" in t.lower() for t in tokens):
                        break
                except asyncio.TimeoutError:
                    break
            reply = "".join(tokens)
            print(f"Reply: {reply}")
            assert "unlocked" in reply.lower(), f"Did not unlock for '{phrase}'"
            assert "security reasons" not in reply.lower(), f"Refusal triggered for '{phrase}'"
            print(f"✅ PASSED for '{phrase}'")
        
        refusal = "can't directly interact" in reply.lower() or "security reasons" in reply.lower()
        if refusal:
            print("❌ FAILED: Refusal still triggered!")
        else:
            print("✅ SUCCESS: Autonomous Mobile unlock executed with zero refusal!")

if __name__ == "__main__":
    asyncio.run(test_unlock())
