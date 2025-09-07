# workers.py
# worker.py
import asyncio
import websockets
import json
import psutil
import socket
import uuid

DEVICE_ID = str(uuid.uuid4())[:8]  # unique ID for each worker
COORDINATOR_URI = "ws://192.168.100.2:5000"

def get_resource_info():
    return {
        "cpu_free": 100 - psutil.cpu_percent(),
        "ram_free_mb": psutil.virtual_memory().available // (1024 * 1024)
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
