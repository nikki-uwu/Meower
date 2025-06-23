import serial, serial.tools.list_ports
import time, sys

PORT          = "COM27"      # ← adjust if needed
BAUDRATE      = 115200
RETRY_DELAY_S = 0.20         # delay between open attempts (seconds)

def port_available(name: str) -> bool:
    """True if <name> is present in the current COM list."""
    return any(p.device == name for p in serial.tools.list_ports.comports())

print(f"[PC] Watching for {PORT} @ {BAUDRATE} baud – Ctrl-C to quit")
ser = None

try:
    while True:
        # ----------  connect (or re-connect) ----------
        if ser is None or not ser.is_open:
            if not port_available(PORT):
                time.sleep(RETRY_DELAY_S)        # port not present → wait / poll
                continue
            try:
                ser = serial.Serial(PORT, BAUDRATE, timeout=0.1)
                print(f"[PC] >>> CONNECTED to {PORT}")
            except serial.SerialException as e:
                print(f"[PC] open() failed: {e}")
                ser = None
                time.sleep(RETRY_DELAY_S)
                continue                          # retry

        # ----------  read ----------
        try:
            data = ser.readline()                 # up to '\n' or timeout
            if data:
                try:
                    print(data.decode('utf-8', errors='replace'), end='')
                except UnicodeDecodeError:        # non-text bytes
                    print(data)
        except (serial.SerialException, OSError, AttributeError) as e:
            print(f"\n[PC] <<< DISCONNECTED ({e})")
            try:
                ser.close()
            except Exception:
                pass
            ser = None                            # back to “search” state
            time.sleep(RETRY_DELAY_S)

except KeyboardInterrupt:
    print("\n[PC] stopped by user")
finally:
    if ser and ser.is_open:
        ser.close()