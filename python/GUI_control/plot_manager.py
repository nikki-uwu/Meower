"""plot_manager.py - Matplotlib Plot Management for DIY EEG GUI
Encapsulates all matplotlib complexity to simplify main GUI
Evangelion/NERV Style Edition
"""

import numpy as np
import scipy.signal as sps
from scipy.signal import get_window
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.pyplot as plt
from matplotlib import font_manager

# NERV/Evangelion color palette
NERV_BLACK = "#000000"
NERV_AMBER = "#FFB000"  # Primary amber/yellow
NERV_ORANGE = "#FF6B00"  # Secondary orange
NERV_RED = "#FF0000"    # Alert/active red
NERV_GREEN = "#00FF00"  # Success/status green
NERV_GRID = "#333333"   # Subtle grid color
NERV_TEXT = "#FFB000"   # Text color

# Configure matplotlib for NERV aesthetic
matplotlib.rcParams.update({
    "axes.facecolor": NERV_BLACK,
    "axes.edgecolor": NERV_AMBER,
    "axes.labelcolor": NERV_AMBER,
    "xtick.color": NERV_AMBER,
    "ytick.color": NERV_AMBER,
    "figure.facecolor": NERV_BLACK,
    "grid.color": NERV_GRID,
    "grid.linestyle": "-",
    "grid.linewidth": 0.5,
    "grid.alpha": 0.7,
    "font.family": "monospace",
    "font.size": 9,
    "axes.linewidth": 1.5,
    "xtick.major.width": 1.2,
    "ytick.major.width": 1.2,
    "xtick.major.size": 4,
    "ytick.major.size": 4,
})


