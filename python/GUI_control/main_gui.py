"""main_gui.py  ·  DIY EEG / BCI Board Control - NERV Interface
Python 3.12  ·  Tkinter + Matplotlib  ·  No external deps beyond PySerial & MPL
Run:  python main_gui.py

Revision - Evangelion/NERV Style
--------------------------------
• **Color scheme**: Black backgrounds, amber/yellow accents, red alerts
• **Typography**: Monospace all-caps for that technical NERV aesthetic  
• **Buttons**: Black with amber borders, red glow on hover, orange on press
• **Sliders**: Minimalist with amber track and handle
• **Overall**: Technical/military interface inspired by Evangelion

FIXED: Universal Python/Tkinter compatibility
- Entry widgets: Smart type-aware synchronization
  * StringVar entries: Fixed to prevent doubles in Python 3.11
  * DoubleVar/IntVar entries: Left untouched to prevent TclError
- Initialization order: Fixed sig_cfg not existing during GUI setup  
- Slider initialization: Uses hardcoded defaults instead of StringVar values
- No more "can't assign non-numeric value to scale variable" errors
"""

# ─────────────────────────── DEBUG SWITCH ─────────────────────────
# Set to 1 to enable debug messages, 0 to disable
DEBUG = 0
# ──────────────────────────────────────────────────────────────────

import sys

# ─────────────────────────── PYTHON VERSION CHECK ─────────────────────
if sys.version_info < (3, 11, 5):
    print(f"ERROR: Python 3.11.5 or higher required (you have {sys.version})")
    print("Please upgrade Python from https://python.org")
    sys.exit(1)
# ──────────────────────────────────────────────────────────────────────

# ─────────────────────────── DEPENDENCY CHECK ─────────────────────────
try:
    import numpy
    import scipy
    import matplotlib
except ImportError as e:
    print(f"ERROR: Missing required dependency - {e}")
    print("Please run: python install_dependencies.py")
    print("Or manually install: pip install numpy scipy matplotlib")
    sys.exit(1)
# ──────────────────────────────────────────────────────────────────────

import queue
import threading
import time
import random
import socket
import numpy as np

