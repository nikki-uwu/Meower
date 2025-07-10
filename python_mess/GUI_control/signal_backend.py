# ─── signal_backend.py ────────────────────────────────────────────────
from __future__ import annotations
import multiprocessing as mp, socket, struct, time
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
import numpy as np

# ── configuration ────────────────────────────────────────────────────
@dataclass
class SigConfig:
    sample_rate: int = 250
    buf_secs   : int = 4
    n_ch       : int = 16
    def __post_init__(self):
        self.sample_rate = int(self.sample_rate)
        self.buf_secs    = int(self.buf_secs)
        self.n_ch        = int(self.n_ch)
    @property
    def buf_len(self) -> int:          # samples per channel in ring-buffer
        return self.sample_rate * self.buf_secs

# ── 24-bit ADS1299 frame parser (one-to-one with your script) ────────
IDX_ADC_SAMPLES = (3 * np.arange(16)).astype(np.int32)
def parse_frame(raw: bytes) -> np.ndarray:
    if len(raw) != 48:
        raise ValueError(f"parse_frame() needs 48 B, got {len(raw)} B")
    raw_arr = np.frombuffer(raw, np.uint8).astype(np.int32)
    high = (raw_arr[IDX_ADC_SAMPLES    ] << 16)
    mid  = (raw_arr[IDX_ADC_SAMPLES + 1] <<  8)
    low  =  raw_arr[IDX_ADC_SAMPLES + 2]
    val  = (high | mid | low).astype(np.int32)
    neg  = (val & 0x800000) != 0
    val[neg] -= 1 << 24                 # sign-extend 24→32 bit
    return val

# ── single scaling factor: ±4.5 V full-scale ─────────────────────────
SCALE = 4.5 / (1 << 23)                # 0.536 µV / LSB

# ── background UDP reader process ────────────────────────────────────
class _Reader(mp.Process):
    FRAMESIZE = 52                      # 48 B samples + 4 B timestamp
    def __init__(self, cfg_ns, shared, lock, port, ip="0.0.0.0"):
        super().__init__(daemon=True)
        self.cfg, self.shared, self.lock = cfg_ns, shared, lock
        self.port, self.ip = port, ip
    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.ip, self.port))
        sock.setblocking(False)
        buf_raw  = np.zeros((self.cfg.buf_len, self.cfg.n_ch), np.int32)
        buf_time = np.zeros(self.cfg.buf_len,                 np.uint32)
        while True:
            try:
                pkt, _ = sock.recvfrom(4096)
            except BlockingIOError:
                time.sleep(0.0005); continue
            if len(pkt) < self.FRAMESIZE:
                continue
            frames = (len(pkt) - 4) // self.FRAMESIZE
            batt   = struct.unpack_from("<f", pkt, frames * self.FRAMESIZE)[0]
            for n in range(frames):
                base = n * self.FRAMESIZE
                buf_raw  = np.roll(buf_raw,  -1, axis=0)
                buf_time = np.roll(buf_time, -1)
                buf_raw [-1] = parse_frame(pkt[base : base + 48])
                buf_time[-1] = struct.unpack_from("<I", pkt, base + 48)[0]
            with self.lock:
                self.shared["data"]   = buf_raw.astype(np.float32) * SCALE
                self.shared["time"]   = buf_time.copy()
                self.shared["batt_v"] = batt

# ── facade for GUI ───────────────────────────────────────────────────
class SignalWorker:
    def __init__(self, cfg: SigConfig, data_port: int = 5001):
        self._mgr    = mp.Manager()
        self._shared = self._mgr.dict()
        self._lock   = mp.Lock()
        self.cfg     = self._mgr.Namespace(**asdict(cfg))
        self.cfg.buf_len = cfg.buf_len
        self._proc   = _Reader(self.cfg, self._shared, self._lock, data_port)
    def start(self):
        if not self._proc.is_alive():
            self._proc.start()
    def stop(self):
        if self._proc.is_alive():
            self._proc.terminate(); self._proc.join()
    def snapshot(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if "data" not in self._shared:
                return None
            return {k: v.copy() if hasattr(v, "copy") else v
                    for k, v in self._shared.items()}
    def update_cfg(self, **kw):
        for k, v in kw.items():
            setattr(self.cfg, k, v)
# ──────────────────────────────────────────────────────────────────────
