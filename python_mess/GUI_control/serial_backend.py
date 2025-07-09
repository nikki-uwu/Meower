# ─── serial_backend.py ───────────────────────────────────────────
import threading, queue, time
try:
    import serial, serial.tools.list_ports
except ImportError:
    serial = None                        # demo-mode fallback


class SerialManager:
    RETRY = 0.2                          # seconds between connect attempts

    def __init__(self):
        self.rx_q, self.tx_q = queue.Queue(), queue.Queue()
        self.ack_q = queue.Queue() 
        self._stop_evt  = threading.Event()
        self._thread    = None

    # ── public api ───────────────────────────────────────────
    def start(self, port: str, baud: int):
        self.stop()
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._loop, args=(port, baud), daemon=False)
        self._thread.start()

    def stop(self):
        if self._thread and self._thread.is_alive():
            self._stop_evt.set()
            self._thread.join(timeout=1)

    def send(self, text: str):
        """Echo locally and queue one TX line (adds newline)."""
        line = text.rstrip()
        self.rx_q.put(f">>> {line}\n")        # console echo
        self.tx_q.put(line + "\n")
        
    def send_and_wait(self, text: str, timeout: float = 1.0):
        """Send one command and wait for the board’s OK / ERR reply.
           If nothing arrives within *timeout* seconds, log a warning."""
        # flush stale acknowledgements
        while not self.ack_q.empty():
            try:
                self.ack_q.get_nowait()
            except queue.Empty:
                break

        self.send(text)                        # enqueue TX

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                line = self.ack_q.get(timeout=deadline - time.time())
                if line.lstrip().startswith(("OK", "ERR")):
                    return                     # got the ack
            except queue.Empty:
                pass

        # timeout
        self.rx_q.put(f"[PC] ✖ No response for: {text.strip()}\n")


    # ── NEW: batch helper ──────────────────────────────────
    def send_many(self, lines, delay=0.10):
        """
        Queue several commands in sequence.
        delay – pause (s) between lines so the device can answer.
        """
        for ln in lines:
            self.send(ln)
            time.sleep(delay)

    @staticmethod
    def ports():
        return [p.device for p in serial.tools.list_ports.comports()] if serial else []

    # ── internal loop ───────────────────────────────────────
    def _loop(self, port, baud):
        ser = None
        while not self._stop_evt.is_set():
            if ser is None or not ser.is_open:
                if port not in self.ports():
                    time.sleep(self.RETRY); continue
                try:
                    ser = serial.Serial(port, baud, timeout=0.1)
                    self.rx_q.put(f"[PC] >>> CONNECTED {port}\n")
                except Exception as e:
                    self.rx_q.put(f"[PC] open() failed: {e}\n")
                    time.sleep(self.RETRY); continue

            try:
                if ser.in_waiting:
                    line = ser.readline().decode(errors="replace")
                    self.rx_q.put(line)  
                    self.ack_q.put(line)         # <-- NEW  (goes to waiter)
                try:
                    ser.write(self.tx_q.get_nowait().encode())
                except queue.Empty:
                    pass
            except Exception as e:
                self.rx_q.put(f"[PC] <<< DISCONNECTED ({e})\n")
                try: ser.close()
                except Exception: pass
                ser = None
                time.sleep(self.RETRY)

        if ser and ser.is_open:
            try: ser.close()
            except Exception: pass
        self.rx_q.put("[PC] Worker stopped\n")
