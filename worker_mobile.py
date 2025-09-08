# worker_mobile.py
import asyncio
import websockets
import json
import uuid
import psutil
import os
import time
import subprocess
import warnings
from typing import Dict, Any

# Suppress psutil warnings about swap memory on Android
warnings.filterwarnings("ignore", category=RuntimeWarning, module="psutil")

DEVICE_ID = str(uuid.uuid4())[:8]
COORDINATOR_URI = "ws://192.168.100.5:5000"

def get_cpu_free() -> float:
    """Get CPU free percentage with Android-optimized fallbacks"""
    try:
        # First try psutil with a shorter interval for mobile
        return round(100 - psutil.cpu_percent(interval=0.3), 2)
    except Exception:
        try:
            # Fallback: manual /proc/stat reading
            with open("/proc/stat") as f:
                cpu_times1 = list(map(int, f.readline().split()[1:]))
            idle1, total1 = cpu_times1[3], sum(cpu_times1)
            time.sleep(0.2)  # Shorter sleep for mobile
            with open("/proc/stat") as f:
                cpu_times2 = list(map(int, f.readline().split()[1:]))
            idle2, total2 = cpu_times2[3], sum(cpu_times2)
            
            if total2 - total1 > 0:  # Avoid division by zero
                usage = (1 - ((idle2 - idle1) / (total2 - total1))) * 100
                return round(100 - usage, 2)
            else:
                return 0.0
        except Exception:
            # Final fallback: try to get load average
            try:
                with open("/proc/loadavg") as f:
                    load = float(f.read().split()[0])
                # Rough estimation: assume 4 cores, convert load to CPU free %
                cpu_cores = os.cpu_count() or 4
                usage = min((load / cpu_cores) * 100, 100)
                return round(100 - usage, 2)
            except Exception:
                return 50.0  # Default reasonable value

def get_ram_free_mb() -> int:
    """Get available RAM in MB with Android-optimized approach"""
    try:
        mem = psutil.virtual_memory()
        # Don't rely on swap memory on Android as it often fails
        return mem.available // (1024 * 1024)
    except Exception:
        try:
            # Fallback: read /proc/meminfo directly
            meminfo = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    key, value = line.split()[0], int(line.split()[1])
                    meminfo[key[:-1]] = value  # Remove ':' from key
            
            # Calculate available memory
            available = meminfo.get('MemAvailable', 0)
            if available == 0:
                # Fallback calculation if MemAvailable not present
                free = meminfo.get('MemFree', 0)
                buffers = meminfo.get('Buffers', 0)
                cached = meminfo.get('Cached', 0)
                available = free + buffers + cached
            
            return available // 1024  # Convert KB to MB
        except Exception:
            return 0

def get_battery_info() -> Dict[str, Any]:
    """Get battery information with error handling"""
    try:
        # Check if termux-api is available
        result = subprocess.run(
            ["termux-battery-status"], 
            capture_output=True, 
            text=True, 
            timeout=3  # 3 second timeout
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
        else:
            return {"error": "termux-api not available or failed"}
    except subprocess.TimeoutExpired:
        return {"error": "battery status timeout"}
    except json.JSONDecodeError:
        return {"error": "invalid battery status response"}
    except FileNotFoundError:
        return {"error": "termux-battery-status command not found"}
    except Exception as e:
        return {"error": f"battery status failed: {str(e)}"}

def get_storage_info() -> Dict[str, Any]:
    """Get storage information"""
    try:
        usage = psutil.disk_usage('/')
        return {
            "total_gb": round(usage.total / (1024**3), 2),
            "free_gb": round(usage.free / (1024**3), 2),
            "used_percent": round((usage.used / usage.total) * 100, 2)
        }
    except Exception:
        return {"total_gb": 0, "free_gb": 0, "used_percent": 0}

def get_network_info() -> Dict[str, Any]:
    """Get basic network connectivity info"""
    try:
        # Simple connectivity check
        import socket
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return {"connected": True}
    except Exception:
        return {"connected": False}

def get_device_info() -> Dict[str, Any]:
    """Get device-specific information"""
    info = {
        "platform": "android",
        "cpu_count": os.cpu_count(),
        "device_id": DEVICE_ID
    }
    
    try:
        # Try to get Android version
        result = subprocess.run(
            ["getprop", "ro.build.version.release"], 
            capture_output=True, 
            text=True, 
            timeout=2
        )
        if result.returncode == 0:
            info["android_version"] = result.stdout.strip()
    except Exception:
        pass
        
    return info

def get_resource_info() -> Dict[str, Any]:
    """Get comprehensive resource information"""
    return {
        "cpu_free": get_cpu_free(),
        "ram_free_mb": get_ram_free_mb(),
        "battery": get_battery_info(),
        "storage": get_storage_info(),
        "network": get_network_info(),
        "device": get_device_info(),
        "timestamp": time.time()
    }

async def worker_loop():
    """Main worker loop with improved error handling and reconnection"""
    reconnect_delay = 5
    max_reconnect_delay = 60
    
    while True:
        try:
            print(f"[+] Connecting to coordinator at {COORDINATOR_URI}...")
            
            async with websockets.connect(
                COORDINATOR_URI,
                ping_interval=30,  # Send ping every 30 seconds
                ping_timeout=10,   # Wait 10 seconds for pong
                close_timeout=10   # Wait 10 seconds when closing
            ) as websocket:
                
                # Register with coordinator
                info = get_resource_info()
                register_msg = {"type": "register", **info}
                await websocket.send(json.dumps(register_msg))
                print(f"[+] Worker {DEVICE_ID} connected to coordinator (Mobile).")
                
                # Reset reconnect delay on successful connection
                reconnect_delay = 5
                
                # Main heartbeat loop
                while True:
                    try:
                        info = get_resource_info()
                        heartbeat_msg = {"type": "heartbeat", "device_id": DEVICE_ID, **info}
                        await websocket.send(json.dumps(heartbeat_msg))
                        
                        # Wait for heartbeat interval or handle incoming messages
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                            # Handle any incoming messages from coordinator
                            try:
                                data = json.loads(message)
                                msg_type = data.get("type")
                                if msg_type == "ping":
                                    await websocket.send(json.dumps({"type": "pong", "device_id": DEVICE_ID}))
                            except json.JSONDecodeError:
                                pass  # Ignore invalid JSON
                        except asyncio.TimeoutError:
                            # No message received, continue with next heartbeat
                            pass
                        except websockets.exceptions.ConnectionClosed:
                            print("[!] Connection closed by server")
                            break
                            
                    except Exception as e:
                        print(f"[!] Error in heartbeat loop: {e}")
                        break
                        
        except Exception as e:
            print(f"[!] Connection failed: {e}")
            print(f"[+] Retrying in {reconnect_delay}s...")
            await asyncio.sleep(reconnect_delay)
            
            # Exponential backoff with maximum delay
            reconnect_delay = min(reconnect_delay * 1.5, max_reconnect_delay)

def main():
    """Main entry point"""
    print(f"[+] Starting mobile worker with ID: {DEVICE_ID}")
    print(f"[+] Coordinator URI: {COORDINATOR_URI}")
    
    try:
        asyncio.run(worker_loop())
    except KeyboardInterrupt:
        print("\n[+] Worker stopped by user")
    except Exception as e:
        print(f"[!] Fatal error: {e}")

if __name__ == "__main__":
    main()
