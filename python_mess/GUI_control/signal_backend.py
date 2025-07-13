# ─── signal_backend.py ────────────────────────────────────────────────
"""
High-Performance Signal Processing Backend for DIY EEG Board

This module handles high-speed UDP data reception from the EEG board:
- Receives 24-bit samples from 16 channels at up to 4000 Hz
- Optimized circular buffer management
- Zero-copy parsing where possible
- Multiprocess architecture for CPU isolation
"""

from __future__ import annotations
import multiprocessing as mp
import socket
import struct
import time
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any
import numpy as np


# ────────────────────── Configuration ──────────────────────────

@dataclass
class SigConfig:
    """
    Signal acquisition configuration.
    
    Attributes:
        sample_rate: Samples per second per channel (Hz)
        buf_secs: Buffer duration in seconds
        n_ch: Number of channels (fixed at 16 for ADS1299)
    """
    sample_rate: int = 250
    buf_secs: int = 4
    n_ch: int = 16
    
    def __post_init__(self):
        """Ensure all values are integers."""
        self.sample_rate = int(self.sample_rate)
        self.buf_secs = int(self.buf_secs)
        self.n_ch = int(self.n_ch)
    
    @property
    def buf_len(self) -> int:
        """Total samples per channel in the circular buffer."""
        return self.sample_rate * self.buf_secs


# ────────────────────── 24-bit Parser ──────────────────────────

# Pre-computed byte indices for each channel's 24-bit value
# Channel 0: bytes 0,1,2  Channel 1: bytes 3,4,5  etc.
IDX_HIGH = np.array([0,3,6,9,12,15,18,21,24,27,30,33,36,39,42,45], dtype=np.uint8)
IDX_MID = IDX_HIGH + 1
IDX_LOW = IDX_HIGH + 2

# Lookup table for fast 24-bit to 32-bit sign extension
# When MSB (bit 23) is set, we need to extend the sign to bits 24-31
SIGN_EXTEND_LUT = np.zeros(256, dtype=np.int32)
for i in range(128, 256):  # Bytes with bit 7 set (negative in 2's complement)
    SIGN_EXTEND_LUT[i] = -(1 << 24)  # Subtract 2^24 for sign extension


def parse_frame(raw: bytes) -> np.ndarray:
    """
    Parse 48-byte frame containing 16 channels of 24-bit samples.
    
    Args:
        raw: 48 bytes (16 channels × 3 bytes/channel)
        
    Returns:
        Array of 16 signed 32-bit integers
        
    Raises:
        ValueError: If input is not exactly 48 bytes
        
    Note:
        Optimized using vectorized operations - ~3-5x faster than loop
    """
    if len(raw) != 48:
        raise ValueError(f"parse_frame() needs 48 B, got {len(raw)} B")
    
    # View bytes as uint8 array without copying
    raw_arr = np.frombuffer(raw, dtype=np.uint8)
    
    # Extract all channels at once using pre-computed indices
    high = raw_arr[IDX_HIGH].astype(np.int32) << 16  # MSB shifted to bits 16-23
    mid  = raw_arr[IDX_MID].astype(np.int32) << 8    # Middle byte to bits 8-15
    low  = raw_arr[IDX_LOW].astype(np.int32)         # LSB in bits 0-7
    
    # Combine three bytes into 24-bit values
    val = high | mid | low
    
    # Fast sign extension from 24-bit to 32-bit using lookup table
    # If bit 23 is set (negative), we need to set bits 24-31 to 1
    sign_bits = raw_arr[IDX_HIGH]  # MSB of each channel
    val += SIGN_EXTEND_LUT[sign_bits]
    
    return val


# ── ADS1299 Scaling Factor ────────────────────────────────────
# Full scale range: ±4.5V, 24-bit signed ADC
# LSB = 4.5V / 2^23 = 0.536 µV
SCALE = 4.5 / (2**23)


# ────────────────────── UDP Reader Process ─────────────────────

