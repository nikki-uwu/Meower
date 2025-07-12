"""main_gui.py  ·  DIY EEG / BCI Board Control
Python 3.12  ·  Tkinter + Matplotlib  ·  No external deps beyond PySerial & MPL
Run:  python main_gui.py

Revision
--------
• **Instant feedback**: figure redraw is scheduled just **40 ms** after the
  *last* <Configure> event, which feels immediate when you release the
  window edge.
• Debounce handler is appended (add="+") so Matplotlib's own resize logic
  remains active; we only throttle the expensive draw call.
• **Fixed blitting**: Proper implementation with animated artists and single figure background
• **Fixed duration issue**: X-axis now uses expected duration, not snapshot size
"""

# ─────────────────────────── DEBUG SWITCH ─────────────────────────
# Set to 1 to enable debug messages, 0 to disable
DEBUG = 0
# ──────────────────────────────────────────────────────────────────

import sys
import queue
import threading
import time
import random
import socket
import numpy as np
import scipy.signal as sps

import tkinter as tk
from tkinter import ttk, scrolledtext
from serial_backend import SerialManager
from udp_backend import UDPManager
from signal_backend import SignalWorker, SigConfig

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Dark palette for Matplotlib & Tk
matplotlib.rcParams.update({
    "axes.facecolor": "#1E1E1E",
    "axes.edgecolor": "#D4D4D4",
    "axes.labelcolor": "#D4D4D4",
    "xtick.color": "#D4D4D4",
    "ytick.color": "#D4D4D4",
    "figure.facecolor": "#1E1E1E",
})


try:
    import serial, serial.tools.list_ports
except ImportError:
    serial = None  # demo‑mode fallback



class WiFiWorker(threading.Thread):
    def __init__(self, q, stop_evt):
        super().__init__(daemon=True); self.q, self.stop_evt = q, stop_evt
    def run(self):
        cnt = 0
        while not self.stop_evt.is_set():
            self.q.put(f"[Wi‑Fi DEMO] Tick {cnt}\n"); cnt += 1; time.sleep(2)

