# workers.py
import asyncio
import websockets
import json
import socket
import uuid
import os

DEVICE_ID = str(uuid.uuid4())[:8]  # unique ID for each worker
COORDINATOR_URI = "ws://192.168.100.2:5000"  # your laptop IP

def get_resource_info():
    # Dummy CPU (since psutil not allowed on Android without root)
    cpu_free = 50.0  

    # Real RAM read from /proc/meminfo
    ram_free_mb = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if "MemAvailable" in line:
                    ram_free_kb = int(line.split()[1])
                    ram_free_mb = ram_free_kb // 1024
                    break
    except Exception:
        ram_free_mb = 0

    return {
        "cpu_free": cpu_free,
        "ram_free_mb": ram_free_mb
    }

async def worker_loop():
    async with websockets.connect(COORDINATOR_URI) as websocket:
        # Register once at start
        info = get_resource_info()
        await websocket.send(json.dumps({
            "type": "register",
            "device_id": DEVICE_ID,
            **info
        }))
        print(f"[+] Worker {DEVICE_ID} connected to coordinator.")

        # Keep sending heartbeats with free resources
        while True:
            info = get_resource_info()
            await websocket.send(json.dumps({
                "type": "heartbeat",
                "device_id": DEVICE_ID,
                **info
            }))
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(worker_loop())
