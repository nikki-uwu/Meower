# ─── signal_backend.py ────────────────────────────────────────────────────
"""
Real-time UDP data acquisition & signal-processing backend
==========================================================

• Only *network I/O + maths* live here – no plots, no Tk widgets.
• GUI drives it through the public API:
      >>> from signal_backend import SignalWorker, SigConfig
      >>> cfg  = SigConfig(sample_rate=500, n_ch=16)
      >>> proc = SignalWorker(cfg, data_port=5001)
      >>> proc.start()
      ...                                # later in the GUI's timer:
      >>> latest = proc.snapshot()       # numpy-dict with fresh results
• All tunables (FFT size, window overlap, filter enables …) are *mutable*
  attributes of `SigConfig` – the GUI can edit them live.

Any heavy processing still happens in a *separate process* so the GUI stays
buttery-smooth even with large FFT / wavelet loads.

Author: ChatGPT 2025-07
"""

from __future__ import annotations
import multiprocessing as mp, threading, socket, struct, time
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
import numpy as np
import scipy.signal as sps

# ── ———————————————————————————————————— Configuration ———————————— ── #

@dataclass
class SigConfig:
    
    def __init__(self, sample_rate, buf_secs, n_ch):
        self.sample_rate = int(sample_rate)
        self.buf_secs   = int(buf_secs)
        self.n_ch       = int(n_ch)
        
    """All user-tweakable DSP / UI parameters live here."""
    # Acquisition
    sample_rate : int   = 500
    n_ch        : int   = 16
    buf_secs    : int   = 8            # rolling window length in seconds

    # Notch filters
    notch_50_on     : bool = False
    notch_100_on    : bool = False
    dc_block_on     : bool = False
    eq_on           : bool = False

    # Spectro/FFT
    fft_pts     : int   = 512          # Nfft (must be power-of-two preferred)
    win_pts     : int   = 128          # window length for STFT / FFT
    win_overlap : int   = 50           # % overlap

    # Wavelet scalogram
    wav_n_freqs : int   = 128
    wav_overlap : int   = 95           # %

    # Misc
    cheb_atten_db   : float = 100.0    # Chebyshev window attenuation
    digital_gain    : int   = 1
    network_freq    : int   = 50       # 50 or 60 Hz
    dc_cut_hz       : float = 0.5

    # ---------- convenience --------------------------------------------
    @property
    def buf_len(self) -> int:          # total samples per channel kept
        return self.sample_rate * self.buf_secs

# ── ———————————————————————————— Helper DSP primitives ———————————— ── #

IDX_ADC_SAMPLES = (3 * np.arange(16)).astype(np.int32)

def parse_frame(raw: bytes) -> np.ndarray:
    """Convert one *48-byte* ADS1299 frame → int32[16] signed values."""
    if len(raw) != 48:
        raise ValueError(f"Need 48 B, got {len(raw)} B")
    b = np.frombuffer(raw, np.uint8).astype(np.int32)
    val24 = (
        (b[IDX_ADC_SAMPLES    ] << 16) |
        (b[IDX_ADC_SAMPLES + 1] <<  8) |
         b[IDX_ADC_SAMPLES + 2]
    )
    neg = val24 & 0x800000
    val24[neg != 0] -= 1 << 24
    return val24

def design_notch(freq: float, fs: float, Q: float = 1.5):
    return sps.iirnotch(freq, Q, fs)

def _prepare_filters(cfg: SigConfig):
    """Return cascaded IIR for 50+100 Hz comb if requested."""
    b, a = [np.array([1.]), np.array([1.])]
    if cfg.notch_50_on:
        b50, a50 = design_notch(50, cfg.sample_rate)
        b, a = np.convolve(b, b50), np.convolve(a, a50)
    if cfg.notch_100_on:
        b100, a100 = design_notch(100, cfg.sample_rate)
        b, a = np.convolve(b, b100), np.convolve(a, a100)
    return b, a

# ── —————————————————————————————— Worker process ——————————————— ── #