# ─────────────────────────── Main GUI ─────────────────────────
class App(tk.Tk):
    BG, FG = "#1E1E1E", "#D4D4D4"
    RESIZE_DELAY_MS = 1  # draw 40 ms after last Configure → instant feel

    def __init__(self):
        super().__init__()
        
        self.udp = None
        self.sig = None  # Initialize as None, create after GUI vars exist
        
        self.title("DIY EEG / BCI Board Control")
        self.geometry("1600x1000")      # ← initial size
        self.minsize(900, 600)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._apply_style()

        # debouncer handle
        self._resize_job = None

        # master grid 1×3 : 2:1:1
        self.rowconfigure(0, weight=1)
        for c, w in enumerate((2, 1, 1)):
            self.columnconfigure(c, weight=w, uniform="main")

        # queues & stop‑event
        self.stop_evt = threading.Event()
        self.wifi_q = queue.Queue()

        # Create serial manager early
        self.ser = SerialManager()

        # UI columns
        self._build_plot_column()
        self.ser_console  = self._build_io_block(1, "Serial control", self._serial_controls)
        self.wifi_console = self._build_io_block(2, "Wi‑Fi control",  self._wifi_controls)
        
        # ------- Signal backend (now safe because fs_var & dur_var exist) --------
        self.sig_cfg = SigConfig(sample_rate=self.fs_var.get(),
                                 buf_secs   =self.dur_var.get(),
                                 n_ch       =16)
        self.sig     = SignalWorker(self.sig_cfg,
                                    data_port=int(self.data_port_var.get()))
        self.sig.start()
        
        # ── console colour scheme ───────────────────────────────────────
        self.ser_console .configure(bg="#000000", fg="#00ff00", insertbackground="#00ff00")  # green on black
        self.wifi_console.configure(bg="#000000", fg="#ff8800", insertbackground="#ff8800")  # orange on black

        # timers
        self.after(16, self._animate_plots)   # ~60 fps demo wave
        self.after(50, self._poll_queues)
        


    # ── style ───────────────────────────────────────────────
    def _apply_style(self):
        s = ttk.Style(self); s.theme_use("clam")
        for elem in ("TFrame","TLabel","TLabelframe","TLabelframe.Label",
                     "TButton","TCombobox","TEntry"):
            s.configure(elem, background=self.BG, foreground=self.FG)
        s.configure("TScrollbar", background=self.BG)
        s.configure("TEntry",    fieldbackground=self.BG,
                                foreground=self.FG,
                                insertcolor=self.FG)
        s.configure("TCombobox", fieldbackground=self.BG,
                                foreground=self.FG)
        s.map      ("TCombobox", fieldbackground=[("readonly", self.BG)])
        s.map("TButton", background=[("!active", self.BG), ("active", "#3E3E3E")])
        self.configure(background=self.BG)
        
        # ── coloured toggle styles ────────────────────────────────
        s.configure("On.TButton",  background="#248f24", foreground="white")
        s.map      ("On.TButton",
                    background=[("active",  "#1f7a1f"), ("pressed", "#1b671b")])

        s.configure("Off.TButton", background="#555555", foreground="white")
        s.map      ("Off.TButton",
                    background=[("active", "#4a4a4a"), ("pressed", "#3f3f3f")])

    # ── plot column + signal-controls ───────────────────────────────────────
    # ── plot column + signal controls ───────────────────────────────────────────
    # ── plot column + signal controls ───────────────────────────────────────────
    def _build_plot_column(self):
        """
        Five stacked plots (Δt · time · wavelet · spectrogram · PSD) + controls.
        Backgrounds are cached for fast blitting.
        """
        col = tk.Frame(self, bg=self.BG)
        col.grid(row=0, column=0, sticky="nsew")
        col.rowconfigure(0, weight=1)
        col.rowconfigure(1, weight=0)
        col.columnconfigure(0, weight=1)

        fig = Figure(constrained_layout=True, dpi=100)
        g   = fig.add_gridspec(5, 1, height_ratios=[1, 1, 1, 1, 1])

        self.ax_dt   = fig.add_subplot(g[0])
        self.ax_time = fig.add_subplot(g[1])
        self.ax_wav  = fig.add_subplot(g[2])
        self.ax_sg   = fig.add_subplot(g[3])
        self.ax_psd  = fig.add_subplot(g[4])

        # aliases so the rest of the file keeps working verbatim
        self.ax_wavelet  = self.ax_wav
        self.ax_specgram = self.ax_sg

        self.ax_dt.set_ylabel("Δt [µs]"); self.ax_dt.grid(ls=":")
        self.ax_time.set_ylabel("V");     self.ax_time.grid(ls=":")
        self.ax_time.set_ylim(-0.5, 0.5)  # Set initial amplitude limits
        self.ax_wav.set_ylabel("f [Hz]")
        self.ax_sg .set_ylabel("f [Hz]")
        self.ax_psd.set_ylabel("dB"); self.ax_psd.set_xlabel("Hz"); self.ax_psd.grid(ls=":")
        self.ax_psd.set_ylim(-130, 0)  # Set initial PSD limits

        N0  = 100
        xs  = np.arange(N0)
        self.dt_line,    = self.ax_dt.plot(xs, np.zeros(N0), lw=.8)
        self.time_lines  = [self.ax_time.plot(xs, np.zeros(N0), lw=.8)[0]
                            for _ in range(16)]
        self.im_wavelet  = self.ax_wav.imshow(np.zeros((64, N0)), origin="lower",
                                              aspect="auto", extent=(0, N0, 1, 250),
                                              vmin=-60, vmax=0)
        self.im_specgram = self.ax_sg.imshow (np.zeros((64, N0)), origin="lower",
                                              aspect="auto", extent=(0, N0, 0, 250),
                                              vmin=-80, vmax=0)
        self.psd_lines = [self.ax_psd.plot([], [], lw=.8)[0] for _ in range(16)]
        self.psd_max   = [self.ax_psd.plot([], [], lw=.8, ls="--",
                             color=self.psd_lines[i].get_color())[0]
                          for i in range(16)]
        self.maxhold_data = [None]*16

        # MARK ALL DYNAMIC ARTISTS AS ANIMATED
        self.dt_line.set_animated(True)
        for line in self.time_lines:
            line.set_animated(True)
        self.im_wavelet.set_animated(True)
        self.im_specgram.set_animated(True)
        for line in (*self.psd_lines, *self.psd_max):
            line.set_animated(True)

        canvas = FigureCanvasTkAgg(fig, master=col)
        w = canvas.get_tk_widget()
        w.grid(row=0, column=0, sticky="nsew")
        w.configure(bg=self.BG, highlightthickness=0)
        w.bind("<Configure>", self._queue_redraw, add="+")
        self.fig, self.fig_canvas = fig, canvas

        # USE SINGLE FIGURE BACKGROUND BUFFER
        self._bg_cache = None
        def _save_bg(evt):
            if DEBUG:
                print(f"[BLIT_DEBUG] _save_bg called - saving single figure background")
            self._bg_cache = canvas.copy_from_bbox(self.fig.bbox)
            if DEBUG:
                print(f"[BLIT_DEBUG] Background saved: cache={self._bg_cache is not None}")
        fig.canvas.mpl_connect("draw_event", _save_bg)
        fig.canvas.draw()          # first draw → backgrounds cached
    
        # ────────── control panel ─────────────────────────────────────
        ctrl = ttk.LabelFrame(col, text="Signal & display controls")
        ctrl.grid(row=1, column=0, sticky="ew", padx=4, pady=(4, 6))
        for c in range(7):
            ctrl.columnconfigure(c, weight=1)
    
        r = 0
        # Fs & Record
        ttk.Label(ctrl, text="Fs (Hz)").grid(row=r, column=0, sticky="e")
        self.fs_var  = tk.StringVar(value="250")
        fs_entry = ttk.Entry(ctrl, textvariable=self.fs_var, width=8)
        fs_entry.grid(row=r, column=1, sticky="we", padx=2)
        fs_entry.insert(0, self.fs_var.get())
    
        ttk.Label(ctrl, text="Record (s)").grid(row=r, column=2, sticky="e")
        self.dur_var = tk.StringVar(value="4")
        self.dur_entry = ttk.Entry(ctrl, textvariable=self.dur_var, width=6)
        self.dur_entry.grid(row=r, column=3, sticky="we", padx=2)
        self.dur_entry.insert(0, "4")  # Set initial display value
        ttk.Button(ctrl, text="Apply", command=self._apply_buf_settings).grid(row=r, column=4, padx=4)
        r += 1
    
        # amplitude slider (symmetric ± log scale)
        ttk.Label(ctrl, text="Amplitude ±V").grid(row=r, column=0, sticky="e")
        self.amp_var = tk.DoubleVar(value=0.5)
        
        # Create log scale slider (-6 to 0.7 represents 10^-6 to 10^0.7 ≈ 5V)
        self.amp_log_var = tk.DoubleVar(value=np.log10(0.5))
        self.amp_scale = tk.Scale(ctrl, from_=0.7, to=-6, resolution=0.01,
                 orient="horizontal", variable=self.amp_log_var,
                 command=self._update_amp_from_log,
                 showvalue=False)  # Don't show log value on slider
        self.amp_scale.grid(row=r, column=1, columnspan=4, sticky="we", padx=2)
        
        self.amp_entry = ttk.Entry(ctrl, textvariable=self.amp_var, width=8)
        self.amp_entry.grid(row=r, column=5, sticky="we", padx=2)
        self.amp_entry.bind('<Return>', self._update_amp_from_entry)
        self.amp_entry.bind('<FocusOut>', self._update_amp_from_entry)
        r += 1
    
        # NFFT
        ttk.Label(ctrl, text="NFFT").grid(row=r, column=0, sticky="e")
        self.nfft_var = tk.IntVar(value=512)
        self.nfft_sld = ttk.Scale(
            ctrl, from_=32, to=8192, variable=self.nfft_var,
            command=lambda v: (self.nfft_var.set(int(float(v))),
                               self._sig_update(fft_pts=int(float(v)))))
        self.nfft_sld.grid(row=r, column=1, columnspan=3, sticky="we", padx=2)
        self.nfft_label = ttk.Label(ctrl, text="512")
        self.nfft_label.grid(row=r, column=4, sticky="w", padx=2)
        
        # Update label when slider moves
        def update_nfft_label(v):
            val = int(float(v))
            self.nfft_var.set(val)
            self.nfft_label.config(text=str(val))
            self._sig_update(fft_pts=val)
        self.nfft_sld.config(command=update_nfft_label)
        r += 1
    
        # Chebyshev attenuation
        ttk.Label(ctrl, text="Cheb atten (dB)").grid(row=r, column=0, sticky="e")
        self.cheb_var = tk.DoubleVar(value=80.0)
        ttk.Scale(ctrl, from_=40, to=120, variable=self.cheb_var,
                  command=lambda v: (self.cheb_var.set(float(v)),
                                     self._sig_update(cheb_atten_db=float(v))))\
            .grid(row=r, column=1, columnspan=3, sticky="we", padx=2)
        ttk.Entry(ctrl, textvariable=self.cheb_var, width=6)\
            .grid(row=r, column=4, sticky="we", padx=2)
        r += 1
    
        # PSD limits
        ttk.Label(ctrl, text="PSD min (dB)").grid(row=r, column=0, sticky="e")
        self.psd_lo = tk.DoubleVar(value=-130)
        tk.Scale(ctrl, from_=-200, to=40, orient="horizontal",
                 variable=self.psd_lo,
                 command=lambda v: (self.psd_lo.set(float(v)),
                                    self._enforce_psd(lo=True)))\
            .grid(row=r, column=1, sticky="we", padx=2)
        ttk.Entry(ctrl, textvariable=self.psd_lo, width=6)\
            .grid(row=r, column=2, sticky="we", padx=2)
    
        ttk.Label(ctrl, text="PSD max (dB)").grid(row=r, column=3, sticky="e")
        self.psd_hi = tk.DoubleVar(value=0)
        tk.Scale(ctrl, from_=-200, to=40, orient="horizontal",
                 variable=self.psd_hi,
                 command=lambda v: (self.psd_hi.set(float(v)),
                                    self._enforce_psd(lo=False)))\
            .grid(row=r, column=4, sticky="we", padx=2)
        ttk.Entry(ctrl, textvariable=self.psd_hi, width=6)\
            .grid(row=r, column=5, sticky="we", padx=2)
    
        self.maxhold_on = tk.BooleanVar(value=False)
        self.maxhold_cb = ttk.Checkbutton(
            ctrl, text="Max-hold", variable=self.maxhold_on,
            command=self._on_maxhold_toggle
        )
        self.maxhold_cb.grid(row=r, column=6, sticky="w")
        ttk.Button(ctrl, text="Reset", command=self._reset_maxhold)\
            .grid(row=r, column=6, sticky="e", padx=4)

    def _on_maxhold_toggle(self):
        if DEBUG:
            print(f"[BLIT_DEBUG] Max-hold toggled: {self.maxhold_on.get()}")
        # Always update visibility immediately
        for idx in range(16):
            self.psd_max[idx].set_visible(self.maxhold_on.get())
        if DEBUG:
            print(f"[BLIT_DEBUG] Calling draw() due to max-hold toggle")
        self.ax_psd.figure.canvas.draw()
        self._bg_cache = self.fig_canvas.copy_from_bbox(self.fig.bbox)
        if DEBUG:
            print(f"[BLIT_DEBUG] Background cache updated after max-hold toggle: {self._bg_cache is not None}")


        
    # live SigConfig update and safety-clamped NFFT
    def _sig_update(self, **kwargs):
        """Sync SigConfig with worker, and clamp NFFT ≤ buffer length."""
        if DEBUG:
            print(f"[BLIT_DEBUG] _sig_update called with: {kwargs}")
        
        if hasattr(self, "sig") and self.sig:
            self.sig.update_cfg(**kwargs)
        if hasattr(self, "sig_cfg"):
            self.sig_cfg.__dict__.update(kwargs)

        # Handle NFFT clamping
        if 'fft_pts' in kwargs:
            total    = self.sig_cfg.sample_rate * self.sig_cfg.buf_secs
            max_pow2 = 1 << (total.bit_length() - 1)
            if self.nfft_var.get() > max_pow2:
                self.nfft_var.set(max_pow2)
            if hasattr(self, "nfft_sld"):
                self.nfft_sld.configure(to=max_pow2)
                
        # Handle other updates that need immediate visual feedback
        if 'cheb_atten_db' in kwargs:
            if DEBUG:
                print(f"[BLIT_DEBUG] Chebyshev attenuation changed to: {kwargs['cheb_atten_db']}")
            # This affects the PSD window function - we'll see it in next frame
        
    # update amplitude limits (symmetric ±)
    def _update_amp(self):
        a = max(1e-6, min(5.0, float(self.amp_var.get())))
        self.amp_var.set(a)
        self.ax_time.set_ylim(-a, a)
        # Immediate update without full redraw
        self.fig_canvas.draw_idle()
        
    def _update_amp_from_log(self, log_val):
        """Update amplitude from log scale slider"""
        linear_val = 10 ** float(log_val)
        self.amp_var.set(linear_val)
        self.ax_time.set_ylim(-linear_val, linear_val)
        if DEBUG:
            print(f"[BLIT_DEBUG] Amplitude slider: ±{linear_val:.6f}V, ylim set to ({-linear_val:.6f}, {linear_val:.6f})")
    
        # Force immediate redraw of the figure and update background
        if DEBUG:
            print(f"[BLIT_DEBUG] Calling draw() due to amplitude change")
        self.fig_canvas.draw()
        self._bg_cache = self.fig_canvas.copy_from_bbox(self.fig.bbox)
        if DEBUG:
            print(f"[BLIT_DEBUG] Background cache updated after amplitude change: {self._bg_cache is not None}")
            
    def _update_amp_from_entry(self, event=None):
        """Update log slider when entry is changed"""
        try:
            val = float(self.amp_var.get())
            val = max(1e-6, min(5.0, val))
            self.amp_var.set(val)
            self.amp_log_var.set(np.log10(val))
            self.ax_time.set_ylim(-val, val)
    
            if DEBUG:
                print(f"[BLIT_DEBUG] Calling draw() due to amplitude entry change")
            self.fig_canvas.draw()
            self._bg_cache = self.fig_canvas.copy_from_bbox(self.fig.bbox)
            if DEBUG:
                print(f"[BLIT_DEBUG] Background cache updated after amplitude entry change: {self._bg_cache is not None}")
        except ValueError:
            pass

        
    # ── apply Fs / Record settings --------------------------------------
    def _apply_buf_settings(self):
        if DEBUG:
            print(f"[DURATION_TRACE] === APPLY BUTTON CLICKED ===")
        
        # Enable debug mode for the next few animation cycles
        self._animate_debug_mode = True
        
        # Read directly from Entry widget instead of StringVar
        dur_entry_text = self.dur_entry.get()
        fs_entry_text = self.fs_var.get()  # fs still works with StringVar
        
        if DEBUG:
            print(f"[DURATION_TRACE] Step 1: Raw value from dur_entry.get() = '{dur_entry_text}'")
            print(f"[DURATION_TRACE] Step 1b: Raw value from dur_var.get() = '{self.dur_var.get()}'")
            print(f"[DURATION_TRACE] Step 2: Raw value from fs_var.get() = '{fs_entry_text}'")
        
        try:
            new_fs  = int(float(fs_entry_text))
            if DEBUG:
                print(f"[DURATION_TRACE] Step 3: Parsed new_fs = {new_fs}")
            new_dur = int(float(dur_entry_text))
            if DEBUG:
                print(f"[DURATION_TRACE] Step 4: Parsed new_dur = {new_dur}")
            if new_fs <= 0 or new_dur <= 0:
                raise ValueError
        except ValueError:
            if DEBUG:
                print(f"[DURATION_TRACE] Step 5: PARSE ERROR - Invalid values, returning")
            return
    
        if DEBUG:
            print(f"[DURATION_TRACE] Step 6: Validation passed - fs={new_fs}, dur={new_dur}")
        
        # Update the StringVar to match what user actually entered
        self.dur_var.set(str(new_dur))
        if DEBUG:
            print(f"[DURATION_TRACE] Step 6b: Updated dur_var to '{self.dur_var.get()}'")
        
        # 1 ─ Pause data reception and update buffer without killing worker
        if self.sig:
            if DEBUG:
                print(f"[DURATION_TRACE] Step 7: Pausing signal worker for buffer update")
            # Tell signal worker to pause reception
            self.sig.pause_reception = True
            time.sleep(0.1)  # Give time for current packet processing to finish
            
            # Flush any pending UDP packets
            if hasattr(self.sig, '_udp_sock') and self.sig._udp_sock:
                self.sig._udp_sock.settimeout(0.01)
                while True:
                    try:
                        self.sig._udp_sock.recv(65536)  # Discard data
                    except socket.timeout:
                        break
                    except:
                        break
                self.sig._udp_sock.settimeout(0.1)  # Restore timeout
            
            # Update configuration
            if DEBUG:
                print(f"[DURATION_TRACE] Step 8: Updating signal configuration")
                print(f"[DURATION_TRACE] Step 8a: Before update - sig_cfg.buf_secs = {self.sig_cfg.buf_secs}")
            self.sig_cfg.sample_rate = new_fs
            self.sig_cfg.buf_secs = new_dur
            if DEBUG:
                print(f"[DURATION_TRACE] Step 8b: After update - sig_cfg.buf_secs = {self.sig_cfg.buf_secs}")
            self.sig.update_cfg(sample_rate=new_fs, buf_secs=new_dur)
            
            # Clear the buffer and resize
            if DEBUG:
                print(f"[DURATION_TRACE] Step 9: Resizing buffer")
            self.sig._buf = np.zeros((new_fs * new_dur, 16), dtype=np.float32)
            self.sig._ptr = 0
            
            # Resume reception
            self.sig.pause_reception = False
            if DEBUG:
                print(f"[DURATION_TRACE] Step 10: Resumed signal reception")
        else:
            # No existing worker, create new one
            if DEBUG:
                print(f"[DURATION_TRACE] Step 11: Creating new signal worker")
            self.sig_cfg = SigConfig(sample_rate=new_fs,
                                     buf_secs=new_dur,
                                     n_ch=16)
            self.sig = SignalWorker(self.sig_cfg,
                                    data_port=int(self.data_port_var.get()))
            self.sig.start()
    
        # 3 ─ Clear all artists from axes
        if DEBUG:
            print(f"[DURATION_TRACE] Step 12: Clearing all artists")
            print(f"[BLIT_DEBUG] Clearing axes - this will invalidate background cache")
        self.ax_dt.clear()
        self.ax_time.clear()
        self.ax_wav.clear()
        self.ax_sg.clear()
        self.ax_psd.clear()
        
        # 4 ─ Recreate axes labels and settings
        self.ax_dt.set_ylabel("Δt [µs]"); self.ax_dt.grid(ls=":")
        self.ax_time.set_ylabel("V");     self.ax_time.grid(ls=":")
        # Restore current amplitude limits
        current_amp = self.amp_var.get()
        self.ax_time.set_ylim(-current_amp, current_amp)
        self.ax_wav.set_ylabel("f [Hz]")
        self.ax_sg .set_ylabel("f [Hz]")
        self.ax_psd.set_ylabel("dB"); self.ax_psd.set_xlabel("Hz"); self.ax_psd.grid(ls=":")
        # Restore current PSD limits
        self.ax_psd.set_ylim(self.psd_lo.get(), self.psd_hi.get())
        
        # 5 ─ Recreate all line objects and images with proper X-axis in seconds
        N0 = int(new_dur * new_fs)
        xs_sec = np.arange(N0) / new_fs  # X-axis in seconds
        if DEBUG:
            print(f"[DURATION_TRACE] Step 13: Creating time axis xs_sec with {N0} points over {new_dur} seconds")
            print(f"[DURATION_TRACE] Step 13a: xs_sec ranges from {xs_sec[0]} to {xs_sec[-1]}")
        
        self.dt_line,    = self.ax_dt.plot(xs_sec, np.zeros(N0), lw=.8)
        self.time_lines  = [self.ax_time.plot(xs_sec, np.zeros(N0), lw=.8)[0]
                            for _ in range(16)]
        # Create dummy images with proper initial extent
        dummy_rows = 64
        self.im_wavelet  = self.ax_wav.imshow(np.zeros((dummy_rows, N0)), origin="lower",
                                              aspect="auto", extent=(0, new_dur, 1, new_fs/2),
                                              vmin=-60, vmax=0)
        self.im_specgram = self.ax_sg.imshow (np.zeros((dummy_rows, N0)), origin="lower",
                                              aspect="auto", extent=(0, new_dur, 0, new_fs/2),
                                              vmin=-80, vmax=0)
        self.psd_lines = [self.ax_psd.plot([], [], lw=.8)[0] for _ in range(16)]
        self.psd_max   = [self.ax_psd.plot([], [], lw=.8, ls="--",
                             color=self.psd_lines[i].get_color())[0]
                          for i in range(16)]
        
        # MARK NEW ARTISTS AS ANIMATED
        self.dt_line.set_animated(True)
        for line in self.time_lines:
            line.set_animated(True)
        self.im_wavelet.set_animated(True)
        self.im_specgram.set_animated(True)
        for line in (*self.psd_lines, *self.psd_max):
            line.set_animated(True)
        
        # 6 ─ Update the GUI axes to 0…Record-s and force proper limits
        if DEBUG:
            print(f"[DURATION_TRACE] Step 14: Setting axes xlim to 0-{new_dur} seconds")
        for ax in (self.ax_time, self.ax_wavelet, self.ax_specgram, self.ax_dt):
            if DEBUG:
                print(f"[DURATION_TRACE] Step 14a: Setting {ax} xlim to (0, {new_dur})")
            ax.set_xlim(0, new_dur)
            ax.set_xlabel("Time (s)")  # Make it clear it's in seconds
            if DEBUG:
                print(f"[DURATION_TRACE] Step 14b: After set_xlim, {ax}.get_xlim() = {ax.get_xlim()}")
        
        # Update NFFT slider maximum based on new buffer size
        total_samples = new_fs * new_dur
        max_pow2 = 1 << (total_samples.bit_length() - 1)
        self.nfft_sld.configure(to=max_pow2)
        if self.nfft_var.get() > max_pow2:
            self.nfft_var.set(max_pow2)
            self.nfft_label.config(text=str(max_pow2))
        else:
            self.nfft_label.config(text=str(self.nfft_var.get()))
        
        # 7 ─ Clear old background
        if DEBUG:
            print(f"[BLIT_DEBUG] Step 15: Explicitly clearing background cache")
        self._bg_cache = None
        
        # 8 ─ Reset previous fs and duration to force rebuild in animate
        if DEBUG:
            print(f"[DURATION_TRACE] Step 16: Updating sig_cfg and prev tracking")
        self.sig_cfg.sample_rate = new_fs
        self.sig_cfg.buf_secs = new_dur
        if DEBUG:
            print(f"[DURATION_TRACE] Step 16a: sig_cfg.buf_secs now = {self.sig_cfg.buf_secs}")
        
        # Reset max-hold data
        self.maxhold_data = [None] * 16
        
        # 9 ─ Force full redraw and update display
        if DEBUG:
            print(f"[BLIT_DEBUG] Step 17: Calling fig_canvas.draw() to rebuild everything")
        self.fig_canvas.draw()
        if DEBUG:
            print(f"[BLIT_DEBUG] Step 17a: Draw complete, creating new background cache")
        self.fig_canvas.flush_events()
        self._bg_cache = self.fig_canvas.copy_from_bbox(self.fig.bbox)
        if DEBUG:
            print(f"[BLIT_DEBUG] Step 17b: Background cache created: {self._bg_cache is not None}")
        
        # Update the status in console
        self.ser_console.configure(state="normal")
        self.ser_console.insert("end", f"[PC] Buffer updated: {new_fs} Hz, {new_dur} s ({N0} samples)\n")
        self.ser_console.configure(state="disabled")
        self.ser_console.see("end")
        
        if DEBUG:
            print(f"[DURATION_TRACE] Step 18: sig_cfg now has: fs={self.sig_cfg.sample_rate}, dur={self.sig_cfg.buf_secs}")
            print(f"[DURATION_TRACE] Step 19: signal buffer shape = {self.sig._buf.shape}")
            print(f"[DURATION_TRACE] Step 20: _apply_buf_settings complete")
        # Apply current NFFT clamp and cheb_atten immediately
        self._sig_update(fft_pts=self.nfft_var.get(),
                         cheb_atten_db=self.cheb_var.get())
        
        self._prev_dur = new_dur  # Use the actual parsed value
        if DEBUG:
            print(f"[DURATION_TRACE] Step 21: Set _prev_dur = {self._prev_dur}")
            print(f"[DURATION_TRACE] === APPLY BUTTON COMPLETE ===")
        


    
    def _enforce_limits(self, lo=True):
        self.ax_time.set_ylim(self.lim_lo.get(), self.lim_hi.get())
    
    def _enforce_psd(self, lo=True):
        if lo and self.psd_lo.get() >= self.psd_hi.get():
            self.psd_lo.set(self.psd_hi.get() - 1)
        elif not lo and self.psd_hi.get() <= self.psd_lo.get():
            self.psd_hi.set(self.psd_lo.get() + 1)
    
        # apply the new limits instantly
        if hasattr(self, "ax_psd"):
            new_lo, new_hi = self.psd_lo.get(), self.psd_hi.get()
            self.ax_psd.set_ylim(new_lo, new_hi)
            if DEBUG:
                print(f"[BLIT_DEBUG] PSD limits updated: ({new_lo}, {new_hi}) dB")
    
            if DEBUG:
                print(f"[BLIT_DEBUG] Calling draw() due to PSD limits change")
            self.fig_canvas.draw()
            self._bg_cache = self.fig_canvas.copy_from_bbox(self.fig.bbox)
            if DEBUG:
                print(f"[BLIT_DEBUG] Background cache updated after PSD limits change: {self._bg_cache is not None}")


    
    def _reset_maxhold(self):
        self.maxhold_data = [None] * 16
        if DEBUG:
            print(f"[BLIT_DEBUG] Max-hold data reset")
        for ln in self.psd_max:
            ln.set_visible(False)
            ln.set_data([], [])  # clear visibly
        if DEBUG:
            print(f"[BLIT_DEBUG] Calling draw() due to max-hold reset")
        self.ax_psd.figure.canvas.draw()
        self._bg_cache = self.fig_canvas.copy_from_bbox(self.fig.bbox)
        if DEBUG:
            print(f"[BLIT_DEBUG] Background cache updated after max-hold reset: {self._bg_cache is not None}")




    # ── debounced draw ---------------------------------------------------
    def _queue_redraw(self, _):
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(self.RESIZE_DELAY_MS, self._do_redraw)

    def _do_redraw(self):
        self.fig_canvas.draw_idle()
        self._resize_job = None
    
    def _toggle_serial(self):
        if self.ser_btn["text"] == "Connect":      # ---- connect
            self.ser.start(self.port_var.get(), int(self.baud_var.get()))
            self.ser_btn.config(text="Disconnect")
            self.port_cb.config(state="disabled")
        else:                                      # ---- disconnect
            self.ser.stop()
            self.ser_btn.config(text="Connect")
            self.port_cb.config(state="readonly")
        
    def _send_net_config(self):
        if self.ser_btn["text"] != "Disconnect":
            return
    
        # ⬇ NEW: read directly from the Entry widgets
        ssid = self.ssid_entry.get().strip()
        pw   = self.pass_entry.get().strip()
    
        if not ssid or not pw:
            self.ser.rx_q.put("[PC] ✖ SSID / Password required\n")
            return
    
        snd = self.ser.send_and_wait
        snd(f"set ssid {ssid}")
        snd(f"set pass {pw}")
        snd(f"set ip {self.pc_ip_var.get().strip()}")
        snd(f"set port_ctrl {self.ctrl_port_var.get().strip()}")
        snd(f"set port_data {self.data_port_var.get().strip()}")
        snd("apply and reboot")




        
    # ── refresh COM-port list ───────────────────────────────────────────
    def _refresh_ports(self):
        plist = SerialManager.ports()          # fresh scan every call
        self.port_cb["values"] = plist or ("",)
    
        # if current selection vanished → pick the first detected port
        if plist and self.port_var.get() not in plist:
            self.port_var.set(plist[0])
            try:
                self.port_cb.current(0)
            except tk.TclError:
                pass                           # widget may be disabled
    
        # ←————  schedule the next scan!
        self.after(1000, self._refresh_ports)



    # ── IO blocks --------------------------------------------------------
    def _build_io_block(self, col_idx, title, build_controls):
        frame = ttk.Frame(self)
        frame.grid(row=0, column=col_idx, sticky="nsew",
                   padx=(6,3) if col_idx==1 else (3,6))
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1); frame.columnconfigure(1, weight=0)

        ctl = ttk.LabelFrame(frame, text=title)
        ctl.grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=4)
        build_controls(ctl)

        txt = tk.Text(frame, wrap="word", bg=self.BG, fg=self.FG,
                      insertbackground=self.FG, state="disabled")
        txt.grid(row=1, column=0, sticky="nsew", padx=(2,0), pady=(0,2))
        sb  = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
        sb.grid(row=1, column=1, sticky="ns", padx=(0,2), pady=(0,2))
        txt.configure(yscrollcommand=sb.set)
        return txt

    # ── control bars -----------------------------------------------------
    # ── control bar + Wi-Fi params ───────────────────────────
    # ── control bar + Wi-Fi params ───────────────────────────
    def _serial_controls(self, parent):
        # one flexible column for the Entry widgets
        parent.columnconfigure(1, weight=1)

        # ── row-0 : COM port ───────────────────────────────────
        ttk.Label(parent, text="Port").grid(row=0, column=0, sticky="e")
        self.port_var = tk.StringVar()
        self.port_cb = ttk.Combobox(parent, textvariable=self.port_var,
                                    values=[], state="readonly")
        self.port_cb.grid(row=0, column=1, sticky="we", padx=2)

        # ── row-1 : Baud rate ──────────────────────────────────
        ttk.Label(parent, text="Baud").grid(row=1, column=0, sticky="e")
        self.baud_var = tk.StringVar(value="115200")
        ent = ttk.Entry(parent, textvariable=self.baud_var)
        ent.insert(0, self.baud_var.get())
        ent.grid(row=1, column=1, sticky="we", padx=2)

        # ── row-2 : Connect / Disconnect button ───────────────
        self.ser_btn = ttk.Button(parent, text="Connect",
                                  command=self._toggle_serial)
        self.ser_btn.grid(row=2, column=0, columnspan=2,
                          sticky="we", pady=(0, 4))

        # ── row-3 : SSID ───────────────────────────────────────
        ttk.Label(parent, text="SSID").grid(row=3, column=0, sticky="e")
        self.ssid_var = tk.StringVar(value="SlimeVR")                # put your default here
        ent = ttk.Entry(parent, textvariable=self.ssid_var)
        self.ssid_entry = ent
        ent.insert(0, self.ssid_var.get())
        ent.grid(row=3, column=1, sticky="we", padx=2)

        # ── row-4 : Password ──────────────────────────────────
        ttk.Label(parent, text="Password").grid(row=4, column=0, sticky="e")
        self.pass_var = tk.StringVar(value="")                # put your default here
        ent = ttk.Entry(parent, textvariable=self.pass_var, show="*")
        self.pass_entry = ent
        ent.insert(0, self.pass_var.get())
        ent.grid(row=4, column=1, sticky="we", padx=2)

        # ── row-5 : PC IP ─────────────────────────────────────
        ttk.Label(parent, text="PC IP").grid(row=5, column=0, sticky="e")
        self.pc_ip_var = tk.StringVar(
            value=socket.gethostbyname(socket.gethostname()))
        ent = ttk.Entry(parent, textvariable=self.pc_ip_var)
        ent.insert(0, self.pc_ip_var.get())
        ent.grid(row=5, column=1, sticky="we", padx=2)

        # ── row-6 : Data port ─────────────────────────────────
        ttk.Label(parent, text="Data port").grid(row=6, column=0, sticky="e")
        self.data_port_var = tk.StringVar(value="5001")
        ent = ttk.Entry(parent, textvariable=self.data_port_var, width=8)
        ent.insert(0, self.data_port_var.get())
        ent.grid(row=6, column=1, sticky="we", padx=2)

        # ── row-7 : Control port ──────────────────────────────
        ttk.Label(parent, text="Ctrl port").grid(row=7, column=0, sticky="e")
        self.ctrl_port_var = tk.StringVar(value="5000")
        ent = ttk.Entry(parent, textvariable=self.ctrl_port_var, width=8)
        ent.insert(0, self.ctrl_port_var.get())
        ent.grid(row=7, column=1, sticky="we", padx=2)

        # ── row-8 : Send-config button ────────────────────────
        ttk.Button(parent, text="Send net config",
                   command=self._send_net_config
                   ).grid(row=8, column=0, columnspan=2,
                          sticky="we", pady=(4, 0))

        # initialise port list & schedule refresh
        self._refresh_ports()









        # ── Wi-Fi / board-control panel ───────────────────────────────────────
    def _wifi_controls(self, parent):

        # helpers ──────────────────────────────────────────────────────────
        parent.columnconfigure(0, weight=1)          # whole column stretches

        def row_frame(r, n_cols):
            """Return a frame with *n_cols* equal-width columns at grid-row r."""
            frm = ttk.Frame(parent); frm.grid(row=r, column=0, sticky="we")
            for c in range(n_cols):
                frm.columnconfigure(c, weight=1, uniform=f"w{r}")
            return frm

        # ── helper: labelled two-button selector ────────────────────────────────
        def two_way(frm, col, text, cmd_a, cmd_b,
                    labels=("ON", "OFF"),             # NEW
                    default="A"):
            """
            Place a header + two side-by-side buttons in *frm* starting at *col*.
        
            labels : (left_text, right_text)
            default: "A" | "B"  → which button is active at start
            """
            state = {"sel": None}                         # current side
        
            # header
            ttk.Label(frm, text=text).grid(row=0, column=col, columnspan=2,
                                           sticky="we", pady=(0, 1))
        
            # sub-frame so both buttons have equal width
            box = ttk.Frame(frm); box.grid(row=1, column=col, sticky="we")
            for c in (0, 1):
                box.columnconfigure(c, weight=1)
        
            btnA = ttk.Button(box, text=labels[0])
            btnB = ttk.Button(box, text=labels[1])
            btnA.grid(row=0, column=0, sticky="we", padx=1)
            btnB.grid(row=0, column=1, sticky="we", padx=1)
        
            def _apply_styles():
                btnA.configure(style="On.TButton"  if state["sel"] == "A"
                                                else "Off.TButton")
                btnB.configure(style="On.TButton"  if state["sel"] == "B"
                                                else "Off.TButton")
        
            def _click(which):
                if state["sel"] == which:                 # already active
                    return
                state["sel"] = which
                _apply_styles()
                self._send_udp_cmd(cmd_a if which == "A" else cmd_b)
        
            btnA.configure(command=lambda: _click("A"))
            btnB.configure(command=lambda: _click("B"))
        
            # initialise
            state["sel"] = default
            _apply_styles()


        # ──────────────────────────────────────────────────────────────────
        r = 0                                                         # row index

        # UDP connect / disconnect
        self.wifi_btn = ttk.Button(parent, text="UDP Connect",
                                   command=self._toggle_udp)
        self.wifi_btn.grid(row=r, column=0, sticky="we", padx=2, pady=(0, 8))
        r += 1

        # ── maintenance trio (board / adc / erase) ───────────────────────
        f = row_frame(r, 3);  r += 1
        ttk.Button(f, text="Board Reboot",
                   command=lambda: self._send_udp_cmd("sys esp_reboot")
                   ).grid(row=0, column=0, sticky="we", padx=2, pady=1)
        ttk.Button(f, text="ADC reset",
                   command=lambda: self._send_udp_cmd("sys adc_reset")
                   ).grid(row=0, column=1, sticky="we", padx=2, pady=1)
        ttk.Button(f, text="Erase Wi-Fi",
                   command=lambda: self._send_udp_cmd("sys erase_flash")
                   ).grid(row=0, column=2, sticky="we", padx=2, pady=1)

        # ── filter master & mains frequency ──────────────────────────────
        f = row_frame(r, 2);  r += 1
        two_way(f, 0, "All filters",      "sys filters_on",  "sys filters_off", default="B")
        two_way(f, 1, "Network 50 / 60 Hz",
                "sys networkfreq 50", "sys networkfreq 60",
                labels=("50 Hz", "60 Hz"),              # ← NEW labels
                default="A")                            # default = 50 Hz

        # ── equaliser & DC-block ─────────────────────────────────────────
        f = row_frame(r, 2);  r += 1
        two_way(f, 0, "Equaliser", "sys filter_equalizer_on",
                              "sys filter_equalizer_off",    default="B")
        two_way(f, 1, "DC-block",  "sys filter_dc_on",
                              "sys filter_dc_off",           default="B")

        # ── notch filters ────────────────────────────────────────────────
        f = row_frame(r, 2);  r += 1
        two_way(f, 0, "50 / 60 Hz notch",
                "sys filter_5060_on",  "sys filter_5060_off",  default="B")
        two_way(f, 1, "100 / 120 Hz notch",
                "sys filter_100120_on","sys filter_100120_off",default="B")

        # ── DC-cut dropdown ──────────────────────────────────────────────
        f = row_frame(r, 3);  r += 1
        ttk.Label(f, text="DC-cutoff (Hz)").grid(row=0, column=0, sticky="e", padx=2)
        
        dc_values          = ["0.5", "1", "2", "4", "8"]
        self.dccut_var     = tk.StringVar(value=dc_values[0])      # ← default
        dccut_cb           = ttk.Combobox(
            f, textvariable=self.dccut_var, state="readonly", values=dc_values
        )
        dccut_cb.grid(row=0, column=1, sticky="we", padx=2)
        dccut_cb.current(0)                                        # show ″0.5″
        ttk.Button(
            f, text="Set",
            command=lambda cb=dccut_cb:
                self._send_udp_cmd(f"sys dccutofffreq {cb.get()}")
        ).grid(row=0, column=2, sticky="we", padx=2, pady=1)
        
        # ── digital-gain dropdown ───────────────────────────────────────
        f = row_frame(r, 3);  r += 1
        ttk.Label(f, text="Digital gain (×)").grid(row=0, column=0, sticky="e", padx=2)
        
        gain_values        = ["1", "2", "4", "8", "16", "32", "64", "128", "256"]
        self.gain_var      = tk.StringVar(value=gain_values[0])    # ← default
        gain_cb            = ttk.Combobox(
            f, textvariable=self.gain_var, state="readonly", values=gain_values
        )
        gain_cb.grid(row=0, column=1, sticky="we", padx=2)
        gain_cb.current(0)                                         # show ″1″
        ttk.Button(
            f, text="Set",
            command=lambda cb=gain_cb:
                self._send_udp_cmd(f"sys digitalgain {cb.get()}")
        ).grid(row=0, column=2, sticky="we", padx=2, pady=1)

        # ── continuous-mode controls ─────────────────────────────────────
        f = row_frame(r, 2);  r += 1
        ttk.Button(f, text="Start CNT",
                   command=lambda: self._send_udp_cmd("sys start_cnt")
                   ).grid(row=0, column=0, sticky="we", padx=2, pady=(4, 1))
        ttk.Button(f, text="Stop CNT",
                   command=lambda: self._send_udp_cmd("sys stop_cnt")
                   ).grid(row=0, column=1, sticky="we", padx=2, pady=(4, 1))


    # ── start / stop UDP listener ─────────────────────────────────────────
    def _toggle_udp(self):
        if self.udp and self.udp._thread and self.udp._thread.is_alive():        # stop
            self.udp.stop()
            self.udp = None
            self.wifi_btn.config(text="UDP Connect")
            self.wifi_console.insert("end", "[PC] UDP disconnected\n")
            return

        # start
        try:
            port = int(self.ctrl_port_var.get())
        except ValueError:
            self.wifi_console.insert("end", "[PC] ✖ Invalid control-port\n")
            return

        self.udp = UDPManager(port)
        self.udp.start()
        self.udp.rx_q = self.wifi_q
        self.udp.tx_hook = lambda pkt: self.wifi_q.put(f"[PC_] {pkt}\n")

        self.wifi_btn.config(text="Disconnect")
        self.wifi_console.insert(
            "end", f"[PC] UDP listening on *:{port} … waiting for beacon\n")

    # ── helper: transmit one command over UDP (no local echo) ─────────────
    def _send_udp_cmd(self, cmd: str):
        """
        Queue *cmd* for transmission over UDP.
        Echo appears once via udp_backend.tx_hook so no duplicates.
        """
        if self.udp and self.udp.board_ip:
            self.udp.send(cmd)
        else:
            self.wifi_q.put("[PC] ✖ UDP not connected / board IP unknown\n")


    # helper → "DC-cutoff freq, Hz Set"
    def _send_dccut(self):
        self._send_udp_cmd(f"sys dccutofffreq {self.dccut_var.get()}")

    # helper → "Gain Set"
    def _send_gain(self):
        self._send_udp_cmd(f"sys digitalgain {self.gain_var.get()}")






    # ── animate plots ----------------------------------------------------
    def _animate_plots(self):
        """
        Animation loop that updates plots every 16ms.
        
        CRITICAL FIX: This method now uses the expected duration for x-axis
        calculation instead of the actual snapshot data size, which solves
        the duration update issue.
        """
        # stay idle until UDP really connected
        if not (self.udp and self.udp.board_ip):
            self.after(100, self._animate_plots)
            return
    
        if not self.sig:  # Safety check
            self.after(100, self._animate_plots)
            return
            
        snap = self.sig.snapshot()
        if snap is None:
            self.after(16, self._animate_plots)
            return
    
        if DEBUG:
            print(f"[DURATION_TRACE] === ANIMATE PLOTS ENTRY ===")
        data   = snap["data"]                 # (N,16)
        npts   = data.shape[0]
        fs_val = self.sig_cfg.sample_rate
        self._prev_fs = getattr(self, "_prev_fs", fs_val)
        if DEBUG:
            print(f"[DURATION_TRACE] Animate: npts={npts}, fs_val={fs_val}, _prev_fs={self._prev_fs}")
            print(f"[DURATION_TRACE] Animate: Expected buffer size for {self.sig_cfg.buf_secs}s at {fs_val}Hz = {int(self.sig_cfg.buf_secs * fs_val)} points")
            print(f"[DURATION_TRACE] Animate: Actual signal buffer shape = {self.sig._buf.shape if hasattr(self.sig, '_buf') else 'N/A'}")
            print(f"[DURATION_TRACE] Animate: Signal worker buf_secs = {getattr(self.sig.cfg, 'buf_secs', 'N/A') if hasattr(self.sig, 'cfg') else 'N/A'}")
    
        # ==================================================================
        # CRITICAL FIX: Use full buffer size for x-axis, not snapshot size
        # ==================================================================
        expected_npts = int(self.sig_cfg.buf_secs * fs_val)
        if DEBUG:
            print(f"[DURATION_TRACE] FIX: Snapshot returned {npts} points but buffer should have {expected_npts} points")
            print(f"[DURATION_TRACE] FIX: Creating x-axis for full {self.sig_cfg.buf_secs}s duration regardless of snapshot size")
        
        # x-vector in **seconds** - use FULL DURATION, not snapshot size
        xs_sec = np.arange(expected_npts) / fs_val
        if DEBUG:
            print(f"[DURATION_TRACE] Animate: xs_sec created with {len(xs_sec)} points, range {xs_sec[0]:.3f} to {xs_sec[-1]:.3f}")
            print(f"[DURATION_TRACE] FIX APPLIED: xs_sec now covers full {self.sig_cfg.buf_secs}s duration")
        
        # Use the config duration, which is the authoritative source after Apply
        duration = self.sig_cfg.buf_secs
        if DEBUG:
            print(f"[DURATION_TRACE] Animate: Using sig_cfg.buf_secs = {duration}")
            print(f"[DURATION_TRACE] Animate: For comparison, dur_var.get() = '{self.dur_var.get()}'")
            print(f"[DURATION_TRACE] Animate: For comparison, dur_entry.get() = '{self.dur_entry.get()}'")
        
        # rebuild line objects if length OR Fs changed -------------------
        prev_dur = getattr(self, '_prev_dur', duration)
        if DEBUG:
            print(f"[DURATION_TRACE] Animate: Comparing durations - current={duration}, prev={prev_dur}")
        
        need_rebuild = (
            xs_sec.size != self.time_lines[0].get_xdata().size or
            fs_val != self._prev_fs or
            abs(duration - prev_dur) > 1e-6
        )
        
        if DEBUG:
            print(f"[DURATION_TRACE] Animate: Rebuild check:")
            print(f"[DURATION_TRACE] Animate:   xs_sec.size={xs_sec.size} vs time_lines[0].size={self.time_lines[0].get_xdata().size}")
            print(f"[DURATION_TRACE] Animate:   fs_val={fs_val} vs _prev_fs={self._prev_fs}")
            print(f"[DURATION_TRACE] Animate:   duration diff = {abs(duration - prev_dur)}")
            print(f"[DURATION_TRACE] Animate:   need_rebuild = {need_rebuild}")
    
        if need_rebuild:
            if DEBUG:
                print(f"[DURATION_TRACE] Animate: REBUILDING!")
            for ln in (*self.time_lines, self.dt_line):
                ln.set_xdata(xs_sec)
                ln.set_ydata(np.zeros_like(xs_sec))
            for ax in (self.ax_time, self.ax_wavelet, self.ax_specgram, self.ax_dt):
                if DEBUG:
                    print(f"[DURATION_TRACE] Animate REBUILD: Setting {ax} xlim to (0, {duration})")
                ax.set_xlim(0, duration)
                if DEBUG:
                    print(f"[DURATION_TRACE] Animate REBUILD: After set_xlim, {ax}.get_xlim() = {ax.get_xlim()}")
            if DEBUG:
                print(f"[DURATION_TRACE] Animate: Calling draw() for rebuild")
            self.fig_canvas.draw()            # new blit backgrounds
            # CRITICAL: Update background cache after rebuild
            self._bg_cache = self.fig_canvas.copy_from_bbox(self.fig.bbox)
            if DEBUG:
                print(f"[DURATION_TRACE] Animate: After draw(), background cached")
            self._prev_fs = fs_val            # store for next call
            self._prev_dur = duration         # store duration too
            if DEBUG:
                print(f"[DURATION_TRACE] Animate: Updated _prev_fs={fs_val}, _prev_dur={duration}")
        else:
            if DEBUG:
                print(f"[DURATION_TRACE] Animate: NO REBUILD - keeping existing xlim")
                for ax in (self.ax_time, self.ax_wavelet, self.ax_specgram, self.ax_dt):
                    print(f"[DURATION_TRACE] Animate NO REBUILD: {ax}.get_xlim() = {ax.get_xlim()}")
    
        # Re-acquire background if missing (e.g. after resize)
        if self._bg_cache is None:
            if DEBUG:
                print(f"[DURATION_TRACE] Animate: Background cache missing, redrawing")
            self.fig_canvas.draw()
            self._bg_cache = self.fig_canvas.copy_from_bbox(self.fig.bbox)
    
        # Δt (for now just showing zeros as placeholder)
        self.dt_line.set_ydata(np.zeros(xs_sec.size))
    
        # time-domain --------------------------------------------------------
        # Handle case where snapshot data is smaller than full buffer
        if data.shape[0] < xs_sec.size:
            if DEBUG:
                print(f"[DURATION_TRACE] Animate: Snapshot data ({data.shape[0]}) < full buffer ({xs_sec.size})")
            # Create zero-padded data that matches the full x-axis
            full_data = np.zeros((xs_sec.size, 16))
            # Put the snapshot data at the end (most recent)
            full_data[-data.shape[0]:] = data
            for ln, ch in zip(self.time_lines, full_data.T):
                ln.set_ydata(ch)
        else:
            # If we somehow have more data than expected, just use the last portion
            for ln, ch in zip(self.time_lines, data[-xs_sec.size:].T):
                ln.set_ydata(ch)
    
        # spectrogram (seconds on x-axis) ------------------------------------
        # Use the most recent data for spectrogram (or pad if needed)
        if data.shape[0] < expected_npts:
            # Pad with zeros at the beginning
            spec_data = np.zeros(expected_npts)
            spec_data[-data.shape[0]:] = data[:, 0]
        else:
            spec_data = data[-expected_npts:, 0]
            
        f_s, t_s, Sxx = sps.spectrogram(spec_data, fs=fs_val,
                                        window="hann", nperseg=256, noverlap=128)
        self.im_specgram.set_data(10*np.log10(Sxx + 1e-12))
        # extent: (t_left, t_right, f_low, f_high)
        self.im_specgram.set_extent((0, duration, f_s[0], f_s[-1]))
        if DEBUG:
            print(f"[DURATION_TRACE] Animate: Set spectrogram extent to (0, {duration}, {f_s[0]}, {f_s[-1]})")
        
        # wavelet (placeholder - currently just showing same as spectrogram)
        self.im_wavelet.set_data(10*np.log10(Sxx + 1e-12))
        self.im_wavelet.set_extent((0, duration, 1, fs_val/2))
    
        # PSD ----------------------------------------------------------------
        nfft  = int(self.nfft_var.get())
        try:
            from scipy.signal import get_window
            cheb_db = self.cheb_var.get()
            win = get_window(('chebwin', cheb_db), nfft, fftbins=False)
        except:
            win = np.hamming(nfft)
        
        freqs = np.fft.rfftfreq(nfft, d=1/fs_val)
        
        for idx in range(16):
            if len(data) >= nfft:
                seg = data[-nfft:, idx] * win
                psd = 20*np.log10(np.abs(np.fft.rfft(seg)) + 1e-15)
                self.psd_lines[idx].set_data(freqs, psd)
        
                if self.maxhold_on.get():
                    mh = self.maxhold_data[idx]
                    if mh is None or len(mh) != len(psd):
                        self.maxhold_data[idx] = psd.copy()
                    else:
                        self.maxhold_data[idx] = np.maximum(mh, psd)
                    self.psd_max[idx].set_data(freqs, self.maxhold_data[idx])
                    self.psd_max[idx].set_visible(True)
                else:
                    self.psd_max[idx].set_visible(False)
        
        self.ax_psd.set_xlim(0, fs_val / 2)

    
        # -------- PROPER BLITTING WITH SINGLE FIGURE BACKGROUND -----------
        if self._bg_cache is not None:
            # Restore the entire figure background
            self.fig_canvas.restore_region(self._bg_cache)
            
            # Draw all animated artists
            self.ax_dt.draw_artist(self.dt_line)
            for ln in self.time_lines:
                self.ax_time.draw_artist(ln)
            self.ax_sg.draw_artist(self.im_specgram)
            self.ax_wav.draw_artist(self.im_wavelet)
            for ln in (*self.psd_lines, *self.psd_max):
                if ln.get_visible():
                    self.ax_psd.draw_artist(ln)
            
            # Single blit call for the entire figure
            self.fig_canvas.blit(self.fig.bbox)
            self.fig_canvas.flush_events()
        
        if DEBUG:
            print(f"[DURATION_TRACE] === ANIMATE PLOTS EXIT ===")
        self.after(16, self._animate_plots)






    # ── queue → console pump ──────────────────────────────────────────
    def _poll_queues(self):
        """Transfer any new text from worker queues into their Text widgets
        and reschedule itself every 50 ms."""
        self._drain(self.ser.rx_q if self.ser else None,  self.ser_console)
        self._drain(self.wifi_q,    self.wifi_console)
        if self.udp:                                    # board replies
            self._drain(self.udp.rx_q, self.wifi_console)
        self.after(50, self._poll_queues)


    @staticmethod
    def _drain(q, console):
        if not q:  # Safety check
            return
            
        console.configure(state="normal")

        # Remember if the view is already at the bottom BEFORE inserting
        at_bottom = console.yview()[1] == 1.0

        # Limit drain iterations to prevent GUI freeze
        max_items = 50
        items_processed = 0
        try:
            while items_processed < max_items:
                console.insert("end", q.get_nowait())
                items_processed += 1
        except queue.Empty:
            pass

        console.configure(state="disabled")

        # Only autoscroll if the user was already at the bottom
        if at_bottom:
            console.see("end")


    # ── shutdown ---------------------------------------------------------
    # ── shutdown / window-close handler ─────────────────────────────────
    def _on_close(self):
        """
        Called by the window manager (the "X" button).
        Sets stop flags, stops UDP thread if running, then destroys the GUI
        after 300 ms so background threads/processes can exit cleanly.
        """
        # tell timers & workers to stop
        self.stop_evt.set()
    
        # stop signal worker
        if self.sig:
            try:
                self.sig.stop()
            except Exception:
                pass
                
        # stop UDP manager (if it exists and is connected)
        if self.udp:
            try:
                self.udp.stop()
            except Exception:
                pass
                
        # stop serial manager
        if self.ser:
            try:
                self.ser.stop()
            except Exception:
                pass
    
        # destroy window after a short grace period
        self.after(300, self.destroy)



# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        App().mainloop()
    except KeyboardInterrupt:
        sys.exit(0)