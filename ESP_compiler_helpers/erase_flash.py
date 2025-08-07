# SPDX-License-Identifier: MIT OR Apache-2.0
# Copyright (c) 2025 Gleb Manokhin (nikki)
# Project: Meower

# ESP_compiler_helpers/erase_flash.py
Import("env")
import os

# Only run erase if we're uploading
import sys
is_upload = "upload" in "".join(sys.argv).lower()

if is_upload:
    def erase_flash_before_upload(source, target, env):
        """
        Erase flash before upload. Since PlatformIO hasn't detected the port yet,
        we detect it ourselves using the same logic PlatformIO uses.
        """
        print("[ERASE] ====================================")
        print("[ERASE] Starting flash erase before upload...")
        
        # Try to get explicitly set port first
        port = env.GetProjectOption("upload_port", None)
        
        if not port:
            # Do the same auto-detection PlatformIO does
            import serial.tools.list_ports
            ports = list(serial.tools.list_ports.comports())
            
            # PlatformIO picks the first USB serial port - same logic it uses internally
            for p in ports:
                # Check for common USB serial chips (same checks PlatformIO uses)
                desc = p.description or ""
                if any(x in desc.upper() for x in ["USB", "UART", "SERIAL", "CH340", "CP210", "FTDI", "SILICON"]):
                    port = p.device
                    print(f"[ERASE] Auto-detected port: {port}")
                    break
        
        if not port:
            print("[ERASE] ERROR: No USB serial port detected")
            print("[ERASE] Check that ESP32 is connected")
            print("[ERASE] ====================================")
            return 0  # Don't block upload, let PlatformIO fail naturally
        
        # Build erase command
        python = env.subst("$PYTHONEXE")
        esptool = os.path.join(env.subst("$PROJECT_PACKAGES_DIR"), "tool-esptoolpy", "esptool.py")
        
        # Use 115200 for erase (more reliable than high speeds)
        cmd = f'"{python}" "{esptool}" --chip esp32c3 --port {port} --baud 115200 erase_flash'
        
        print(f"[ERASE] Erasing flash on port: {port}")
        result = env.Execute(cmd)
        
        if result == 0:
            print(f"[ERASE] ✓ Flash erased successfully on {port}")
        else:
            print(f"[ERASE] ✗ Flash erase FAILED on {port}")
        
        print("[ERASE] ====================================")
        return result
    
    # Register the action to run before upload
    env.AddPreAction("upload", erase_flash_before_upload)
    print("[ERASE] Flash erase registered - will erase before upload")
else:
    print("[ERASE] Build mode - flash erase skipped")