Import("env")
import os
import serial.tools.list_ports

def detect_com_port():
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        desc = p.description.lower()
        if "silicon" in desc or "usb" in desc or "esp" in desc:
            return p.device
    return None

def erase_flash():
    port = detect_com_port()
    if not port:
        print("[SCRIPT] ERROR: Could not detect COM port. Is your ESP32 connected?")
        return 1

    python = env.subst("$PYTHONEXE")
    esptool = os.path.join(env.subst("$PROJECT_PACKAGES_DIR"), "tool-esptoolpy", "esptool.py")
    cmd = f'"{python}" "{esptool}" --chip esp32c3 --port {port} --baud 115200 erase_flash'
    
    print(f"[SCRIPT] Erasing flash on {port}...")
    return env.Execute(cmd)

erase_flash()