class _Reader(mp.Process):
    """
    Background process for high-speed UDP data reception.
    
    Features:
    - Circular buffer with zero-copy updates
    - Batch processing of multiple packets
    - Dynamic buffer resizing
    - Performance statistics
    """
    
    # Protocol constants
    FRAMESIZE = 52          # 48 bytes data + 4 bytes timestamp
    MAX_PACKET = 4096       # Maximum UDP packet size
    MAX_PACKETS_PER_CYCLE = 10  # Process up to 10 packets at once
    RESIZE_CHECK_INTERVAL = 100  # Check buffer resize every N frames
    SOCKET_TIMEOUT = 0.010  # 10ms blocking timeout
    STATS_INTERVAL = 1.0    # Print performance stats every second
    
    def __init__(self, cfg_ns, shared, lock, port, ip="0.0.0.0"):
        """
        Initialize reader process.
        
        Args:
            cfg_ns: Multiprocessing namespace with configuration
            shared: Shared dictionary for data exchange
            lock: Lock for shared memory access
            port: UDP port to listen on (default 5001)
            ip: IP to bind to (0.0.0.0 = all interfaces)
        """
        super().__init__(daemon=True, name="SignalReader")
        self.cfg = cfg_ns
        self.shared = shared
        self.lock = lock
        self.port = port
        self.ip = ip
        
    def run(self):
        """Main process loop - receives and processes UDP packets."""
        # Create UDP socket with timeout (blocking but not infinite)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((self.ip, self.port))
        sock.settimeout(self.SOCKET_TIMEOUT)
        
        # Pre-allocate receive buffer to avoid allocations
        recv_buf = bytearray(self.MAX_PACKET)
        
        # Initialize circular buffers
        current_buf_len = self.cfg.buf_len
        buf_raw = np.zeros((current_buf_len, self.cfg.n_ch), np.int32)
        buf_time = np.zeros(current_buf_len, np.uint32)
        
        # Circular buffer write pointer (next write position)
        ptr = 0
        
        # Cache frequently accessed values
        n_ch = self.cfg.n_ch
        pause_reception = False
        
        # Performance monitoring
        last_stat_time = time.perf_counter()
        packets_processed = 0
        frames_processed = 0
        enable_stats = True  # Set False to disable performance printing
        
        # Main processing loop
        while True:
            # ─────── Periodic Tasks (every N frames) ───────
            if frames_processed % self.RESIZE_CHECK_INTERVAL == 0:
                # Check if buffer needs resizing
                expected_buf_len = self.cfg.sample_rate * self.cfg.buf_secs
                if expected_buf_len != current_buf_len:
                    # Buffer size changed - resize
                    print(f"[SIGNAL_BACKEND] Buffer resize: {current_buf_len} -> {expected_buf_len}")
                    
                    # Create new buffers
                    new_buf_raw = np.zeros((expected_buf_len, n_ch), np.int32)
                    new_buf_time = np.zeros(expected_buf_len, np.uint32)
                    
                    # Preserve existing data if any
                    if ptr > 0:
                        # Reorder old buffer to linear time (oldest first)
                        old_ordered = np.concatenate([buf_raw[ptr:], buf_raw[:ptr]], axis=0)
                        old_time_ordered = np.concatenate([buf_time[ptr:], buf_time[:ptr]])
                        
                        copy_len = min(current_buf_len, expected_buf_len)
                        if current_buf_len > expected_buf_len:
                            # Buffer shrinking: keep most recent data
                            new_buf_raw[:] = old_ordered[-copy_len:]
                            new_buf_time[:] = old_time_ordered[-copy_len:]
                        else:
                            # Buffer growing: put old data at end
                            new_buf_raw[-copy_len:] = old_ordered
                            new_buf_time[-copy_len:] = old_time_ordered
                    
                    # Switch to new buffers
                    buf_raw = new_buf_raw
                    buf_time = new_buf_time
                    current_buf_len = expected_buf_len
                    ptr = 0  # Reset pointer after resize
                
                # Cache pause flag to avoid attribute lookup in hot path
                pause_reception = getattr(self.cfg, 'pause_reception', False)
            
            # ─────── Handle Pause State ───────
            if pause_reception:
                time.sleep(0.010)  # Sleep longer when paused
                continue
            
            # ─────── Receive & Process Packets ───────
            packets_this_cycle = 0
            frames_this_cycle = 0
            
            # Process multiple packets per cycle for efficiency
            while packets_this_cycle < self.MAX_PACKETS_PER_CYCLE:
                try:
                    # Receive directly into pre-allocated buffer (zero-copy)
                    nbytes = sock.recv_into(recv_buf)
                    
                    # Validate packet size
                    if nbytes < self.FRAMESIZE:
                        continue  # Too small, skip
                    
                    packets_this_cycle += 1
                    
                    # Calculate number of complete frames in packet
                    # Packet format: [Frame1][Frame2]...[FrameN][BatteryFloat]
                    frames = (nbytes - 4) // self.FRAMESIZE
                    frames_this_cycle += frames
                    
                    # Extract battery voltage (last 4 bytes of packet)
                    batt = struct.unpack_from('<f', recv_buf, frames * self.FRAMESIZE)[0]
                    
                    # Process each frame in the packet
                    for n in range(frames):
                        base = n * self.FRAMESIZE
                        
                        # Parse 24-bit samples and timestamp
                        buf_raw[ptr] = parse_frame(recv_buf[base:base + 48])
                        # Timestamp is in units of 8 microseconds (hardware specific)
                        buf_time[ptr] = struct.unpack_from('<I', recv_buf, base + 48)[0]
                        
                        # Advance circular buffer pointer
                        ptr = (ptr + 1) % current_buf_len
                        
                except socket.timeout:
                    # Normal - no more packets available
                    break
                except socket.error as e:
                    # Network error - log and continue
                    if enable_stats:
                        print(f"[SIGNAL_BACKEND] Socket error: {e}")
                    break
                except Exception as e:
                    # Unexpected error - log and continue
                    if enable_stats:
                        print(f"[SIGNAL_BACKEND] Unexpected error: {e}")
                    break
            
            # ─────── Update Shared Memory ───────
            if frames_this_cycle > 0:
                with self.lock:
                    # Convert to linear time order for GUI
                    # Circular buffer: [newest...ptr...oldest]
                    # Linear order: [oldest...newest]
                    if ptr == 0:
                        # Buffer full and pointer wrapped - already in order
                        self.shared["data"] = (buf_raw * SCALE).copy()
                        self.shared["time"] = buf_time.copy()
                    else:
                        # Reorder: [ptr:end] + [0:ptr]
                        ordered_raw = np.concatenate([buf_raw[ptr:], buf_raw[:ptr]], axis=0)
                        ordered_time = np.concatenate([buf_time[ptr:], buf_time[:ptr]])
                        self.shared["data"] = ordered_raw * SCALE
                        self.shared["time"] = ordered_time
                    
                    self.shared["batt_v"] = batt
                
                # Update statistics
                packets_processed += packets_this_cycle
                frames_processed += frames_this_cycle
            
            # ─────── Performance Monitoring ───────
            if enable_stats:
                now = time.perf_counter()
                if now - last_stat_time > self.STATS_INTERVAL:
                    elapsed = now - last_stat_time
                    pps = packets_processed / elapsed
                    fps = frames_processed / elapsed
                    print(f"[PERF] {pps:.1f} pkt/s, {fps:.1f} frm/s")
                    last_stat_time = now
                    packets_processed = 0
                    frames_processed = 0