class _Reader(mp.Process):
    """
    Sits in a *process*:
      • receives UDP packets (data_port)
      • maintains rolling numpy buffers
      • applies filters, FFT, CWT … according to shared SigConfig
      • pushes latest results into a *mp.Manager().dict()* for zero-copy reads
    """
    FRAMESIZE = 52                              # 48 B ADC + 4 B TS

    def __init__(self,
                 cfg_proxy,
                 shared_dict, lock: mp.Lock,
                 data_port: int,
                 ip: str = "0.0.0.0"):
        super().__init__(daemon=True)
        self.cfg     = cfg_proxy           # *proxy* to live-mutating SigConfig
        self.out     = shared_dict
        self.lock    = lock
        self.ip      = ip
        self.port    = data_port

    # ---------------------------- main loop ----------------------------
    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.ip, self.port))
        sock.setblocking(False)
        buf_raw  = np.zeros((self.cfg.buf_len, self.cfg.n_ch), np.int32)
        buf_time = np.zeros(self.cfg.buf_len,                 np.uint32)
        scale    = 4.5 / (1 << 23)            # 24-bit ADS1299 → volts
        b_notch, a_notch = design_notch(50, 500)  # dummy init

        while True:
            try:
                pkt, _ = sock.recvfrom(4096)
            except BlockingIOError:
                time.sleep(0.0005)
                continue
            if len(pkt) < self.FRAMESIZE:      # bogus
                continue
            frames = (len(pkt) - 4) // self.FRAMESIZE
            batt   = struct.unpack_from("<f", pkt, frames*self.FRAMESIZE)[0]

            # (re)-calc filters if user toggled something ---------------
            cfg = self.cfg
            b_notch, a_notch = _prepare_filters(cfg)

            for n in range(frames):
                base = n * self.FRAMESIZE
                samples = parse_frame(pkt[base:base+48])
                ts      = struct.unpack_from('<I', pkt, base+48)[0]
                buf_raw  = np.roll(buf_raw,  -1, axis=0);  buf_raw[-1]  = samples
                buf_time = np.roll(buf_time, -1);          buf_time[-1] = ts

            # ----------- fast vectorised processing -------------------
            vs = buf_raw.astype(np.float32) * scale * cfg.digital_gain
            if cfg.notch_50_on or cfg.notch_100_on:
                vs = sps.filtfilt(b_notch, a_notch, vs, axis=0)

            # only *latest* snapshot is needed for GUI  ----------------
            with self.lock:
                self.out["time"]   = buf_time.copy()
                self.out["data"]   = vs.copy()
                self.out["batt_v"] = batt
                # Placeholders that the GUI/plotter will compute itself
                # (FFT/specgram/wavelet are heavy; do them on demand)
        # never returns

# ── —————————————————————————————— Public facade ———————————————— ── #

class SignalWorker:
    """
    Thin wrapper that the GUI can own:

        cfg  = SigConfig()
        proc = SignalWorker(cfg, data_port=5001)
        proc.start()

        ... in GUI timer ...
        snap = proc.snapshot()
        if snap:  do_something(snap["data"])
    """
    def __init__(self, cfg: SigConfig, data_port: int = 5001):
        self._manager = mp.Manager()
        self._shared  = self._manager.dict()    # will hold {"data": …}
        self._lock    = mp.Lock()
        self.cfg      = self._manager.Namespace(**asdict(cfg))
        self.cfg.buf_len = cfg.buf_len 
        self._proc    = _Reader(self.cfg, self._shared, self._lock, data_port)

    def start(self):
        if not self._proc.is_alive():
            self._proc.start()

    def stop(self):
        if self._proc.is_alive():
            self._proc.terminate()
            self._proc.join()

    # ------------ GUI helper ------------------------------------------
    def snapshot(self) -> Optional[Dict[str, Any]]:
        """Return a *copy* of the latest buffers – or None if not yet filled."""
        with self._lock:
            if "data" not in self._shared:
                return None
            return {k: v.copy() if hasattr(v, 'copy') else v
                    for k, v in self._shared.items()}

    # ------------ live parameter update -------------------------------
    def update_cfg(self, **kwargs):
        """GUI can live-patch any SigConfig field."""
        for k, v in kwargs.items():
            setattr(self.cfg, k, v)
# ─────────────────────────────────────────────────────────────────────────
