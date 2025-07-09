# ─── udp_backend.py ───────────────────────────────────────────
import socket, threading, queue, time

class UDPManager:
    """
    • Listens on the local **control-port** you already entered in the GUI
      and waits for the board’s beacon (first packet) to learn its IP.
    • Once locked, every second it sends the keep-alive string “floof”.
    • Non-blocking: all RX lines go to .rx_q (for the GUI), use .send(…)
      to transmit arbitrary control commands yourself.
    """
    FLOOF_INTERVAL = 5.0          # seconds
    TIMEOUT        = 0.2          # socket timeout

    def __init__(self, ctrl_port: int):
        self.ctrl_port   = ctrl_port
        self.board_ip    = None           # learned from beacon
        self.rx_q, self.tx_q = queue.Queue(), queue.Queue()
        self.tx_hook     = None            # ← callback set by the GUI
        self._stop_evt   = threading.Event()
        self._thread     = None

    # ── public api ───────────────────────────────────────────
    def start(self):
        if self._thread and self._thread.is_alive():
            return                          # already running
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_evt.set()

    def send(self, text: str):
        """Queue one control line for TX."""
        self.tx_q.put(text.rstrip().encode() + b"\n")

    # ── internal loop ───────────────────────────────────────
    def _loop(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", self.ctrl_port))
        s.settimeout(self.TIMEOUT)

        next_floof = time.time() + self.FLOOF_INTERVAL

        while not self._stop_evt.is_set():
            # 1) RX -------------------------------------------------------
            try:
                data, addr = s.recvfrom(512)     # non-blocking
                line = data.decode(errors="replace")
                self.rx_q.put(f"[ESP] {line}\n")  # single tagged copy
                if self.board_ip is None:        # first ever packet = beacon
                    self.board_ip = addr[0]
                    self.rx_q.put(f"[PC] ⇄ Board IP locked to {self.board_ip}\n")
            except socket.timeout:
                pass

            # 2) TX -------------------------------------------------------
            try:
                pkt = self.tx_q.get_nowait()
                if self.board_ip:
                    if self.tx_hook:
                        self.tx_hook(pkt.decode(errors="replace").rstrip())
                    s.sendto(pkt, (self.board_ip, self.ctrl_port))
            except queue.Empty:
                pass

            # 3) periodic floof ------------------------------------------
            if self.board_ip and time.time() >= next_floof:
                if self.tx_hook:
                    self.tx_hook("floof")
                s.sendto(b"floof", (self.board_ip, self.ctrl_port))
                next_floof = time.time() + self.FLOOF_INTERVAL

        s.close()
        self.rx_q.put("[PC] UDP worker stopped\n")
