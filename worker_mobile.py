# worker_mobile.py
import asyncio
import websockets
import json
import uuid
import psutil

DEVICE_ID = str(uuid.uuid4())[:8]
COORDINATOR_URI = "ws://192.168.100.2:5000"

def get_resource_info():
    # CPU usage
    cpu_usage = psutil.cpu_percent(interval=0.5)
    cpu_free = round(100 - cpu_usage, 2)

    # RAM info
    mem = psutil.virtual_memory()
    ram_free_mb = mem.available // (1024 * 1024)

    # Battery info
    battery_info = {}
    try:
        battery = psutil.sensors_battery()
        if battery:
            battery_info = {
                "percent": battery.percent,
                "plugged": battery.power_plugged
            }
    except Exception:
        battery_info = {}

    return {
        "cpu_free": cpu_free,
        "ram_free_mb": ram_free_mb,
        "battery": battery_info
    }

async def worker_loop():
    while True:
        try:
            async with websockets.connect(COORDINATOR_URI) as websocket:
                # Register
                info = get_resource_info()
                await websocket.send(json.dumps({"type": "register", "device_id": DEVICE_ID, **info}))
                print(f"[+] Worker {DEVICE_ID} connected to coordinator (Mobile).")

                while True:
                    info = get_resource_info()
                    await websocket.send(json.dumps({"type": "heartbeat", "device_id": DEVICE_ID, **info}))
                    await asyncio.sleep(5)
        except Exception as e:
            print(f"[!] Lost connection: {e}. Retrying in 5s...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(worker_loop())