import tkinter as tk
from tkinter import ttk, scrolledtext, font
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
    # NERV/Evangelion Color Scheme
    BG_PRIMARY = "#000000"      # Pure black background
    BG_SECONDARY = "#0A0A0A"    # Slightly lighter black for panels
    FG_PRIMARY = "#FFB000"      # Amber/yellow for primary text
    FG_SECONDARY = "#FF6B00"    # Orange for secondary elements
    FG_ACTIVE = "#FF0000"       # Red for active/alert states
    FG_SUCCESS = "#00FF00"      # Green for success/active
    BORDER_COLOR = "#FFB000"    # Amber borders
    BORDER_ACTIVE = "#FF6B00"   # Orange borders when active
    
    # Console colors
    CONSOLE_BG = "#000000"
    SERIAL_FG = "#00FF00"       # Green terminal style
    WIFI_FG = "#FFB000"         # Amber for WiFi console
    
    RESIZE_DELAY_MS = 40  # draw 40 ms after last Configure → instant feel

    def __init__(self):
        super().__init__()
        
        self.udp = None
        self.sig = None  # Initialize as None, create after GUI vars exist
        
        self.title("NERV EEG/BCI INTERFACE - SYNCHRONIZATION MONITOR")
        self.geometry("1600x1000")      # ← initial size
        self.minsize(900, 600)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.configure(bg=self.BG_PRIMARY)
        
        # Set up NERV-style fonts
        self.setup_fonts()
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
        self.ser_console  = self._build_io_block(1, "SERIAL INTERFACE", self._serial_controls)
        self.wifi_console = self._build_io_block(2, "NETWORK CONTROL", self._wifi_controls)
        
        # ------- Signal backend (now safe because fs_var & dur_var exist) --------
        self.sig_cfg = SigConfig(sample_rate=int(self.fs_var.get()),
                                 buf_secs   =int(self.dur_var.get()),
                                 n_ch       =16)
        self.sig     = SignalWorker(self.sig_cfg,
                                    data_port=int(self.data_port_var.get()))
        self.sig.start()
        
        # ── console colour scheme ───────────────────────────────────────
        self.ser_console .configure(bg=self.CONSOLE_BG, fg=self.SERIAL_FG, 
                                   insertbackground=self.SERIAL_FG,
                                   font=self.mono_font)
        self.wifi_console.configure(bg=self.CONSOLE_BG, fg=self.WIFI_FG, 
                                   insertbackground=self.WIFI_FG,
                                   font=self.mono_font)

        # timers
        self.after(16, self._animate_plots)   # 60 fps animation
        self.after(50, self._poll_queues)
        
    def setup_fonts(self):
        """Set up NERV-style monospace fonts"""
        # Try to find a good monospace font
        available_fonts = font.families()
        mono_fonts = ['Consolas', 'Courier New', 'Monaco', 'DejaVu Sans Mono', 'Liberation Mono']
        
        selected_font = 'TkFixedFont'  # Default
        for f in mono_fonts:
            if f in available_fonts:
                selected_font = f
                break
        
        self.mono_font = font.Font(family=selected_font, size=10, weight='normal')
        self.mono_font_bold = font.Font(family=selected_font, size=10, weight='bold')
        self.label_font = font.Font(family=selected_font, size=9, weight='normal')

    # ── style ───────────────────────────────────────────────
    def _apply_style(self):
        """Apply NERV/Evangelion-inspired styling"""
        s = ttk.Style(self)
        s.theme_use("clam")
        
        # Configure base elements with NERV colors
        s.configure("TFrame", background=self.BG_PRIMARY, borderwidth=0)
        s.configure("TLabel", background=self.BG_PRIMARY, foreground=self.FG_PRIMARY,
                   font=self.label_font)
        s.configure("TLabelframe", background=self.BG_PRIMARY, foreground=self.FG_PRIMARY,
                   bordercolor=self.BORDER_COLOR, borderwidth=1, relief="solid",
                   font=self.mono_font_bold)
        s.configure("TLabelframe.Label", background=self.BG_PRIMARY, 
                   foreground=self.FG_PRIMARY, font=self.mono_font_bold)
        
        # NERV-style buttons
        s.configure("TButton", 
                   background=self.BG_PRIMARY,
                   foreground=self.FG_PRIMARY,
                   bordercolor=self.BORDER_COLOR,
                   lightcolor=self.BG_PRIMARY,
                   darkcolor=self.BG_PRIMARY,
                   borderwidth=2,
                   focuscolor='none',
                   font=self.mono_font)
        
        s.map("TButton",
              background=[("active", self.BG_PRIMARY), ("pressed", self.BG_PRIMARY)],
              foreground=[("active", self.FG_SECONDARY), ("pressed", self.FG_ACTIVE)],
              bordercolor=[("active", self.BORDER_ACTIVE), ("pressed", self.FG_ACTIVE)])
        
        # Entry fields
        s.configure("TEntry", 
                   fieldbackground=self.BG_PRIMARY,
                   background=self.BG_PRIMARY,
                   foreground=self.FG_PRIMARY,
                   bordercolor=self.BORDER_COLOR,
                   insertcolor=self.FG_PRIMARY,
                   font=self.mono_font)
        
        # Combobox
        s.configure("TCombobox",
                   fieldbackground=self.BG_PRIMARY,
                   background=self.BG_PRIMARY,
                   foreground=self.FG_PRIMARY,
                   bordercolor=self.BORDER_COLOR,
                   arrowcolor=self.FG_PRIMARY,
                   font=self.mono_font)
        
        s.map("TCombobox", 
              fieldbackground=[("readonly", self.BG_PRIMARY)],
              bordercolor=[("focus", self.BORDER_ACTIVE)])
        
        # Scrollbar
        s.configure("TScrollbar", 
                   background=self.BG_PRIMARY,
                   bordercolor=self.BORDER_COLOR,
                   arrowcolor=self.FG_PRIMARY,
                   troughcolor=self.BG_SECONDARY)
        
        # Special button styles
        s.configure("Active.TButton",
                   background=self.BG_PRIMARY,
                   foreground=self.FG_SUCCESS,
                   bordercolor=self.FG_SUCCESS)
        
        s.map("Active.TButton",
              foreground=[("active", self.FG_SUCCESS), ("pressed", self.FG_SUCCESS)],
              bordercolor=[("active", self.FG_SUCCESS), ("pressed", self.FG_SUCCESS)])
        
        s.configure("Alert.TButton",
                   background=self.BG_PRIMARY,
                   foreground=self.FG_ACTIVE,
                   bordercolor=self.FG_ACTIVE)
        
        s.map("Alert.TButton",
              foreground=[("active", self.FG_ACTIVE), ("pressed", "#FF3333")],
              bordercolor=[("active", self.FG_ACTIVE), ("pressed", "#FF3333")])

    # ── plot column + signal-controls ───────────────────────────────────────
    def _build_plot_column(self):
        """
        Five stacked plots (Δt · time · wavelet · spectrogram · PSD) + controls.
        Now uses PlotManager to handle all matplotlib complexity.
        """
        col = tk.Frame(self, bg=self.BG_PRIMARY)
        col.grid(row=0, column=0, sticky="nsew")
        col.rowconfigure(0, weight=1)
        col.rowconfigure(1, weight=0)
        col.columnconfigure(0, weight=1)

        # Create PlotManager to handle all plotting (with NERV style)
        self.plots = PlotManager(col, self.BG_PRIMARY, debug=DEBUG, style="evangelion")
        self.plots.get_widget().grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        self.plots.bind_resize_callback(self._queue_redraw)
    
        # ────────── control panel ─────────────────────────────────────
        ctrl = ttk.LabelFrame(col, text="SYNCHRONIZATION PARAMETERS")
        ctrl.grid(row=1, column=0, sticky="ew", padx=4, pady=(4, 6))
        for c in range(7):
            ctrl.columnconfigure(c, weight=1)
    
        r = 0
        # Fs & Record
        self._create_label(ctrl, "SAMPLE RATE", r, 0)
        self.fs_var = tk.StringVar(value="250")
        self.fs_entry = self._create_entry(ctrl, self.fs_var, r, 1, width=8)
        self._create_label(ctrl, "HZ", r, 2, sticky="w")
    
        self._create_label(ctrl, "BUFFER", r, 3)
        self.dur_var = tk.StringVar(value="4")
        self.dur_entry = self._create_entry(ctrl, self.dur_var, r, 4, width=6)
        self._create_label(ctrl, "SEC", r, 5, sticky="w")
        
        ttk.Button(ctrl, text="APPLY", command=self._apply_buf_settings).grid(row=r, column=6, padx=4)
        r += 1
    
        # amplitude slider
        self._create_label(ctrl, "AMPLITUDE", r, 0)
        self.amp_var = tk.DoubleVar(value=0.5)
        
        # Create log scale slider
        self.amp_log_var = tk.DoubleVar(value=np.log10(0.5))
        self.amp_scale = self._create_nerv_scale(
            ctrl, from_=0.7, to=-6, resolution=0.01,
            orient="horizontal", variable=self.amp_log_var,
            command=self._update_amp_from_log
        )
        self.amp_scale.grid(row=r, column=1, columnspan=3, sticky="we", padx=2)
        self.amp_scale.set(np.log10(0.5))
        
        # Voltage display
        self.amp_value_label = self._create_label(ctrl, "0.500 V", r, 4, sticky="w")
        
        self.amp_entry = self._create_entry(ctrl, self.amp_var, r, 5, width=8)
        self.amp_entry.bind('<Return>', self._update_amp_from_entry)
        self.amp_entry.bind('<FocusOut>', self._update_amp_from_entry)
        r += 1
    
        # NFFT
        self._create_label(ctrl, "FFT POINTS", r, 0)
        self.nfft_var = tk.IntVar(value=512)
        # Use default values directly instead of trying to get from StringVars
        # which might not be fully initialized yet
        initial_fs = 250  # Default sample rate
        initial_dur = 4   # Default duration
        initial_max = initial_fs * initial_dur
        self.nfft_sld = self._create_nerv_scale(
            ctrl, from_=32, to=initial_max, variable=self.nfft_var,
            orient="horizontal",
            command=lambda v: (self.nfft_var.set(int(float(v))),
                               self._sig_update(fft_pts=int(float(v)))))
        self.nfft_sld.grid(row=r, column=1, columnspan=3, sticky="we", padx=2)
        self.nfft_label = self._create_label(ctrl, "512", r, 4, sticky="w")
        
        # Update label when slider moves
        def update_nfft_label(v):
            val = int(float(v))
            self.nfft_var.set(val)
            self.nfft_label.config(text=str(val))
            # Only call _sig_update if sig_cfg exists
            if hasattr(self, 'sig_cfg'):
                self._sig_update(fft_pts=val)
        self.nfft_sld.config(command=update_nfft_label)
        self.nfft_sld.set(512)
        r += 1
    
        # Chebyshev attenuation
        self._create_label(ctrl, "CHEB ATTEN", r, 0)
        self.cheb_var = tk.DoubleVar(value=80.0)
        self.cheb_scale = self._create_nerv_scale(
            ctrl, from_=40, to=120, orient="horizontal",
            variable=self.cheb_var,
            command=lambda v: (self.cheb_var.set(float(v)),
                               self._sig_update(cheb_atten_db=float(v)))
        )
        self.cheb_scale.grid(row=r, column=1, columnspan=3, sticky="we", padx=2)
        self.cheb_scale.set(80.0)
        self.cheb_entry = self._create_entry(ctrl, self.cheb_var, r, 4, width=6)
        self._create_label(ctrl, "DB", r, 5, sticky="w")
        r += 1
    
        # PSD limits
        self._create_label(ctrl, "PSD MIN", r, 0)
        self.psd_lo = tk.DoubleVar(value=-150)
        self.psd_lo_scale = self._create_nerv_scale(
            ctrl, from_=-200, to=40, orient="horizontal",
            variable=self.psd_lo,
            command=lambda v: (self.psd_lo.set(float(v)),
                               self._enforce_psd(lo=True))
        )
        self.psd_lo_scale.grid(row=r, column=1, sticky="we", padx=2)
        self.psd_lo_scale.set(-150)
        psd_lo_entry = self._create_entry(ctrl, self.psd_lo, r, 2, width=6)
        psd_lo_entry.bind('<Return>', lambda e: (self.psd_lo_scale.set(self.psd_lo.get()), self._enforce_psd(lo=True)))
        psd_lo_entry.bind('<FocusOut>', lambda e: (self.psd_lo_scale.set(self.psd_lo.get()), self._enforce_psd(lo=True)))
    
        self._create_label(ctrl, "PSD MAX", r, 3)
        self.psd_hi = tk.DoubleVar(value=-20)
        self.psd_hi_scale = self._create_nerv_scale(
            ctrl, from_=-200, to=40, orient="horizontal",
            variable=self.psd_hi,
            command=lambda v: (self.psd_hi.set(float(v)),
                               self._enforce_psd(lo=False))
        )
        self.psd_hi_scale.grid(row=r, column=4, sticky="we", padx=2)
        self.psd_hi_scale.set(-20)
        self._create_entry(ctrl, self.psd_hi, r, 5, width=6)
    
        self.maxhold_on = tk.BooleanVar(value=False)
        self.maxhold_cb = self._create_nerv_checkbutton(
            ctrl, text="MAX-HOLD", 
            variable=self.maxhold_on,
            command=self._on_maxhold_toggle
        )
        self.maxhold_cb.grid(row=r, column=6, sticky="w")
        ttk.Button(ctrl, text="RESET", command=self._reset_maxhold,
                  style="Alert.TButton").grid(row=r, column=6, sticky="e", padx=4)
        r += 1
        
        # Channel visibility checkboxes
        self._create_label(ctrl, "CHANNELS", r, 0)
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
        
            cb = self._create_nerv_checkbutton(
                ch_frame,
                text=f"{i:02d}",
                command=make_callback(i),
                width=3
            )
            cb.grid(row=i // 8, column=i % 8, padx=1, pady=1)
            self.channel_cbs.append(cb)
        
            if DEBUG:
                print(f"[MAIN_GUI] Created checkbox for channel {i}, var={var.get()}")
            
        # Add All/None buttons
        btn_frame = ttk.Frame(ch_frame)
        btn_frame.grid(row=0, column=8, rowspan=2, padx=(10, 0))
        ttk.Button(btn_frame, text="ALL", width=5,
                   command=self._select_all_channels,
                   style="Active.TButton").grid(row=0, column=0, pady=1)
        ttk.Button(btn_frame, text="NONE", width=5,
                   command=self._select_no_channels,
                   style="Alert.TButton").grid(row=1, column=0, pady=1)
        r += 1

        # Wavelet/Spectrogram channel selector
        self._create_label(ctrl, "WAV/SPEC CH", r, 0)
        self.wavspec_ch_var = tk.IntVar(value=0)
        self.wavspec_ch_cb = ttk.Combobox(
            ctrl, 
            textvariable=self.wavspec_ch_var,
            values=[f"{i:02d}" for i in range(16)],
            state="readonly",
            width=4
        )
        self.wavspec_ch_cb.grid(row=r, column=1, sticky="w", padx=2)
        self.wavspec_ch_cb.current(0)
        self.wavspec_ch_cb.bind('<<ComboboxSelected>>', 
                                lambda e: self.plots.set_wavspec_channel(int(self.wavspec_ch_cb.get())))

        # Spectrogram window size
        self._create_label(ctrl, "SPEC WIN", r, 2)
        self.spec_win_var = tk.IntVar(value=256)
        # Use default values directly instead of trying to get from StringVars
        initial_max_win = initial_fs * initial_dur // 2  # Using same defaults as NFFT
        self.spec_win_sld = self._create_nerv_scale(
            ctrl, from_=32, to=initial_max_win, variable=self.spec_win_var,
            orient="horizontal",
            command=lambda v: (self.spec_win_var.set(int(float(v))),
                               self.spec_win_label.config(text=str(int(float(v)))))
        )
        self.spec_win_sld.grid(row=r, column=3, columnspan=2, sticky="we", padx=2)
        self.spec_win_sld.set(256)
        self.spec_win_label = self._create_label(ctrl, "256", r, 5, sticky="w")
        r += 1

        # Wavelet power limits
        self._create_label(ctrl, "WAV MIN", r, 0)
        self.wav_lo = tk.DoubleVar(value=-120)
        self.wav_lo_scale = self._create_nerv_scale(
            ctrl, from_=-200, to=20, orient="horizontal",
            variable=self.wav_lo,
            command=lambda v: (self.wav_lo.set(float(v)),
                               self._enforce_wav_limits(lo=True))
        )
        self.wav_lo_scale.grid(row=r, column=1, sticky="we", padx=2)
        self.wav_lo_scale.set(-120)
        self._create_entry(ctrl, self.wav_lo, r, 2, width=6)

        self._create_label(ctrl, "WAV MAX", r, 3)
        self.wav_hi = tk.DoubleVar(value=-30)
        self.wav_hi_scale = self._create_nerv_scale(
            ctrl, from_=-200, to=20, orient="horizontal",
            variable=self.wav_hi,
            command=lambda v: (self.wav_hi.set(float(v)),
                               self._enforce_wav_limits(lo=False))
        )
        self.wav_hi_scale.grid(row=r, column=4, sticky="we", padx=2)
        self.wav_hi_scale.set(-30)
        self._create_entry(ctrl, self.wav_hi, r, 5, width=6)
        r += 1

        # Spectrogram power limits
        self._create_label(ctrl, "SPEC MIN", r, 0)
        self.spec_lo = tk.DoubleVar(value=-120)
        self.spec_lo_scale = self._create_nerv_scale(
            ctrl, from_=-200, to=20, orient="horizontal",
            variable=self.spec_lo,
            command=lambda v: (self.spec_lo.set(float(v)),
                               self._enforce_spec_limits(lo=True))
        )
        self.spec_lo_scale.grid(row=r, column=1, sticky="we", padx=2)
        self.spec_lo_scale.set(-120)
        self._create_entry(ctrl, self.spec_lo, r, 2, width=6)

        self._create_label(ctrl, "SPEC MAX", r, 3)
        self.spec_hi = tk.DoubleVar(value=-30)
        self.spec_hi_scale = self._create_nerv_scale(
            ctrl, from_=-200, to=20, orient="horizontal",
            variable=self.spec_hi,
            command=lambda v: (self.spec_hi.set(float(v)),
                               self._enforce_spec_limits(lo=False))
        )
        self.spec_hi_scale.grid(row=r, column=4, sticky="we", padx=2)
        self.spec_hi_scale.set(-30)
        self._create_entry(ctrl, self.spec_hi, r, 5, width=6)

        # Apply initial plot limits to PlotManager
        self.plots.set_psd_limits(self.psd_lo.get(), self.psd_hi.get())
        self.plots.set_wavelet_limits(self.wav_lo.get(), self.wav_hi.get())
        self.plots.set_specgram_limits(self.spec_lo.get(), self.spec_hi.get())
        self.plots.set_amplitude_limits(self.amp_var.get())
        self.amp_value_label.config(text="0.500 V")
        # Use the same default values we used for NFFT initialization
        self.plots.resize_buffer(initial_fs, initial_dur)

    # Helper methods for NERV-style widgets
    def _create_label(self, parent, text, row, col, **kwargs):
        """Create a NERV-style label"""
        label = ttk.Label(parent, text=text.upper())
        label.grid(row=row, column=col, **kwargs)
        return label
        
    def _create_entry(self, parent, textvariable, row, col, **kwargs):
        """Create a NERV-style entry - version-agnostic approach"""
        entry = ttk.Entry(parent, textvariable=textvariable, **kwargs)
        entry.grid(row=row, column=col, sticky="we", padx=2)
        
        # VERSION-AGNOSTIC SOLUTION that handles different variable types:
        # 1. Force any pending updates
        entry.update_idletasks()
        
        # 2. Get the expected value, handling different variable types
        try:
            expected_value = textvariable.get()
            # Don't manipulate if it's a numeric variable (DoubleVar/IntVar)
            # connected to a scale - these sync properly on their own
            if isinstance(textvariable, (tk.DoubleVar, tk.IntVar)):
                # For numeric variables, don't manipulate the entry
                # The variable binding handles it correctly
                return entry
        except:
            # If get() fails, just return the entry as-is
            return entry
        
        # 3. For StringVar only: check and fix if needed
        if isinstance(textvariable, tk.StringVar):
            current_value = entry.get()
            expected_str = str(expected_value) if expected_value else ""
            
            # Only manipulate if values don't match
            if current_value != expected_str:
                entry.delete(0, tk.END)
                if expected_str:
                    entry.insert(0, expected_str)
            
        return entry
        
    def _create_nerv_scale(self, parent, **kwargs):
        """Create a NERV-style scale (slider)"""
        scale = tk.Scale(
            parent,
            bg=self.FG_SECONDARY,             # ← Changed to orange by default
            fg=self.FG_PRIMARY,
            activebackground=self.FG_ACTIVE,  # ← Changed to red on hover for distinction
            highlightbackground=self.BG_PRIMARY,
            highlightcolor=self.BORDER_COLOR,
            highlightthickness=0,
            troughcolor=self.BG_SECONDARY,
            borderwidth=0,
            sliderlength=20,
            sliderrelief="flat",
            showvalue=False,
            font=self.mono_font,
            **kwargs
        )
        return scale
        
    def _create_nerv_checkbutton(self, parent, **kwargs):
        """Create a NERV-style checkbutton"""
        cb = tk.Checkbutton(
            parent,
            bg=self.BG_PRIMARY,
            fg=self.FG_PRIMARY,
            activebackground=self.BG_PRIMARY,
            activeforeground=self.FG_SECONDARY,
            selectcolor=self.BG_PRIMARY,
            highlightbackground=self.BG_PRIMARY,
            highlightcolor=self.BORDER_COLOR,
            highlightthickness=0,
            font=self.mono_font,
            **kwargs
        )
        return cb

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
        
        # Only proceed if sig_cfg exists (it might not during initialization)
        if not hasattr(self, "sig_cfg"):
            if DEBUG:
                print(f"[MAIN_GUI] _sig_update: sig_cfg doesn't exist yet, skipping")
            return
        
        if hasattr(self, "sig") and self.sig:
            self.sig.update_cfg(**kwargs)
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
        fs_entry_text = self.fs_entry.get()  # Read from Entry widget directly
        
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
        self.fs_var.set(str(new_fs))
        
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
        
        # Ensure the NFFT slider updates immediately
        self.nfft_sld.update_idletasks()
        
        # NEW: Update spectrogram window size slider maximum
        spec_max_win = total_samples // 2
        self.spec_win_sld.configure(to=spec_max_win)
        if self.spec_win_var.get() > spec_max_win:
            self.spec_win_var.set(spec_max_win)
            self.spec_win_sld.set(spec_max_win)  # Update slider position
            self.spec_win_label.config(text=str(spec_max_win))
        
        # Update the status in console
        self.ser_console.configure(state="normal")
        self.ser_console.insert("end", f"[PC] BUFFER UPDATED: {new_fs} HZ, {new_dur} S ({total_samples} SAMPLES)\n")
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
        if self.ser_btn["text"] == "CONNECT":      # ---- connect
            self.ser.start(self.port_var.get(), int(self.baud_var.get()))
            self.ser_btn.config(text="DISCONNECT", style="Active.TButton")
            self.port_cb.config(state="disabled")
        else:                                      # ---- disconnect
            self.ser.stop()
            self.ser_btn.config(text="CONNECT", style="TButton")
            self.port_cb.config(state="readonly")
        
    def _send_net_config(self):
        if self.ser_btn["text"] != "DISCONNECT":
            return
    
        # ⬇ NEW: read directly from the Entry widgets
        ssid = self.ssid_entry.get().strip()
        pw   = self.pass_entry.get().strip()
    
        if not ssid or not pw:
            self.ser.rx_q.put("[PC] ✖ SSID / PASSWORD REQUIRED\n")
            return
    
        snd = self.ser.send_and_wait
        snd(f"set ssid {ssid}")
        snd(f"set pass {pw}")
        snd(f"set port_ctrl {self.ctrl_port_var.get().strip()}")
        snd(f"set port_data {self.data_port_var.get().strip()}")
        snd("apply and reboot")
        
    # ── refresh COM-port list ───────────────────────────────────────────
    def _refresh_ports(self):
        try:
            plist = SerialManager.ports()          # fresh scan every call
        except Exception as e:                     # catch any PySerial/WMI error
            plist = []
            # Log error to console for debugging
            if self.ser_console:
                self.ser_console.configure(state="normal")
                self.ser_console.insert("end", f"[PC] ⚠ Port scan error: {e}\n")
                self.ser_console.configure(state="disabled")
                self.ser_console.see("end")
        
        self.port_cb["values"] = plist or ("",)
    
        # if current selection vanished → pick the first detected port
        if plist and self.port_var.get() not in plist:
            self.port_var.set(plist[0])
            try:
                self.port_cb.current(0)
            except tk.TclError:
                pass                           # widget may be disabled
    
        # ←————  schedule the next scan! (ALWAYS happens now, even on error)
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

        txt = tk.Text(frame, wrap="word", bg=self.CONSOLE_BG, 
                      insertbackground=self.FG_PRIMARY, state="disabled",
                      borderwidth=1, relief="solid", highlightthickness=0)
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
        self._create_label(parent, "PORT", 0, 0, sticky="e")
        self.port_var = tk.StringVar()
        self.port_cb = ttk.Combobox(parent, textvariable=self.port_var,
                                    values=[], state="readonly")
        self.port_cb.grid(row=0, column=1, sticky="we", padx=2)

        # ── row-1 : Baud rate ──────────────────────────────────
        self._create_label(parent, "BAUD", 1, 0, sticky="e")
        self.baud_var = tk.StringVar(value="115200")
        ent = self._create_entry(parent, self.baud_var, 1, 1)

        # ── row-2 : Connect / Disconnect button ───────────────
        self.ser_btn = ttk.Button(parent, text="CONNECT",
                                  command=self._toggle_serial)
        self.ser_btn.grid(row=2, column=0, columnspan=2,
                          sticky="we", pady=(0, 4))

        # ── row-3 : SSID ───────────────────────────────────────
        self._create_label(parent, "SSID", 3, 0, sticky="e")
        self.ssid_var = tk.StringVar(value="SlimeVR")
        self.ssid_entry = self._create_entry(parent, self.ssid_var, 3, 1)

        # ── row-4 : Password ──────────────────────────────────
        self._create_label(parent, "PASSWORD", 4, 0, sticky="e")
        self.pass_var = tk.StringVar(value="")
        self.pass_entry = ttk.Entry(parent, textvariable=self.pass_var, show="*")
        self.pass_entry.grid(row=4, column=1, sticky="we", padx=2)
        # Password Entry doesn't use _create_entry, so handle it separately
        # Force update and check if empty (for Python 3.12 compatibility)
        self.pass_entry.update_idletasks()
        if not self.pass_entry.get() and self.pass_var.get():
            self.pass_entry.insert(0, self.pass_var.get())

        # ── row-5 : Data port ─────────────────────────────────
        self._create_label(parent, "DATA PORT", 5, 0, sticky="e")
        self.data_port_var = tk.StringVar(value="5001")
        ent = self._create_entry(parent, self.data_port_var, 5, 1, width=8)

        # ── row-6 : Control port ──────────────────────────────
        self._create_label(parent, "CTRL PORT", 6, 0, sticky="e")
        self.ctrl_port_var = tk.StringVar(value="5000")
        ent = self._create_entry(parent, self.ctrl_port_var, 6, 1, width=8)

        # ── row-7 : Send-config button ────────────────────────
        ttk.Button(parent, text="SEND NET CONFIG",
                   command=self._send_net_config
                   ).grid(row=7, column=0, columnspan=2,
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
                    labels=("ON", "OFF"),
                    default="A"):
            """
            Place a header + two side-by-side buttons in *frm* starting at *col*.
        
            labels : (left_text, right_text)
            default: "A" | "B"  → which button is active at start
            """
            state = {"sel": None}                         # current side
        
            # header
            self._create_label(frm, text, 0, col, columnspan=2, sticky="we", pady=(0, 1))
        
            # sub-frame so both buttons have equal width
            box = ttk.Frame(frm); box.grid(row=1, column=col, sticky="we")
            for c in (0, 1):
                box.columnconfigure(c, weight=1)
        
            btnA = ttk.Button(box, text=labels[0].upper())
            btnB = ttk.Button(box, text=labels[1].upper())
            btnA.grid(row=0, column=0, sticky="we", padx=1)
            btnB.grid(row=0, column=1, sticky="we", padx=1)
        
            def _apply_styles():
                btnA.configure(style="Active.TButton" if state["sel"] == "A" else "TButton")
                btnB.configure(style="Active.TButton" if state["sel"] == "B" else "TButton")
        
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
        self.wifi_btn = ttk.Button(parent, text="UDP CONNECT",
                                   command=self._toggle_udp)
        self.wifi_btn.grid(row=r, column=0, sticky="we", padx=2, pady=(0, 8))
        r += 1

        # ── maintenance trio (board / adc / erase) ───────────────────────
        f = row_frame(r, 3);  r += 1
        ttk.Button(f, text="BOARD REBOOT",
                   command=lambda: self._send_udp_cmd("sys esp_reboot"),
                   style="Alert.TButton"
                   ).grid(row=0, column=0, sticky="we", padx=2, pady=1)
        ttk.Button(f, text="ADC RESET",
                   command=lambda: self._send_udp_cmd("sys adc_reset")
                   ).grid(row=0, column=1, sticky="we", padx=2, pady=1)
        ttk.Button(f, text="ERASE WI-FI",
                   command=lambda: self._send_udp_cmd("sys erase_flash"),
                   style="Alert.TButton"
                   ).grid(row=0, column=2, sticky="we", padx=2, pady=1)

        # ── filter master & mains frequency ──────────────────────────────
        f = row_frame(r, 2);  r += 1
        two_way(f, 0, "ALL FILTERS",      "sys filters_on",  "sys filters_off", default="B")
        two_way(f, 1, "NETWORK FREQ",
                "sys networkfreq 50", "sys networkfreq 60",
                labels=("50 HZ", "60 HZ"),
                default="A")

        # ── equaliser & DC-block ─────────────────────────────────────────
        f = row_frame(r, 2);  r += 1
        two_way(f, 0, "EQUALISER", "sys filter_equalizer_on",
                              "sys filter_equalizer_off",    default="B")
        two_way(f, 1, "DC-BLOCK",  "sys filter_dc_on",
                              "sys filter_dc_off",           default="B")

        # ── notch filters ────────────────────────────────────────────────
        f = row_frame(r, 2);  r += 1
        two_way(f, 0, "50/60 HZ NOTCH",
                "sys filter_5060_on",  "sys filter_5060_off",  default="B")
        two_way(f, 1, "100/120 HZ NOTCH",
                "sys filter_100120_on","sys filter_100120_off",default="B")

        # ── DC-cut dropdown ──────────────────────────────────────────────
        f = row_frame(r, 3);  r += 1
        self._create_label(f, "DC-CUTOFF", 0, 0, sticky="e", padx=2)
        
        dc_values          = ["0.5", "1", "2", "4", "8"]
        self.dccut_var     = tk.StringVar(value=dc_values[0])
        dccut_cb           = ttk.Combobox(
            f, textvariable=self.dccut_var, state="readonly", values=dc_values
        )
        dccut_cb.grid(row=0, column=1, sticky="we", padx=2)
        dccut_cb.current(0)
        ttk.Button(
            f, text="SET",
            command=lambda cb=dccut_cb:
                self._send_udp_cmd(f"sys dccutofffreq {cb.get()}")
        ).grid(row=0, column=2, sticky="we", padx=2, pady=1)
        
        # ── digital-gain dropdown ───────────────────────────────────────
        f = row_frame(r, 3);  r += 1
        self._create_label(f, "DIGITAL GAIN", 0, 0, sticky="e", padx=2)
        
        gain_values        = ["1", "2", "4", "8", "16", "32", "64", "128", "256"]
        self.gain_var      = tk.StringVar(value=gain_values[0])
        gain_cb            = ttk.Combobox(
            f, textvariable=self.gain_var, state="readonly", values=gain_values
        )
        gain_cb.grid(row=0, column=1, sticky="we", padx=2)
        gain_cb.current(0)
        ttk.Button(
            f, text="SET",
            command=lambda cb=gain_cb:
                self._send_udp_cmd(f"sys digitalgain {cb.get()}")
        ).grid(row=0, column=2, sticky="we", padx=2, pady=1)

        # ── continuous-mode controls ─────────────────────────────────────
        f = row_frame(r, 2);  r += 1
        ttk.Button(f, text="START CNT",
                   command=lambda: self._send_udp_cmd("sys start_cnt"),
                   style="Active.TButton"
                   ).grid(row=0, column=0, sticky="we", padx=2, pady=(4, 1))
        ttk.Button(f, text="STOP CNT",
                   command=lambda: self._send_udp_cmd("sys stop_cnt"),
                   style="Alert.TButton"
                   ).grid(row=0, column=1, sticky="we", padx=2, pady=(4, 1))

    # ── start / stop UDP listener ─────────────────────────────────────────
    def _toggle_udp(self):
        if self.udp and self.udp._thread and self.udp._thread.is_alive():        # stop
            self.udp.stop()
            self.udp = None
            self.wifi_btn.config(text="UDP CONNECT", style="TButton")
            self.wifi_console.insert("end", "[PC] UDP DISCONNECTED\n")
            return

        # start
        try:
            port = int(self.ctrl_port_var.get())
        except ValueError:
            self.wifi_console.insert("end", "[PC] ✖ INVALID CONTROL-PORT\n")
            return

        self.udp = UDPManager(port)
        self.udp.start()
        self.udp.rx_q = self.wifi_q
        self.udp.tx_hook = lambda pkt: self.wifi_q.put(f"[PC_] {pkt}\n")

        self.wifi_btn.config(text="DISCONNECT", style="Active.TButton")
        self.wifi_console.insert(
            "end", f"[PC] UDP LISTENING ON *:{port} … WAITING FOR BEACON\n")

    # ── helper: transmit one command over UDP (no local echo) ─────────────
    def _send_udp_cmd(self, cmd: str):
        """
        Queue *cmd* for transmission over UDP.
        Echo appears once via udp_backend.tx_hook so no duplicates.
        """
        if self.udp and self.udp.board_ip:
            self.udp.send(cmd)
        else:
            self.wifi_q.put("[PC] ✖ UDP NOT CONNECTED / BOARD IP UNKNOWN\n")

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
        # Always use the current configuration values
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
        Ensures all child processes and threads are terminated cleanly.
        """
        print("[MAIN_GUI] Shutting down...")
        
        # Cancel all pending after() callbacks first
        try:
            self.after_cancel(self._animate_plots)
        except:
            pass
        try:
            self.after_cancel(self._poll_queues)
        except:
            pass
        try:
            self.after_cancel(self._refresh_ports)
        except:
            pass
        
        # tell timers & workers to stop
        self.stop_evt.set()
    
        # stop signal worker (IMPORTANT: This runs a subprocess)
        if self.sig:
            try:
                print("[MAIN_GUI] Stopping signal worker process...")
                self.sig.stop()
                # Give it a moment to terminate the subprocess
                time.sleep(0.1)
            except Exception as e:
                print(f"[MAIN_GUI] Error stopping signal worker: {e}")
                
        # stop UDP manager (if it exists and is connected)
        if self.udp:
            try:
                print("[MAIN_GUI] Stopping UDP thread...")
                self.udp.stop()
            except Exception as e:
                print(f"[MAIN_GUI] Error stopping UDP: {e}")
                
        # stop serial manager
        if self.ser:
            try:
                print("[MAIN_GUI] Stopping serial thread...")
                self.ser.stop()
            except Exception as e:
                print(f"[MAIN_GUI] Error stopping serial: {e}")
    
        # Force terminate any remaining child processes (failsafe)
        try:
            import multiprocessing
            for child in multiprocessing.active_children():
                print(f"[MAIN_GUI] Force terminating process: {child.name}")
                child.terminate()
                child.join(timeout=0.5)
                if child.is_alive():
                    child.kill()  # Force kill if terminate didn't work
        except Exception as e:
            print(f"[MAIN_GUI] Error during process cleanup: {e}")
        
        # destroy window
        print("[MAIN_GUI] Closing window...")
        self.destroy()
        
        # Force exit to ensure everything stops
        sys.exit(0)


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Windows .exe support for multiprocessing
    import multiprocessing
    multiprocessing.freeze_support()
    
    try:
        App().mainloop()
    except KeyboardInterrupt:
        sys.exit(0)