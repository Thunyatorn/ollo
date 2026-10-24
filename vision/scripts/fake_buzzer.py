"""A stand-in wrist buzzer: connects to the vision service, prints what it is told, and can tap "acknowledge" by itself.

    python scripts/fake_buzzer.py buzzer-maria [--url ws://127.0.0.1:8000/buzzer] [--auto-ack-after 2] [--seconds 60]
"""
import argparse, asyncio, json, time
import websockets


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("buzzer_id")
    ap.add_argument("--url", default="ws://127.0.0.1:8000/buzzer")
    ap.add_argument("--auto-ack-after", type=float, default=None)
    ap.add_argument("--seconds", type=float, default=60)
    a = ap.parse_args()
    end = time.time() + a.seconds
    async with websockets.connect(a.url) as ws:
        await ws.send(json.dumps({"type": "hello", "buzzer_id": a.buzzer_id, "battery": 0.9}))
        print(f"[{a.buzzer_id}] connected", flush=True)
        while time.time() < end:
            try:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.0))
            except asyncio.TimeoutError:
                continue
            if msg["type"] == "ping":
                continue
            print(f"[{a.buzzer_id}] {time.strftime('%H:%M:%S')} received {msg}", flush=True)
            if msg["type"] == "buzz" and a.auto_ack_after is not None:
                await asyncio.sleep(a.auto_ack_after)
                await ws.send(json.dumps({"type": "ack", "buzzer_id": a.buzzer_id, "alert_id": msg["alert_id"]}))
                print(f"[{a.buzzer_id}] {time.strftime('%H:%M:%S')} TAPPED: acknowledge {msg['alert_id']}", flush=True)

asyncio.run(main())