def ricker_wavelet(points, width):
    """
    Pure Python Ricker (Mexican hat) wavelet.
    
    Args:
        points: Number of points in the wavelet
        width: Width parameter of the wavelet
        
    Returns:
        Ricker wavelet array
    """
    A = 2 / (np.sqrt(3 * width) * (np.pi**0.25))
    t = np.linspace(-points//2, points//2, points)
    wsq = width**2
    return A * (1 - (t**2) / wsq) * np.exp(-(t**2) / (2 * wsq))


def ricker_cwt(x, widths, min_points=6):
    """
    Compute continuous wavelet transform using Ricker wavelets.
    
    Args:
        x: Input signal
        widths: Array of wavelet widths
        min_points: Minimum points for wavelet
        
    Returns:
        CWT matrix
    """
    output = np.zeros((len(widths), len(x)), dtype=np.float32)
    for idx, width in enumerate(widths):
        points = max(2 * int(width), min_points)
        if points < min_points or points > len(x):
            # Skip wavelets that are too short or longer than signal
            continue
        wavelet = ricker_wavelet(points, width)
        output[idx, :] = np.convolve(x, wavelet, mode='same')
    return output


class PlotManager:
    """
    Encapsulates all matplotlib plotting complexity for the EEG GUI.
    
    Manages:
    - Five stacked plots (Δt, time, wavelet, spectrogram, PSD)
    - Background caching for fast blitting
    - Dynamic buffer resizing
    - Plot updates and limits
    - NERV/Evangelion visual style
    """
    
    def __init__(self, parent_frame, bg_color="#000000", debug=False, style="evangelion"):
        """
        Initialize the plot manager.
        
        Args:
            parent_frame: Tkinter frame to contain the plots
            bg_color: Background color for the canvas
            debug: Enable debug output
            style: Visual style ("evangelion" or "default")
        """
        self.parent = parent_frame
        self.bg_color = bg_color
        self.debug = debug
        self.style = style
        
        # Initialize stored limits
        self._psd_min = -150
        self._psd_max = -20
        self._amp_limit = 0.5
        
        # Create figure with 5 subplots
        self.fig = Figure(facecolor=NERV_BLACK, dpi=100)
        # Use tight layout with small padding for NERV aesthetic
        g = self.fig.add_gridspec(5, 1, height_ratios=[1, 1, 1, 1, 1], 
                                  hspace=0.15, left=0.08, right=0.98, 
                                  top=0.98, bottom=0.05)
        
        self.ax_dt = self.fig.add_subplot(g[0])
        self.ax_time = self.fig.add_subplot(g[1])
        self.ax_wav = self.fig.add_subplot(g[2])
        self.ax_sg = self.fig.add_subplot(g[3])
        self.ax_psd = self.fig.add_subplot(g[4])
        
        # Aliases for compatibility
        self.ax_wavelet = self.ax_wav
        self.ax_specgram = self.ax_sg
        
        # Configure axes with NERV style
        self._style_axis(self.ax_dt, "TIMING DEVIATION [µS]")
        self._style_axis(self.ax_time, "AMPLITUDE [V]")
        self._style_axis(self.ax_wav, "FREQUENCY [HZ]")
        self._style_axis(self.ax_sg, "FREQUENCY [HZ]")
        self._style_axis(self.ax_psd, "POWER [DB]", xlabel="FREQUENCY [HZ]")
        
        # Set initial limits
        expected_period_us = 1e6 / 250  # 4000 µs for 250Hz
        y_min = expected_period_us - 100
        y_max = expected_period_us + 100
        if y_min < 0:
            y_min = 0
        self.ax_dt.set_ylim(y_min, y_max)
        self.ax_time.set_ylim(-0.5, 0.5)
        self.ax_psd.set_ylim(-150, -20)
        
        # Initialize with dummy data
        N0 = 100
        xs = np.arange(N0)
        
        # Create line artists with NERV colors
        self.dt_line, = self.ax_dt.plot(xs, np.zeros(N0), lw=1.2, color=NERV_GREEN)
        
        # Use a color palette for the 16 channels
        self.channel_colors = self._generate_channel_colors()
        self.time_lines = [self.ax_time.plot(xs, np.zeros(N0), lw=1.0, 
                                             color=self.channel_colors[i], alpha=0.9)[0] 
                          for i in range(16)]
        
        # Create image artists with NERV colormap
        self.nerv_cmap = self._create_nerv_colormap()
        self.im_wavelet = self.ax_wav.imshow(
            np.zeros((64, N0)), origin="lower", aspect="auto", 
            extent=(0, N0/250.0, 1, 125), vmin=-120, vmax=-30,
            cmap=self.nerv_cmap, interpolation='bilinear'
        )
        self.im_specgram = self.ax_sg.imshow(
            np.zeros((64, N0)), origin="lower", aspect="auto",
            extent=(0, N0/250.0, 0, 125), vmin=-120, vmax=-30,
            cmap=self.nerv_cmap, interpolation='bilinear'
        )
        
        # Create PSD lines
        self.psd_lines = [self.ax_psd.plot([], [], lw=1.0, 
                                          color=self.channel_colors[i], alpha=0.9)[0] 
                         for i in range(16)]
        # Set initial PSD x-axis to positive frequencies only
        self.ax_psd.set_xlim(0, 125)  # 0 to fs/2 for initial 250Hz
        self.psd_max = [self.ax_psd.plot([], [], lw=1.2, ls="--",
                                        color=self.channel_colors[i], alpha=0.6)[0]
                       for i in range(16)]
        
        # Mark all artists as animated for blitting
        self.dt_line.set_animated(True)
        for line in self.time_lines:
            line.set_animated(True)
        self.im_wavelet.set_animated(True)
        self.im_specgram.set_animated(True)
        for line in (*self.psd_lines, *self.psd_max):
            line.set_animated(True)
        
        # Create canvas
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent_frame)
        self.widget = self.canvas.get_tk_widget()
        self.widget.configure(bg=NERV_BLACK, highlightthickness=0)
        
        # Background cache for blitting
        self._bg_cache = None
        
        # Connect draw event to save background
        def _save_bg(evt):
            if self.debug:
                print(f"[PLOT_MANAGER] Saving background cache")
            self._bg_cache = self.canvas.copy_from_bbox(self.fig.bbox)
        
        self.fig.canvas.mpl_connect("draw_event", _save_bg)
        
        # Initial draw to create background
        self.fig.canvas.draw()
        
        # State tracking
        self._current_fs = 250
        self._current_duration = 4
        self.maxhold_data = [None] * 16
        self.maxhold_enabled = False
        self.channel_visible = [True] * 16  # All channels visible by default
        
        # Wavelet/spectrogram channel and limits
        self.wavspec_channel = 0  # Channel to show in wavelet/spectrogram
        self.wav_vmin, self.wav_vmax = -120, -30
        self.spec_vmin, self.spec_vmax = -120, -30
        
    def _style_axis(self, ax, ylabel, xlabel=None):
        """Apply NERV styling to an axis"""
        ax.set_facecolor(NERV_BLACK)
        ax.set_ylabel(ylabel.upper(), fontsize=10, fontweight='bold', color=NERV_AMBER)
        if xlabel:
            ax.set_xlabel(xlabel.upper(), fontsize=10, fontweight='bold', color=NERV_AMBER)
        
        # Configure spines (borders)
        for spine in ax.spines.values():
            spine.set_color(NERV_AMBER)
            spine.set_linewidth(1.5)
        
        # Configure grid
        ax.grid(True, color=NERV_GRID, linestyle='-', linewidth=0.5, alpha=0.5)
        
        # Configure ticks
        ax.tick_params(colors=NERV_AMBER, which='both', labelsize=8)
        
        # Make all text uppercase
        for label in ax.get_xticklabels() + ax.get_yticklabels():
            label.set_fontfamily('monospace')
            
    def _generate_channel_colors(self):
        """Generate NERV-style colors for 16 channels"""
        # Use variations of amber, orange, and green
        base_colors = [
            "#FFB000",  # Amber
            "#FF8C00",  # Dark orange
            "#FFD700",  # Gold
            "#FFA500",  # Orange
            "#00FF00",  # Green
            "#00FF7F",  # Spring green
            "#7FFF00",  # Chartreuse
            "#ADFF2F",  # Green yellow
        ]
        # Repeat and vary brightness
        colors = []
        for i in range(16):
            base = base_colors[i % len(base_colors)]
            # Vary brightness slightly
            factor = 0.8 + (i % 4) * 0.1
            colors.append(self._adjust_color_brightness(base, factor))
        return colors
        
    def _adjust_color_brightness(self, hex_color, factor):
        """Adjust color brightness by factor"""
        rgb = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
        rgb = tuple(min(255, int(c * factor)) for c in rgb)
        return f'#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}'
        
    def _create_nerv_colormap(self):
        """Create NERV-style colormap for spectrograms"""
        # Black -> Dark amber -> Amber -> Bright amber/yellow
        colors = [
            (0.0, NERV_BLACK),
            (0.25, '#331100'),  # Very dark amber
            (0.5, '#663300'),   # Dark amber
            (0.75, NERV_AMBER), # Amber
            (1.0, '#FFFF00')    # Bright yellow
        ]
        
        positions = [c[0] for c in colors]
        colors_rgb = [matplotlib.colors.hex2color(c[1]) for c in colors]
        
        cdict = {
            'red': [(p, c[0], c[0]) for p, c in zip(positions, colors_rgb)],
            'green': [(p, c[1], c[1]) for p, c in zip(positions, colors_rgb)],
            'blue': [(p, c[2], c[2]) for p, c in zip(positions, colors_rgb)]
        }
        
        return matplotlib.colors.LinearSegmentedColormap('nerv', cdict)
    
    def get_widget(self):
        """Return the Tk widget for embedding in GUI."""
        return self.widget
        
    def resize_buffer(self, fs: int, duration: int):
        """
        Handle buffer size changes by rebuilding all artists.
        
        Args:
            fs: New sample rate in Hz
            duration: New buffer duration in seconds
        """
        if self.debug:
            print(f"[PLOT_MANAGER] Resizing buffer: {fs}Hz, {duration}s")
            
        # Clear all axes
        self.ax_dt.clear()
        self.ax_time.clear()
        self.ax_wav.clear()
        self.ax_sg.clear()
        self.ax_psd.clear()
        
        # Get current limits before clearing
        current_amp = getattr(self, '_amp_limit', 0.5)
        current_psd_min = getattr(self, '_psd_min', -150)
        current_psd_max = getattr(self, '_psd_max', -20)
        
        # Recreate axes labels and settings with NERV style
        expected_period_us = 1e6 / fs
        self._style_axis(self.ax_dt, f"TIMING DEVIATION [µS] (EXPECT: {expected_period_us:.0f})")
        self._style_axis(self.ax_time, "AMPLITUDE [V]")
        self._style_axis(self.ax_wav, "FREQUENCY [HZ]")
        self._style_axis(self.ax_sg, "FREQUENCY [HZ]")
        self._style_axis(self.ax_psd, "POWER [DB]", xlabel="FREQUENCY [HZ]")
        
        # Apply the stored limits
        self.ax_time.set_ylim(-current_amp, current_amp)
        self.ax_psd.set_ylim(current_psd_min, current_psd_max)
        # Set PSD x-axis to positive frequencies only
        self.ax_psd.set_xlim(0, fs/2)
        
        # Update Δt y-axis limits based on new sample rate
        y_min = expected_period_us - 100
        y_max = expected_period_us + 100
        if y_min < 0:
            y_min = 0
        self.ax_dt.set_ylim(y_min, y_max)
        
        # Update wavelet and spectrogram frequency axis limits
        self.ax_wav.set_ylim(1, fs/2)
        self.ax_sg.set_ylim(0, fs/2)
        
        # Create new time axis
        N0 = int(duration * fs)
        xs_sec = np.arange(N0) / fs  # X-axis in seconds
        
        # Recreate all artists with NERV colors
        self.dt_line, = self.ax_dt.plot(xs_sec, np.zeros(N0), lw=1.2, color=NERV_GREEN)
        self.time_lines = [self.ax_time.plot(xs_sec, np.zeros(N0), lw=1.0,
                                            color=self.channel_colors[i], alpha=0.9)[0]
                          for i in range(16)]
        
        # Create dummy images with proper extent
        dummy_rows = 64
        self.im_wavelet = self.ax_wav.imshow(
            np.zeros((dummy_rows, N0)), origin="lower", aspect="auto",
            extent=(0, duration, 1, fs/2), vmin=self.wav_vmin, vmax=self.wav_vmax,
            cmap=self.nerv_cmap, interpolation='bilinear'
        )
        self.im_specgram = self.ax_sg.imshow(
            np.zeros((dummy_rows, N0)), origin="lower", aspect="auto",
            extent=(0, duration, 0, fs/2), vmin=self.spec_vmin, vmax=self.spec_vmax,
            cmap=self.nerv_cmap, interpolation='bilinear'
        )
        
        self.psd_lines = [self.ax_psd.plot([], [], lw=1.0,
                                          color=self.channel_colors[i], alpha=0.9)[0] 
                         for i in range(16)]
        self.psd_max = [self.ax_psd.plot([], [], lw=1.2, ls="--",
                                        color=self.channel_colors[i], alpha=0.6)[0]
                       for i in range(16)]
        
        # Mark new artists as animated
        self.dt_line.set_animated(True)
        for line in self.time_lines:
            line.set_animated(True)
        self.im_wavelet.set_animated(True)
        self.im_specgram.set_animated(True)
        for line in (*self.psd_lines, *self.psd_max):
            line.set_animated(True)
            
        # Restore channel visibility settings
        for i in range(16):
            self.time_lines[i].set_visible(self.channel_visible[i])
            self.psd_lines[i].set_visible(self.channel_visible[i])
            if self.maxhold_enabled and self.channel_visible[i]:
                self.psd_max[i].set_visible(True)
            else:
                self.psd_max[i].set_visible(False)
        
        # Update xlimits
        for ax in (self.ax_time, self.ax_wavelet, self.ax_specgram, self.ax_dt):
            ax.set_xlim(0, duration)
            ax.set_xlabel("TIME [S]", fontsize=10, fontweight='bold', color=NERV_AMBER)
        
        # Add reference line for expected period in Δt plot
        expected_period_us = 1e6 / fs
        self._dt_expected_line = self.ax_dt.axhline(
            y=expected_period_us, 
            color=NERV_ORANGE, 
            linestyle='--', 
            alpha=0.7,
            linewidth=1.5,
            animated=True
        )
        
        # Reset max-hold data
        self.maxhold_data = [None] * 16
        
        # Update state - MUST be before draw_full
        self._current_fs = fs
        self._current_duration = duration
        
        # Force redraw and update background
        self._bg_cache = None
        self.draw_full()
        
    def update_snapshot(self, data: np.ndarray, fs: int, duration: int, 
                       timestamps: np.ndarray = None, nfft: int = 512, 
                       cheb_db: float = 80.0, spec_nperseg: int = 256,
                       wav_freqs: int = 64):
        """
        Update all plots with new data snapshot.
        
        Args:
            data: (N, 16) array of samples
            fs: Sample rate in Hz
            duration: Expected buffer duration in seconds
            timestamps: (N,) array of hardware timestamps for Δt calculation
            nfft: FFT size for PSD
            cheb_db: Chebyshev window attenuation in dB
            spec_nperseg: Spectrogram window size
            wav_freqs: Number of frequency points for wavelet transform
        """
        # Check if buffer needs resizing
        expected_npts = int(duration * fs)
        need_rebuild = (
            fs != self._current_fs or
            abs(duration - self._current_duration) > 1e-6 or
            self.time_lines[0].get_xdata().size != expected_npts
        )
        
        if need_rebuild:
            self.resize_buffer(fs, duration)
            return  # resize_buffer will trigger a full redraw
            
        # Create x-axis for full duration
        xs_sec = np.arange(expected_npts) / fs
        
        # Update Δt (time differences from timestamps)
        if timestamps is not None and isinstance(timestamps, np.ndarray) and len(timestamps) > 1:
            try:
                # Calculate time differences between consecutive samples
                # Hardware timestamps are in units of 8 microseconds
                time_diffs = np.diff(timestamps.astype(np.int64))
                
                # Handle 32-bit wraparound
                time_diffs = np.where(time_diffs < 0, time_diffs + (1 << 32), time_diffs)
                
                # Convert to microseconds (multiply by 8)
                dt_us = time_diffs.astype(np.float64) * 8.0
                
                # Pad with the expected period to match the full buffer size
                expected_period_us = 1e6 / fs
                if len(dt_us) < xs_sec.size - 1:
                    dt_full = np.full(xs_sec.size, expected_period_us)
                    # Put the actual diffs at the end (most recent data)
                    start_idx = max(0, xs_sec.size - len(dt_us) - 1)
                    dt_full[start_idx:start_idx + len(dt_us)] = dt_us
                else:
                    # Take the last portion if we have more data
                    dt_full = np.full(xs_sec.size, expected_period_us)
                    dt_full[:-1] = dt_us[-(xs_sec.size-1):]
                
                # First sample has no previous sample to diff with
                dt_full[0] = expected_period_us
                    
                self.dt_line.set_ydata(dt_full)
                
                # Ensure y-axis limits are updated for current sample rate
                y_min = expected_period_us - 100
                y_max = expected_period_us + 100
                # Clip minimum to 0 if it would go negative
                if y_min < 0:
                    y_min = 0
                self.ax_dt.set_ylim(y_min, y_max)
                
                # Update or recreate the horizontal reference line
                if hasattr(self, '_dt_expected_line'):
                    self._dt_expected_line.remove()
                self._dt_expected_line = self.ax_dt.axhline(
                    y=expected_period_us, 
                    color=NERV_ORANGE, 
                    linestyle='--', 
                    alpha=0.7,
                    linewidth=1.5,
                    animated=True
                )
                    
                # Update axis label to show expected period
                self.ax_dt.set_ylabel(f"TIMING DEVIATION [µS] (EXPECT: {expected_period_us:.0f})", 
                                     fontsize=10, fontweight='bold', color=NERV_AMBER)
            except Exception as e:
                if self.debug:
                    print(f"[PLOT_MANAGER] Error updating Δt plot: {e}")
                # Fall back to showing expected period
                expected_period_us = 1e6 / fs
                self.dt_line.set_ydata(np.full(xs_sec.size, expected_period_us))
        else:
            # No timestamps available, show expected period
            expected_period_us = 1e6 / fs
            self.dt_line.set_ydata(np.full(xs_sec.size, expected_period_us))
            # Set appropriate limits based on sample rate
            y_min = expected_period_us - 100
            y_max = expected_period_us + 100
            if y_min < 0:
                y_min = 0
            self.ax_dt.set_ylim(y_min, y_max)
            
            # Update or recreate the horizontal reference line
            if hasattr(self, '_dt_expected_line'):
                self._dt_expected_line.remove()
            self._dt_expected_line = self.ax_dt.axhline(
                y=expected_period_us, 
                color=NERV_ORANGE, 
                linestyle='--', 
                alpha=0.7,
                linewidth=1.5,
                animated=True
            )
            
            self.ax_dt.set_ylabel(f"TIMING DEVIATION [µS] (EXPECT: {expected_period_us:.0f})",
                                 fontsize=10, fontweight='bold', color=NERV_AMBER)
        
        # Update time-domain plots
        if data.shape[0] < xs_sec.size:
            # Pad with zeros if snapshot is smaller than buffer
            full_data = np.zeros((xs_sec.size, 16))
            full_data[-data.shape[0]:] = data
            for i, (ln, ch) in enumerate(zip(self.time_lines, full_data.T)):
                ln.set_ydata(ch)
                # Ensure visibility is maintained during updates
                ln.set_visible(self.channel_visible[i])
        else:
            # Use last portion if we have more data
            for i, (ln, ch) in enumerate(zip(self.time_lines, data[-xs_sec.size:].T)):
                ln.set_ydata(ch)
                # Ensure visibility is maintained during updates
                ln.set_visible(self.channel_visible[i])
        
        # Update spectrogram and wavelet with selected channel
        if self.channel_visible[self.wavspec_channel]:
            if data.shape[0] < expected_npts:
                spec_data = np.zeros(expected_npts)
                spec_data[-data.shape[0]:] = data[:, self.wavspec_channel]
            else:
                spec_data = data[-expected_npts:, self.wavspec_channel]
            
            # Remove DC component by subtracting mean
            spec_data_dc_removed = spec_data
            
            # Calculate 95% overlap
            noverlap = int(0.95 * spec_nperseg)
            
            # Create Chebyshev window for spectrogram
            try:
                spec_window = get_window(('chebwin', cheb_db), spec_nperseg, fftbins=False)
            except:
                spec_window = np.hamming(spec_nperseg)
            
            # Normalize window
            spec_window = spec_window / np.mean(spec_window)
            
            # Compute spectrogram with 95% overlap and DC removed
            f_s, t_s, Sxx = sps.spectrogram(
                spec_data_dc_removed, fs=fs, window=spec_window, 
                nperseg=spec_nperseg, noverlap=noverlap
            )
            
            # Convert to dB and apply limits
            Sxx_db = 10*np.log10(Sxx + 1e-20)
            self.im_specgram.set_data(Sxx_db)
            self.im_specgram.set_extent((0, duration, f_s[0], f_s[-1]))
            self.im_specgram.set_clim(self.spec_vmin, self.spec_vmax)
            
            # Compute proper wavelet transform
            # Use the same DC-removed data
            wav_data = spec_data_dc_removed
            
            # Define frequency range for wavelets
            nyq = fs / 2
            N_freqs = wav_freqs  # Use the parameter from GUI
            freqs = np.linspace(1, nyq, N_freqs)
            
            # Convert frequencies to wavelet widths
            # width = fs / (2 * pi * frequency)
            widths = fs / (2 * np.pi * freqs)
            
            # Only keep widths that make sense for our signal length
            valid = (2 * widths >= 6) & (2 * widths < len(wav_data))
            widths = widths[valid]
            freqs = freqs[valid]
            
            if len(widths) > 0:
                # Compute CWT
                cwt_matrix = ricker_cwt(wav_data, widths)
                
                # Convert to power in dB
                cwt_power_db = 10 * np.log10(np.abs(cwt_matrix)**2 + 1e-20)
                
                # Update wavelet plot
                self.im_wavelet.set_data(cwt_power_db)
                self.im_wavelet.set_extent((0, duration, freqs[0], freqs[-1]))
                self.im_wavelet.set_clim(self.wav_vmin, self.wav_vmax)
                
                # Update y-axis to show actual frequency range
                self.ax_wav.set_ylim(freqs[0], freqs[-1])
            else:
                # No valid wavelets, show empty
                empty = np.zeros((64, expected_npts))
                self.im_wavelet.set_data(empty)
        else:
            # Selected channel is hidden - show empty spectrograms
            empty = np.zeros((64, expected_npts))
            self.im_specgram.set_data(empty)
            self.im_wavelet.set_data(empty)
        
        # Update PSD
        try:
            win = get_window(('chebwin', cheb_db), nfft, fftbins=False)
        except:
            win = np.hamming(nfft)
        
        # Normalize window by its mean
        win = win / np.mean(win)
            
        freqs = np.fft.rfftfreq(nfft, d=1/fs)
        
        for idx in range(16):
            if len(data) >= nfft:
                # Get segment without removing DC (keep original signal)
                seg = data[-nfft:, idx]
                seg_windowed = seg * win
                # Perform FFT with normalization by length
                fft_result = np.fft.rfft(seg_windowed) / nfft
                psd = 20*np.log10(np.abs(fft_result) + 1e-20)
                self.psd_lines[idx].set_data(freqs, psd)
                # Ensure visibility is maintained
                self.psd_lines[idx].set_visible(self.channel_visible[idx])
                
                if self.maxhold_enabled and self.channel_visible[idx]:
                    mh = self.maxhold_data[idx]
                    if mh is None or len(mh) != len(psd):
                        self.maxhold_data[idx] = psd.copy()
                        if self.debug:
                            print(f"[PLOT_MANAGER] Initializing max-hold for channel {idx}")
                    else:
                        self.maxhold_data[idx] = np.maximum(mh, psd)
                    self.psd_max[idx].set_data(freqs, self.maxhold_data[idx])
                    self.psd_max[idx].set_visible(True)
                    if self.debug:
                        print(f"[PLOT_MANAGER] Max-hold updated for channel {idx}, visible={self.psd_max[idx].get_visible()}")
                else:
                    self.psd_max[idx].set_visible(False)
            else:
                # Not enough data for FFT - hide the line
                self.psd_lines[idx].set_visible(False)
                self.psd_max[idx].set_visible(False)
                    
        # Ensure PSD x-axis shows correct frequency range
        self.ax_psd.set_xlim(0, fs / 2)
        
        # Perform fast blit update
        self.draw_blit()
        
    def set_amplitude_limits(self, volts: float):
        """Update time plot y-axis limits."""
        self._amp_limit = volts
        self.ax_time.set_ylim(-volts, volts)
        if self.debug:
            print(f"[PLOT_MANAGER] Set amplitude limits: ±{volts}V")
        self.draw_full()
        
    def set_psd_limits(self, min_db: float, max_db: float):
        """Update PSD plot limits."""
        self._psd_min = min_db
        self._psd_max = max_db
        self.ax_psd.set_ylim(min_db, max_db)
        if self.debug:
            print(f"[PLOT_MANAGER] Set PSD limits: {min_db} to {max_db} dB")
        self.draw_full()
        
    def set_maxhold(self, enabled: bool):
        """Toggle max-hold display."""
        self.maxhold_enabled = enabled
        for idx in range(16):
            # Only show max-hold if channel is visible
            visible = enabled and self.channel_visible[idx]
            self.psd_max[idx].set_visible(visible)
            if self.debug:
                print(f"[PLOT_MANAGER] Max-hold line {idx}: visible={visible} (enabled={enabled}, ch_visible={self.channel_visible[idx]})")
        if not enabled:
            self.maxhold_data = [None] * 16
        if self.debug:
            print(f"[PLOT_MANAGER] Max-hold: {enabled}")
        self.draw_full()
        
    def reset_maxhold(self):
        """Reset max-hold data."""
        self.maxhold_data = [None] * 16
        for ln in self.psd_max:
            ln.set_visible(False)
            ln.set_data([], [])
        if self.debug:
            print(f"[PLOT_MANAGER] Max-hold reset")
        self.draw_full()
        
    def draw_full(self):
        """Force complete redraw and update background cache."""
        if self.debug:
            print(f"[PLOT_MANAGER] Full redraw")
        self.canvas.draw()
        self._bg_cache = self.canvas.copy_from_bbox(self.fig.bbox)
        
    def draw_blit(self):
        """Fast blit update using cached background."""
        if self._bg_cache is None:
            # No background cached, do full draw
            self.draw_full()
            return
            
        # Restore background
        self.canvas.restore_region(self._bg_cache)
        
        # Draw all animated artists
        self.ax_dt.draw_artist(self.dt_line)
        if hasattr(self, '_dt_expected_line'):
            self.ax_dt.draw_artist(self._dt_expected_line)
        for i, ln in enumerate(self.time_lines):
            if self.channel_visible[i] and ln.get_visible():
                self.ax_time.draw_artist(ln)
        self.ax_sg.draw_artist(self.im_specgram)
        self.ax_wav.draw_artist(self.im_wavelet)
        for i, ln in enumerate(self.psd_lines):
            if self.channel_visible[i] and ln.get_visible():
                self.ax_psd.draw_artist(ln)
        for i, ln in enumerate(self.psd_max):
            if ln.get_visible():  # Max-hold visibility already considers channel visibility
                self.ax_psd.draw_artist(ln)
                
        # Single blit call for entire figure
        self.canvas.blit(self.fig.bbox)
        self.canvas.flush_events()
        
    def bind_resize_callback(self, callback):
        """Bind a callback for window resize events."""
        self.widget.bind("<Configure>", callback, add="+")
        
    def get_axes_limits(self):
        """Get current axes limits for programmatic testing."""
        return {
            'time': self.ax_time.get_ylim(),
            'psd': self.ax_psd.get_ylim(),
            'psd_freq': self.ax_psd.get_xlim(),
            'duration': self.ax_time.get_xlim()[1]
        }
        
    def update_axes_labels(self, labels=None):
        """Update axes labels if needed."""
        if labels:
            if 'dt' in labels:
                self.ax_dt.set_ylabel(labels['dt'].upper())
            if 'time' in labels:
                self.ax_time.set_ylabel(labels['time'].upper())
            if 'wav' in labels:
                self.ax_wav.set_ylabel(labels['wav'].upper())
            if 'sg' in labels:
                self.ax_sg.set_ylabel(labels['sg'].upper())
            if 'psd' in labels:
                self.ax_psd.set_ylabel(labels['psd'].upper())
                
    def set_channel_visibility(self, channel: int, visible: bool):
        """Set visibility for a specific channel (0-15)."""
        if self.debug:
            print(f"[PLOT_MANAGER] set_channel_visibility called: channel={channel}, visible={visible}")
            
        if 0 <= channel < 16:
            self.channel_visible[channel] = visible
            
            # Update line visibility immediately
            if self.debug:
                print(f"[PLOT_MANAGER] Setting time_lines[{channel}].set_visible({visible})")
            self.time_lines[channel].set_visible(visible)
            
            if self.debug:
                print(f"[PLOT_MANAGER] Setting psd_lines[{channel}].set_visible({visible})")
            self.psd_lines[channel].set_visible(visible)
            
            if not visible:
                # If hiding channel, also hide its max-hold line
                self.psd_max[channel].set_visible(False)
            elif self.maxhold_enabled:
                # If showing channel and max-hold is on, show max-hold line
                self.psd_max[channel].set_visible(True)
            
            if self.debug:
                print(f"[PLOT_MANAGER] Channel {channel} visibility updated to: {visible}")
                print(f"[PLOT_MANAGER] Calling draw_full()")
            
            # Force redraw to update display immediately
            self.draw_full()
            
    def set_all_channels_visibility(self, visible_list: list):
        """Set visibility for all channels at once (more efficient)."""
        if len(visible_list) != 16:
            return
            
        for i in range(16):
            self.channel_visible[i] = visible_list[i]
            self.time_lines[i].set_visible(visible_list[i])
            self.psd_lines[i].set_visible(visible_list[i])
            if not visible_list[i]:
                self.psd_max[i].set_visible(False)
            elif self.maxhold_enabled:
                self.psd_max[i].set_visible(True)
                
        # Single redraw for all changes
        self.draw_full()
        
    def set_wavspec_channel(self, channel: int):
        """Set which channel to display in wavelet/spectrogram."""
        if 0 <= channel < 16:
            self.wavspec_channel = channel
            if self.debug:
                print(f"[PLOT_MANAGER] Wavelet/Spectrogram channel set to: {channel}")

    def set_wavelet_limits(self, min_db: float, max_db: float):
        """Update wavelet plot limits."""
        self.wav_vmin, self.wav_vmax = min_db, max_db
        self.im_wavelet.set_clim(min_db, max_db)
        if self.debug:
            print(f"[PLOT_MANAGER] Set wavelet limits: {min_db} to {max_db} dB")
        self.draw_full()

    def set_specgram_limits(self, min_db: float, max_db: float):
        """Update spectrogram plot limits."""
        self.spec_vmin, self.spec_vmax = min_db, max_db
        self.im_specgram.set_clim(min_db, max_db)
        if self.debug:
            print(f"[PLOT_MANAGER] Set spectrogram limits: {min_db} to {max_db} dB")
        self.draw_full()