# ────────────────────── Public API ─────────────────────────────

class SignalWorker:
    """
    High-level interface for signal acquisition.
    
    Manages a background process that receives UDP data and provides
    thread-safe access to the latest samples.
    
    Example:
        cfg = SigConfig(sample_rate=500, buf_secs=10)
        worker = SignalWorker(cfg, data_port=5001)
        worker.start()
        
        # Get latest data
        snapshot = worker.snapshot()
        if snapshot:
            data = snapshot['data']    # (samples, 16) float array in volts
            time = snapshot['time']    # Sample timestamps
            batt = snapshot['batt_v']  # Battery voltage
    """
    
    def __init__(self, cfg: SigConfig, data_port: int = 5001):
        """
        Initialize signal worker.
        
        Args:
            cfg: Signal configuration
            data_port: UDP port for data reception (default 5001)
        """
        # Multiprocessing setup
        self._mgr = mp.Manager()
        self._shared = self._mgr.dict()
        self._lock = mp.Lock()
        
        # Configuration in shared namespace
        self.cfg = self._mgr.Namespace(**asdict(cfg))
        self.cfg.buf_len = cfg.buf_len
        self.cfg.pause_reception = False
        
        # Create reader process
        self._proc = _Reader(self.cfg, self._shared, self._lock, data_port)
        
    def start(self):
        """Start the background reader process."""
        if not self._proc.is_alive():
            self._proc.start()
            print(f"[SIGNAL_BACKEND] Started reader process (PID: {self._proc.pid})")
            
    def stop(self):
        """Stop the background reader process."""
        if self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(timeout=1.0)
            if self._proc.is_alive():
                print("[SIGNAL_BACKEND] Warning: Reader process didn't stop cleanly")
            else:
                print("[SIGNAL_BACKEND] Reader process stopped")
            
    def snapshot(self) -> Optional[Dict[str, Any]]:
        """
        Get a snapshot of the latest data.
        
        Returns:
            Dictionary with keys:
            - 'data': (samples, 16) array of voltages
            - 'time': (samples,) array of timestamps
            - 'batt_v': Battery voltage
            
            Returns None if no data available yet.
        """
        with self._lock:
            if "data" not in self._shared:
                return None
            # Return copies to prevent modification
            return {k: v.copy() if hasattr(v, "copy") else v
                    for k, v in self._shared.items()}
                    
    def update_cfg(self, **kwargs):
        """
        Update configuration parameters.
        
        Args:
            sample_rate: New sample rate (Hz)
            buf_secs: New buffer duration (seconds)
            
        The buffer will be resized on the next processing cycle.
        """
        for k, v in kwargs.items():
            setattr(self.cfg, k, v)
        
        # Update derived property
        if 'sample_rate' in kwargs or 'buf_secs' in kwargs:
            self.cfg.buf_len = self.cfg.sample_rate * self.cfg.buf_secs
            print(f"[SIGNAL_BACKEND] Config updated: {self.cfg.sample_rate}Hz, "
                  f"{self.cfg.buf_secs}s buffer ({self.cfg.buf_len} samples)")
            
    @property
    def pause_reception(self) -> bool:
        """Check if reception is paused."""
        return getattr(self.cfg, 'pause_reception', False)
        
    @pause_reception.setter
    def pause_reception(self, value: bool):
        """Pause or resume data reception."""
        self.cfg.pause_reception = value
        state = "paused" if value else "resumed"
        print(f"[SIGNAL_BACKEND] Reception {state}")
        
# ──────────────────────────────────────────────────────────────────────