# worker_mobile.py
import asyncio
import websockets
import json
import uuid
import psutil
import os
import time
import subprocess
import json as jsonlib

DEVICE_ID = str(uuid.uuid4())[:8]
COORDINATOR_URI = "ws://192.168.100.5:5000"

def get_cpu_free():
    try:
        return round(100 - psutil.cpu_percent(interval=0.5), 2)
    except Exception:
        try:
            with open("/proc/stat") as f:
                cpu_times1 = list(map(int, f.readline().split()[1:]))
            idle1, total1 = cpu_times1[3], sum(cpu_times1)

            time.sleep(0.3)

            with open("/proc/stat") as f:
                cpu_times2 = list(map(int, f.readline().split()[1:]))
            idle2, total2 = cpu_times2[3], sum(cpu_times2)

            usage = (1 - ((idle2 - idle1) / (total2 - total1))) * 100
            return round(100 - usage, 2)
        except Exception:
            return 0.0

def get_ram_free_mb():
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    total_free_mb = (mem.available + swap.free) // (1024 * 1024)
    return total_free_mb

def get_battery_info():
    try:
        out = subprocess.check_output(["termux-battery-status"])
        return jsonlib.loads(out.decode())
    except Exception:
        return {}

def get_resource_info():
    return {
        "cpu_free": get_cpu_free(),
        "ram_free_mb": get_ram_free_mb(),
        "battery": get_battery_info()
    }

async def worker_loop():
    while True:
        try:
            async with websockets.connect(COORDINATOR_URI) as websocket:
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
