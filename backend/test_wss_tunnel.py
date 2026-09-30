import asyncio
import json
import sys
import httpx
import websockets

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

async def test_wss():
    url = "wss://const-discipline-cyber-fought.trycloudflare.com/ws/phone"
    print(f"Connecting to {url}...")
    async with websockets.connect(url) as ws:
        print("Connected! Sending handshake...")
        await ws.send(json.dumps({
            "type": "handshake",
            "deviceModel": "RemoteCloudflarePhone",
            "androidVersion": "16",
            "batteryPercent": 92,
            "isCharging": True,
        }))
        await asyncio.sleep(1.0)
        # Check status endpoint
        async with httpx.AsyncClient() as client:
            r = await client.get("http://127.0.0.1:8000/api/phone/status")
            data = r.json()
            print("Status response from Alita Backend:")
            print(json.dumps(data, indent=2))
            assert data["device"]["deviceModel"] == "RemoteCloudflarePhone"
            assert data["device"]["batteryPercent"] == 92
            assert data["device"]["connected"] is True
            print("✅ SUCCESS: Remote phone successfully connected via Cloudflare WSS Tunnel from anywhere!")

if __name__ == "__main__":
    asyncio.run(test_wss())
