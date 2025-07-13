"""main_gui.py  ·  DIY EEG / BCI Board Control
Python 3.12  ·  Tkinter + Matplotlib  ·  No external deps beyond PySerial & MPL
Run:  python main_gui.py

Revision
--------
• **PlotManager extraction**: All matplotlib complexity moved to plot_manager.py
• **Instant feedback**: figure redraw is scheduled just **40 ms** after the
  *last* <Configure> event, which feels immediate when you release the
  window edge.
• Debounce handler is appended (add="+") so Matplotlib's own resize logic
  remains active; we only throttle the expensive draw call.
• **Fixed blitting**: Proper implementation with animated artists and single figure background
• **Fixed duration issue**: X-axis now uses expected duration, not snapshot size
• **Fixed max-hold**: Manual toggle to work around Tkinter callback timing
• **Added wavelet/spectrogram controls**: Channel selector, power limits, window size
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

import tkinter as tk
from tkinter import ttk, scrolledtext
from serial_backend import SerialManager
from udp_backend import UDPManager
from signal_backend import SignalWorker, SigConfig
from plot_manager import PlotManager  # NEW: Import PlotManager

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
    RESIZE_DELAY_MS = 40  # draw 40 ms after last Configure → instant feel

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
    def _build_plot_column(self):
        """
        Five stacked plots (Δt · time · wavelet · spectrogram · PSD) + controls.
        Now uses PlotManager to handle all matplotlib complexity.
        """
        col = tk.Frame(self, bg=self.BG)
        col.grid(row=0, column=0, sticky="nsew")
        col.rowconfigure(0, weight=1)
        col.rowconfigure(1, weight=0)
        col.columnconfigure(0, weight=1)

        # Create PlotManager to handle all plotting
        self.plots = PlotManager(col, self.BG, debug=DEBUG)
        self.plots.get_widget().grid(row=0, column=0, sticky="nsew")
        self.plots.bind_resize_callback(self._queue_redraw)
    
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
                 showvalue=False)  # Don't show log value
        self.amp_scale.grid(row=r, column=1, columnspan=3, sticky="we", padx=2)
        self.amp_scale.set(np.log10(0.5))  # Explicitly set slider position
        
        # Add a label to show the voltage value
        self.amp_value_label = ttk.Label(ctrl, text="0.500 V")
        self.amp_value_label.grid(row=r, column=4, sticky="w", padx=2)
        
        self.amp_entry = ttk.Entry(ctrl, textvariable=self.amp_var, width=8)
        self.amp_entry.grid(row=r, column=5, sticky="we", padx=2)
        self.amp_entry.bind('<Return>', self._update_amp_from_entry)
        self.amp_entry.bind('<FocusOut>', self._update_amp_from_entry)
        r += 1
    
        # NFFT
        ttk.Label(ctrl, text="NFFT").grid(row=r, column=0, sticky="e")
        self.nfft_var = tk.IntVar(value=512)
        initial_max = int(self.fs_var.get()) * int(self.dur_var.get())
        self.nfft_sld = tk.Scale(
            ctrl, from_=32, to=initial_max, variable=self.nfft_var,
            orient="horizontal", showvalue=False,
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
        self.nfft_sld.set(512)  # Explicitly set initial position
        r += 1
    
        # Chebyshev attenuation
        ttk.Label(ctrl, text="Cheb atten (dB)").grid(row=r, column=0, sticky="e")
        self.cheb_var = tk.DoubleVar(value=80.0)
        self.cheb_scale = tk.Scale(ctrl, from_=40, to=120, orient="horizontal",
                  variable=self.cheb_var,
                  command=lambda v: (self.cheb_var.set(float(v)),
                                     self._sig_update(cheb_atten_db=float(v))),
                  showvalue=False)
        self.cheb_scale.grid(row=r, column=1, columnspan=3, sticky="we", padx=2)
        self.cheb_scale.set(80.0)  # Explicitly set slider position
        ttk.Entry(ctrl, textvariable=self.cheb_var, width=6)\
            .grid(row=r, column=4, sticky="we", padx=2)
        r += 1
    
        # PSD limits
        ttk.Label(ctrl, text="PSD min (dB)").grid(row=r, column=0, sticky="e")
        self.psd_lo = tk.DoubleVar(value=-150)
        self.psd_lo_scale = tk.Scale(ctrl, from_=-200, to=40, orient="horizontal",
                 variable=self.psd_lo, showvalue=False,
                 command=lambda v: (self.psd_lo.set(float(v)),
                                    self._enforce_psd(lo=True)))
        self.psd_lo_scale.grid(row=r, column=1, sticky="we", padx=2)
        self.psd_lo_scale.set(-150)  # Explicitly set slider position
        psd_lo_entry = ttk.Entry(ctrl, textvariable=self.psd_lo, width=6)
        psd_lo_entry.grid(row=r, column=2, sticky="we", padx=2)
        psd_lo_entry.bind('<Return>', lambda e: (self.psd_lo_scale.set(self.psd_lo.get()), self._enforce_psd(lo=True)))
        psd_lo_entry.bind('<FocusOut>', lambda e: (self.psd_lo_scale.set(self.psd_lo.get()), self._enforce_psd(lo=True)))
    
        ttk.Label(ctrl, text="PSD max (dB)").grid(row=r, column=3, sticky="e")
        self.psd_hi = tk.DoubleVar(value=-20)
        self.psd_hi_scale = tk.Scale(ctrl, from_=-200, to=40, orient="horizontal",
                 variable=self.psd_hi, showvalue=False,
                 command=lambda v: (self.psd_hi.set(float(v)),
                                    self._enforce_psd(lo=False)))
        self.psd_hi_scale.grid(row=r, column=4, sticky="we", padx=2)
        self.psd_hi_scale.set(-20)  # Explicitly set slider position
        ttk.Entry(ctrl, textvariable=self.psd_hi, width=6)\
            .grid(row=r, column=5, sticky="we", padx=2)
    
        self.maxhold_on = tk.BooleanVar(value=False)
        self.maxhold_cb = tk.Checkbutton(
            ctrl, text="Max-hold", 
            variable=self.maxhold_on,
            command=self._on_maxhold_toggle,
            bg=self.BG,
            fg=self.FG,
            selectcolor=self.BG,
            activebackground="#3E3E3E"
        )
        self.maxhold_cb.grid(row=r, column=6, sticky="w")
        ttk.Button(ctrl, text="Reset", command=self._reset_maxhold)\
            .grid(row=r, column=6, sticky="e", padx=4)
        r += 1
        
        # Channel visibility checkboxes
        ttk.Label(ctrl, text="Channels").grid(row=r, column=0, sticky="e")
        ch_frame = ttk.Frame(ctrl)
        ch_frame.grid(row=r, column=1, columnspan=6, sticky="w", padx=2)
        
        # Create 16 checkboxes in 8x2 grid
        self.channel_vars = []
        self.channel_cbs = []
        
        if DEBUG:
            print(f"[MAIN_GUI] Creating channel checkboxes...")
        
        for i in range(16):
            var = tk.BooleanVar(value=True)
            self.channel_vars.append(var)
        
            def make_callback(index):
                return lambda: self._toggle_channel(index)
        
            cb = tk.Checkbutton(
                ch_frame,
                text=f"{i}",
                command=make_callback(i),
                width=3,
                bg=self.BG,
                fg=self.FG,
                selectcolor=self.BG,
                activebackground="#3E3E3E"
            )
            cb.grid(row=i // 8, column=i % 8, padx=1, pady=1)
            self.channel_cbs.append(cb)
        
            if DEBUG:
                print(f"[MAIN_GUI] Created checkbox for channel {i}, var={var.get()}")
            
        # Add All/None buttons for convenience
        btn_frame = ttk.Frame(ch_frame)
        btn_frame.grid(row=0, column=8, rowspan=2, padx=(10, 0))
        ttk.Button(btn_frame, text="All", width=5,
                   command=self._select_all_channels).grid(row=0, column=0, pady=1)
        ttk.Button(btn_frame, text="None", width=5,
                   command=self._select_no_channels).grid(row=1, column=0, pady=1)
        r += 1

        # NEW: Wavelet/Spectrogram channel selector
        ttk.Label(ctrl, text="Wav/Spec Ch").grid(row=r, column=0, sticky="e")
        self.wavspec_ch_var = tk.IntVar(value=0)
        self.wavspec_ch_cb = ttk.Combobox(
            ctrl, 
            textvariable=self.wavspec_ch_var,
            values=list(range(16)),
            state="readonly",
            width=4
        )
        self.wavspec_ch_cb.grid(row=r, column=1, sticky="w", padx=2)
        self.wavspec_ch_cb.current(0)
        self.wavspec_ch_cb.bind('<<ComboboxSelected>>', 
                                lambda e: self.plots.set_wavspec_channel(self.wavspec_ch_var.get()))

        # NEW: Spectrogram window size
        ttk.Label(ctrl, text="Spec Win").grid(row=r, column=2, sticky="e")
        self.spec_win_var = tk.IntVar(value=256)
        initial_max_win = int(self.fs_var.get()) * int(self.dur_var.get()) // 2
        self.spec_win_sld = tk.Scale(
            ctrl, from_=32, to=initial_max_win, variable=self.spec_win_var,
            orient="horizontal", showvalue=False,
            command=lambda v: (self.spec_win_var.set(int(float(v))),
                               self.spec_win_label.config(text=str(int(float(v))))))
        self.spec_win_sld.grid(row=r, column=3, columnspan=2, sticky="we", padx=2)
        self.spec_win_sld.set(256)  # Explicitly set initial position
        self.spec_win_label = ttk.Label(ctrl, text="256")
        self.spec_win_label.grid(row=r, column=5, sticky="w", padx=2)
        r += 1

        # NEW: Wavelet power limits
        ttk.Label(ctrl, text="Wav min (dB)").grid(row=r, column=0, sticky="e")
        self.wav_lo = tk.DoubleVar(value=-120)
        self.wav_lo_scale = tk.Scale(ctrl, from_=-160, to=20, orient="horizontal",
                 variable=self.wav_lo, showvalue=False,
                 command=lambda v: (self.wav_lo.set(float(v)),
                                    self._enforce_wav_limits(lo=True)))
        self.wav_lo_scale.grid(row=r, column=1, sticky="we", padx=2)
        self.wav_lo_scale.set(-120)  # Explicitly set slider position
        ttk.Entry(ctrl, textvariable=self.wav_lo, width=6)\
            .grid(row=r, column=2, sticky="we", padx=2)

        ttk.Label(ctrl, text="Wav max (dB)").grid(row=r, column=3, sticky="e")
        self.wav_hi = tk.DoubleVar(value=-30)
        self.wav_hi_scale = tk.Scale(ctrl, from_=-160, to=20, orient="horizontal",
                 variable=self.wav_hi, showvalue=False,
                 command=lambda v: (self.wav_hi.set(float(v)),
                                    self._enforce_wav_limits(lo=False)))
        self.wav_hi_scale.grid(row=r, column=4, sticky="we", padx=2)
        self.wav_hi_scale.set(-30)  # Explicitly set slider position
        ttk.Entry(ctrl, textvariable=self.wav_hi, width=6)\
            .grid(row=r, column=5, sticky="we", padx=2)
        r += 1

        # NEW: Spectrogram power limits
        ttk.Label(ctrl, text="Spec min (dB)").grid(row=r, column=0, sticky="e")
        self.spec_lo = tk.DoubleVar(value=-120)
        self.spec_lo_scale = tk.Scale(ctrl, from_=-160, to=20, orient="horizontal",
                 variable=self.spec_lo, showvalue=False,
                 command=lambda v: (self.spec_lo.set(float(v)),
                                    self._enforce_spec_limits(lo=True)))
        self.spec_lo_scale.grid(row=r, column=1, sticky="we", padx=2)
        self.spec_lo_scale.set(-120)  # Explicitly set slider position
        ttk.Entry(ctrl, textvariable=self.spec_lo, width=6)\
            .grid(row=r, column=2, sticky="we", padx=2)

        ttk.Label(ctrl, text="Spec max (dB)").grid(row=r, column=3, sticky="e")
        self.spec_hi = tk.DoubleVar(value=-30)
        self.spec_hi_scale = tk.Scale(ctrl, from_=-160, to=20, orient="horizontal",
                 variable=self.spec_hi, showvalue=False,
                 command=lambda v: (self.spec_hi.set(float(v)),
                                    self._enforce_spec_limits(lo=False)))
        self.spec_hi_scale.grid(row=r, column=4, sticky="we", padx=2)
        self.spec_hi_scale.set(-30)  # Explicitly set slider position
        ttk.Entry(ctrl, textvariable=self.spec_hi, width=6)\
            .grid(row=r, column=5, sticky="we", padx=2)

        # Apply initial plot limits to PlotManager
        self.plots.set_psd_limits(self.psd_lo.get(), self.psd_hi.get())
        self.plots.set_wavelet_limits(self.wav_lo.get(), self.wav_hi.get())
        self.plots.set_specgram_limits(self.spec_lo.get(), self.spec_hi.get())
        self.plots.set_amplitude_limits(self.amp_var.get())
        # Update initial amplitude label
        self.amp_value_label.config(text="0.500 V")

    def _on_maxhold_toggle(self):
        """Handle max-hold toggle using PlotManager."""
        # Manual toggle to work around Tkinter callback timing
        current = self.maxhold_on.get()
        new_val = not current
        self.maxhold_on.set(new_val)
        
        if DEBUG:
            print(f"[MAIN_GUI] Max-hold manually toggled to: {new_val}")
        self.plots.set_maxhold(new_val)

    # live SigConfig update and safety-clamped NFFT
    def _sig_update(self, **kwargs):
        """Sync SigConfig with worker, and clamp NFFT ≤ buffer length."""
        if DEBUG:
            print(f"[MAIN_GUI] _sig_update called with: {kwargs}")
        
        if hasattr(self, "sig") and self.sig:
            self.sig.update_cfg(**kwargs)
        if hasattr(self, "sig_cfg"):
            self.sig_cfg.__dict__.update(kwargs)

        # Handle NFFT clamping
        if 'fft_pts' in kwargs:
            total = self.sig_cfg.sample_rate * self.sig_cfg.buf_secs
            if self.nfft_var.get() > total:
                self.nfft_var.set(total)
            if hasattr(self, "nfft_sld"):
                self.nfft_sld.configure(to=total)
                
    # update amplitude limits (symmetric ±)
    def _update_amp_from_log(self, log_val):
        """Update amplitude from log scale slider using PlotManager."""
        linear_val = 10 ** float(log_val)
        self.amp_var.set(linear_val)
        # Update the voltage display label
        if linear_val >= 0.001:
            self.amp_value_label.config(text=f"{linear_val:.3f} V")
        else:
            self.amp_value_label.config(text=f"{linear_val:.3e} V")
        self.plots.set_amplitude_limits(linear_val)
            
    def _update_amp_from_entry(self, event=None):
        """Update log slider when entry is changed using PlotManager."""
        try:
            val = float(self.amp_var.get())
            val = max(1e-6, min(5.0, val))
            self.amp_var.set(val)
            self.amp_log_var.set(np.log10(val))
            # Update the voltage display label
            if val >= 0.001:
                self.amp_value_label.config(text=f"{val:.3f} V")
            else:
                self.amp_value_label.config(text=f"{val:.3e} V")
            self.plots.set_amplitude_limits(val)
        except ValueError:
            pass

    # ── apply Fs / Record settings --------------------------------------
    def _apply_buf_settings(self):
        if DEBUG:
            print(f"[MAIN_GUI] === APPLY BUTTON CLICKED ===")
        
        # Read directly from Entry widget instead of StringVar
        dur_entry_text = self.dur_entry.get()
        fs_entry_text = self.fs_var.get()  # fs still works with StringVar
        
        if DEBUG:
            print(f"[MAIN_GUI] Raw values: fs='{fs_entry_text}', dur='{dur_entry_text}'")
        
        try:
            new_fs  = int(float(fs_entry_text))
            new_dur = int(float(dur_entry_text))
            if new_fs <= 0 or new_dur <= 0:
                raise ValueError
        except ValueError:
            if DEBUG:
                print(f"[MAIN_GUI] Invalid values, returning")
            return
    
        if DEBUG:
            print(f"[MAIN_GUI] Validation passed - fs={new_fs}, dur={new_dur}")
        
        # Update the StringVar to match what user actually entered
        self.dur_var.set(str(new_dur))
        
        # 1 ─ Pause data reception and update buffer without killing worker
        if self.sig:
            if DEBUG:
                print(f"[MAIN_GUI] Pausing signal worker for buffer update")
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
                print(f"[MAIN_GUI] Updating signal configuration")
            self.sig_cfg.sample_rate = new_fs
            self.sig_cfg.buf_secs = new_dur
            self.sig.update_cfg(sample_rate=new_fs, buf_secs=new_dur)
            
            # Clear the buffer and resize
            if DEBUG:
                print(f"[MAIN_GUI] Resizing buffer")
            self.sig._buf = np.zeros((new_fs * new_dur, 16), dtype=np.float32)
            self.sig._ptr = 0
            
            # Resume reception
            self.sig.pause_reception = False
            if DEBUG:
                print(f"[MAIN_GUI] Resumed signal reception")
        else:
            # No existing worker, create new one
            if DEBUG:
                print(f"[MAIN_GUI] Creating new signal worker")
            self.sig_cfg = SigConfig(sample_rate=new_fs,
                                     buf_secs=new_dur,
                                     n_ch=16)
            self.sig = SignalWorker(self.sig_cfg,
                                    data_port=int(self.data_port_var.get()))
            self.sig.start()
    
        # 2 ─ Update plot manager with new buffer size
        self.plots.resize_buffer(new_fs, new_dur)
        
        # Update NFFT slider maximum based on new buffer size
        total_samples = new_fs * new_dur
        self.nfft_sld.configure(to=total_samples)
        if self.nfft_var.get() > total_samples:
            self.nfft_var.set(total_samples)
            self.nfft_sld.set(total_samples)  # Update slider position
            self.nfft_label.config(text=str(total_samples))
        else:
            self.nfft_label.config(text=str(self.nfft_var.get()))
        
        # NEW: Update spectrogram window size slider maximum
        spec_max_win = total_samples // 2
        self.spec_win_sld.configure(to=spec_max_win)
        if self.spec_win_var.get() > spec_max_win:
            self.spec_win_var.set(spec_max_win)
            self.spec_win_sld.set(spec_max_win)  # Update slider position
            self.spec_win_label.config(text=str(spec_max_win))
        
        # Update the status in console
        self.ser_console.configure(state="normal")
        self.ser_console.insert("end", f"[PC] Buffer updated: {new_fs} Hz, {new_dur} s ({total_samples} samples)\n")
        self.ser_console.configure(state="disabled")
        self.ser_console.see("end")
        
        # Apply current NFFT clamp and cheb_atten immediately
        self._sig_update(fft_pts=self.nfft_var.get(),
                         cheb_atten_db=self.cheb_var.get())
        
        if DEBUG:
            print(f"[MAIN_GUI] === APPLY BUTTON COMPLETE ===")
    
    def _enforce_psd(self, lo=True):
        if lo and self.psd_lo.get() >= self.psd_hi.get():
            self.psd_lo.set(self.psd_hi.get() - 1)
            self.psd_lo_scale.set(self.psd_lo.get())  # Update slider
        elif not lo and self.psd_hi.get() <= self.psd_lo.get():
            self.psd_hi.set(self.psd_lo.get() + 1)
            self.psd_hi_scale.set(self.psd_hi.get())  # Update slider
    
        # Apply the new limits using PlotManager
        if hasattr(self, "plots"):
            new_lo, new_hi = self.psd_lo.get(), self.psd_hi.get()
            self.plots.set_psd_limits(new_lo, new_hi)
    
    def _enforce_wav_limits(self, lo=True):
        """Enforce wavelet power limits."""
        if lo and self.wav_lo.get() >= self.wav_hi.get():
            self.wav_lo.set(self.wav_hi.get() - 1)
            self.wav_lo_scale.set(self.wav_lo.get())  # Update slider
        elif not lo and self.wav_hi.get() <= self.wav_lo.get():
            self.wav_hi.set(self.wav_lo.get() + 1)
            self.wav_hi_scale.set(self.wav_hi.get())  # Update slider
        
        if hasattr(self, "plots"):
            self.plots.set_wavelet_limits(self.wav_lo.get(), self.wav_hi.get())

    def _enforce_spec_limits(self, lo=True):
        """Enforce spectrogram power limits."""
        if lo and self.spec_lo.get() >= self.spec_hi.get():
            self.spec_lo.set(self.spec_hi.get() - 1)
            self.spec_lo_scale.set(self.spec_lo.get())  # Update slider
        elif not lo and self.spec_hi.get() <= self.spec_lo.get():
            self.spec_hi.set(self.spec_lo.get() + 1)
            self.spec_hi_scale.set(self.spec_hi.get())  # Update slider
        
        if hasattr(self, "plots"):
            self.plots.set_specgram_limits(self.spec_lo.get(), self.spec_hi.get())
    
    def _reset_maxhold(self):
        """Reset max-hold using PlotManager."""
        self.plots.reset_maxhold()
        
    def _toggle_channel(self, channel: int):
        """Force-toggle the checkbox state manually and update plots."""
        current = self.channel_vars[channel].get()
        new_val = not current
        self.channel_vars[channel].set(new_val)
    
        if DEBUG:
            print(f"[MAIN_GUI] Channel {channel} manually toggled to: {new_val}")
        self.plots.set_channel_visibility(channel, new_val)
        
    def _select_all_channels(self):
        """Turn ON all channels immediately."""
        for var in self.channel_vars:
            var.set(True)
        self.plots.set_all_channels_visibility([True] * 16)
    
    def _select_no_channels(self):
        """Turn OFF all channels immediately."""
        for var in self.channel_vars:
            var.set(False)
        self.plots.set_all_channels_visibility([False] * 16)

    # ── debounced draw ---------------------------------------------------
    def _queue_redraw(self, _):
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(self.RESIZE_DELAY_MS, self._do_redraw)

    def _do_redraw(self):
        self.plots.draw_full()
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

    # ── animate plots ----------------------------------------------------
    def _animate_plots(self):
        """
        Animation loop that updates plots every 16ms using PlotManager.
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
            print(f"[MAIN_GUI] === ANIMATE PLOTS ===")
        
        # Update plots using PlotManager
        data = snap["data"]  # (N,16)
        timestamps = snap.get("time", None)  # Get timestamps if available
        fs_val = self.sig_cfg.sample_rate
        duration = self.sig_cfg.buf_secs
        
        # Pass current settings to PlotManager
        self.plots.update_snapshot(
            data=data,
            fs=fs_val,
            duration=duration,
            timestamps=timestamps,
            nfft=self.nfft_var.get(),
            cheb_db=self.cheb_var.get(),
            spec_nperseg=self.spec_win_var.get()
        )
        
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