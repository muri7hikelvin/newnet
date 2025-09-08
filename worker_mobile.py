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
import re
from typing import Dict, Any

# Suppress psutil warnings about swap memory on Android
warnings.filterwarnings("ignore", category=RuntimeWarning, module="psutil")

DEVICE_ID = str(uuid.uuid4())[:8]
COORDINATOR_URI = "ws://192.168.100.5:5000"

def get_android_memory_info():
    """Get accurate Android memory information from /proc/meminfo"""
    meminfo = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(':')
                    try:
                        value = int(parts[1])
                        meminfo[key] = value
                    except ValueError:
                        pass
        return meminfo
    except Exception:
        return {}

def get_cpu_free() -> float:
    """Get accurate CPU free percentage for Android"""
    try:
        # Read /proc/stat for accurate CPU measurement
        with open("/proc/stat") as f:
            first_line = f.readline().strip()
            if not first_line.startswith('cpu '):
                return 50.0  # Fallback
            
            parts = first_line.split()
            if len(parts) < 8:
                return 50.0
                
            # Calculate total and idle time
            user, nice, system, idle, iowait, irq, softirq = map(int, parts[1:8])
            total = user + nice + system + idle + iowait + irq + softirq
            return round((idle / total) * 100, 2)
            
    except Exception:
        return 50.0

def get_ram_free_mb() -> int:
    """Get accurate available RAM in MB for Android"""
    try:
        meminfo = get_android_memory_info()
        if not meminfo:
            # Fallback to psutil
            mem = psutil.virtual_memory()
            return mem.available // (1024 * 1024)
        
        # Calculate available memory (Android specific)
        # MemAvailable is the most accurate if available
        if 'MemAvailable' in meminfo:
            return meminfo['MemAvailable'] // 1024
        
        # Fallback calculation for older Android versions
        mem_free = meminfo.get('MemFree', 0)
        cached = meminfo.get('Cached', 0)
        buffers = meminfo.get('Buffers', 0)
        available = mem_free + cached + buffers
        return available // 1024
        
    except Exception:
        return 0

def get_battery_info() -> Dict[str, Any]:
    """Get battery information with multiple fallback methods"""
    # Method 1: Try termux-battery-status
    try:
        result = subprocess.run(
            ["termux-battery-status"], 
            capture_output=True, 
            text=True, 
            timeout=3
        )
        if result.returncode == 0:
            battery_data = json.loads(result.stdout)
            if "percentage" in battery_data and "status" in battery_data:
                return battery_data
    except Exception:
        pass
    
    # Method 2: Try reading from sysfs (Android battery interface)
    try:
        # Common battery paths in Android
        battery_paths = [
            "/sys/class/power_supply/battery/",
            "/sys/class/power_supply/Battery/",
            "/sys/class/power_supply/ac/",
        ]
        
        for base_path in battery_paths:
            try:
                capacity_path = base_path + "capacity"
                status_path = base_path + "status"
                
                if os.path.exists(capacity_path) and os.path.exists(status_path):
                    with open(capacity_path, 'r') as f:
                        percentage = int(f.read().strip())
                    
                    with open(status_path, 'r') as f:
                        status = f.read().strip().lower()
                    
                    return {
                        "percentage": percentage,
                        "status": status,
                        "source": "sysfs"
                    }
            except Exception:
                continue
    except Exception:
        pass
    
    # Method 3: Final fallback
    return {"percentage": 100, "status": "unknown", "error": "battery status unavailable"}

def get_storage_info() -> Dict[str, Any]:
    """Get accurate storage information for Android"""
    try:
        # Try using df command for accurate Android storage info
        result = subprocess.run(
            ["df", "/data", "-B1", "--output=size,used,avail,pcent"], 
            capture_output=True, 
            text=True, 
            timeout=3
        )
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:
                parts = lines[1].split()
                if len(parts) >= 4:
                    total_bytes = int(parts[0])
                    used_bytes = int(parts[1])
                    free_bytes = int(parts[2])
                    used_percent = int(parts[3].rstrip('%'))
                    
                    return {
                        "total_gb": round(total_bytes / (1024**3), 2),
                        "free_gb": round(free_bytes / (1024**3), 2),
                        "used_percent": used_percent
                    }
    except Exception:
        pass
    
    # Fallback: try psutil
    try:
        usage = psutil.disk_usage('/data')
        return {
            "total_gb": round(usage.total / (1024**3), 2),
            "free_gb": round(usage.free / (1024**3), 2),
            "used_percent": round((usage.used / usage.total) * 100, 2)
        }
    except Exception:
        # Final fallback with reasonable defaults
        return {"total_gb": 128.0, "free_gb": 64.0, "used_percent": 50.0}

def get_network_info() -> Dict[str, Any]:
    """Get network connectivity info"""
    try:
        # Check if we have any network interface with an IP address
        result = subprocess.run(
            ["ip", "addr", "show"], 
            capture_output=True, 
            text=True, 
            timeout=3
        )
        if result.returncode == 0:
            # Look for inet (IPv4) addresses that aren't localhost
            lines = result.stdout.split('\n')
            for line in lines:
                if 'inet ' in line and '127.0.0.1' not in line and '::1' not in line:
                    return {"connected": True}
        
        # Fallback to socket test
        import socket
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return {"connected": True}
        
    except Exception:
        return {"connected": False}

def get_device_info() -> Dict[str, Any]:
    """Get device-specific information"""
    info = {
        "platform": "android",
        "cpu_count": os.cpu_count() or 8,  # Default to 8 if unavailable
        "device_id": DEVICE_ID,
        "total_ram_mb": 0
    }
    
    # Get total RAM
    try:
        meminfo = get_android_memory_info()
        if 'MemTotal' in meminfo:
            info["total_ram_mb"] = meminfo['MemTotal'] // 1024
        else:
            # Estimate based on common Android device RAM sizes
            info["total_ram_mb"] = 8192  # 8GB default
    except Exception:
        info["total_ram_mb"] = 8192
    
    # Get Android version
    try:
        result = subprocess.run(
            ["getprop", "ro.build.version.release"], 
            capture_output=True, 
            text=True, 
            timeout=2
        )
        if result.returncode == 0:
            info["android_version"] = result.stdout.strip()
    except Exception:
        info["android_version"] = "unknown"
        
    # Get device model
    try:
        result = subprocess.run(
            ["getprop", "ro.product.model"], 
            capture_output=True, 
            text=True, 
            timeout=2
        )
        if result.returncode == 0:
            info["model"] = result.stdout.strip()
    except Exception:
        pass
    
    return info

def get_resource_info() -> Dict[str, Any]:
    """Get comprehensive resource information"""
    cpu_free = get_cpu_free()
    ram_free_mb = get_ram_free_mb()
    device_info = get_device_info()
    total_ram_mb = device_info.get("total_ram_mb", 8192)
    
    # Calculate RAM usage percentage
    ram_used_percent = 0
    if total_ram_mb > 0:
        ram_used_percent = round(((total_ram_mb - ram_free_mb) / total_ram_mb) * 100, 2)
    
    return {
        "cpu_free": cpu_free,
        "ram_free_mb": ram_free_mb,
        "ram_used_percent": ram_used_percent,
        "total_ram_mb": total_ram_mb,
        "battery": get_battery_info(),
        "storage": get_storage_info(),
        "network": get_network_info(),
        "device": device_info,
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
                ping_interval=30,
                ping_timeout=10,
                close_timeout=10
            ) as websocket:
                
                # Register with coordinator
                info = get_resource_info()
                register_msg = {
                    "type": "register", 
                    "device_id": DEVICE_ID,
                    "cpu_free": info["cpu_free"],
                    "ram_free_mb": info["ram_free_mb"],
                    "ram_used_percent": info["ram_used_percent"],
                    "total_ram_mb": info["total_ram_mb"],
                    "battery": info["battery"],
                    "storage": info["storage"],
                    "network": info["network"],
                    "device": info["device"]
                }
                await websocket.send(json.dumps(register_msg))
                print(f"[+] Worker {DEVICE_ID} registered with coordinator")
                print(f"    CPU: {info['cpu_free']}% free")
                print(f"    RAM: {info['ram_free_mb']}MB free ({info['ram_used_percent']}% used of {info['total_ram_mb']}MB total)")
                print(f"    Battery: {info['battery'].get('percentage', 'N/A')}% ({info['battery'].get('status', 'unknown')})")
                print(f"    Storage: {info['storage'].get('free_gb', 'N/A')}GB free")
                
                # Wait for registration acknowledgment
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    response_data = json.loads(response)
                    if response_data.get("type") == "registration_ack":
                        print(f"[+] Registration acknowledged by coordinator")
                except asyncio.TimeoutError:
                    print("[!] No registration acknowledgment received")
                
                # Reset reconnect delay
                reconnect_delay = 5
                
                # Main heartbeat loop
                heartbeat_count = 0
                while True:
                    try:
                        info = get_resource_info()
                        heartbeat_msg = {
                            "type": "heartbeat", 
                            "device_id": DEVICE_ID,
                            "cpu_free": info["cpu_free"],
                            "ram_free_mb": info["ram_free_mb"],
                            "ram_used_percent": info["ram_used_percent"],
                            "total_ram_mb": info["total_ram_mb"],
                            "battery": info["battery"],
                            "storage": info["storage"],
                            "network": info["network"],
                            "device": info["device"]
                        }
                        await websocket.send(json.dumps(heartbeat_msg))
                        heartbeat_count += 1
                        
                        # Log heartbeat locally every 5th time
                        if heartbeat_count % 5 == 0:
                            print(f"[♥] Heartbeat #{heartbeat_count}: "
                                  f"CPU: {info['cpu_free']}% free, "
                                  f"RAM: {info['ram_free_mb']}MB free")
                        
                        # Wait for acknowledgment
                        try:
                            response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                            response_data = json.loads(response)
                            if response_data.get("type") == "heartbeat_ack":
                                pass
                        except asyncio.TimeoutError:
                            print("[!] No heartbeat acknowledgment received")
                            
                        await asyncio.sleep(5)
                            
                    except Exception as e:
                        print(f"[!] Error in heartbeat loop: {e}")
                        break
                        
        except Exception as e:
            print(f"[!] Connection failed: {e}")
            print(f"[+] Retrying in {reconnect_delay}s...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 1.5, max_reconnect_delay)

def main():
    """Main entry point"""
    print(f"[+] Starting mobile worker with ID: {DEVICE_ID}")
    print(f"[+] Coordinator URI: {COORDINATOR_URI}")
    
    # Test resource functions first
    print("\n[+] Testing resource monitoring functions:")
    info = get_resource_info()
    print(f"    CPU Free: {info['cpu_free']}%")
    print(f"    RAM Free: {info['ram_free_mb']}MB ({info['ram_used_percent']}% used of {info['total_ram_mb']}MB total)")
    print(f"    Battery: {info['battery'].get('percentage', 'N/A')}% ({info['battery'].get('status', 'unknown')})")
    print(f"    Storage: {info['storage'].get('free_gb', 'N/A')}GB free")
    print(f"    Network: {'Connected' if info['network'].get('connected') else 'Disconnected'}")
    
    try:
        asyncio.run(worker_loop())
    except KeyboardInterrupt:
        print("\n[+] Worker stopped by user")
    except Exception as e:
        print(f"[!] Fatal error: {e}")

if __name__ == "__main__":
    main()
