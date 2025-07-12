"""plot_manager.py - Matplotlib Plot Management for DIY EEG GUI
Encapsulates all matplotlib complexity to simplify main GUI
"""

import numpy as np
import scipy.signal as sps
from scipy.signal import get_window
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# Dark palette for Matplotlib
matplotlib.rcParams.update({
    "axes.facecolor": "#1E1E1E",
    "axes.edgecolor": "#D4D4D4",
    "axes.labelcolor": "#D4D4D4",
    "xtick.color": "#D4D4D4",
    "ytick.color": "#D4D4D4",
    "figure.facecolor": "#1E1E1E",
})


class PlotManager:
    """
    Encapsulates all matplotlib plotting complexity for the EEG GUI.
    
    Manages:
    - Five stacked plots (Δt, time, wavelet, spectrogram, PSD)
    - Background caching for fast blitting
    - Dynamic buffer resizing
    - Plot updates and limits
    """
    
    def __init__(self, parent_frame, bg_color="#1E1E1E", debug=False):
        """
        Initialize the plot manager.
        
        Args:
            parent_frame: Tkinter frame to contain the plots
            bg_color: Background color for the canvas
            debug: Enable debug output
        """
        self.parent = parent_frame
        self.bg_color = bg_color
        self.debug = debug
        
        # Create figure with 5 subplots
        self.fig = Figure(constrained_layout=True, dpi=100)
        g = self.fig.add_gridspec(5, 1, height_ratios=[1, 1, 1, 1, 1])
        
        self.ax_dt = self.fig.add_subplot(g[0])
        self.ax_time = self.fig.add_subplot(g[1])
        self.ax_wav = self.fig.add_subplot(g[2])
        self.ax_sg = self.fig.add_subplot(g[3])
        self.ax_psd = self.fig.add_subplot(g[4])
        
        # Aliases for compatibility
        self.ax_wavelet = self.ax_wav
        self.ax_specgram = self.ax_sg
        
        # Configure axes
        self.ax_dt.set_ylabel("Δt [µs]")
        self.ax_dt.grid(ls=":")
        self.ax_time.set_ylabel("V")
        self.ax_time.grid(ls=":")
        self.ax_time.set_ylim(-0.5, 0.5)  # Initial amplitude limits
        self.ax_wav.set_ylabel("f [Hz]")
        self.ax_sg.set_ylabel("f [Hz]")
        self.ax_psd.set_ylabel("dB")
        self.ax_psd.set_xlabel("Hz")
        self.ax_psd.grid(ls=":")
        self.ax_psd.set_ylim(-130, 0)  # Initial PSD limits
        
        # Initialize with dummy data
        N0 = 100
        xs = np.arange(N0)
        
        # Create line artists
        self.dt_line, = self.ax_dt.plot(xs, np.zeros(N0), lw=.8)
        self.time_lines = [self.ax_time.plot(xs, np.zeros(N0), lw=.8)[0] 
                          for _ in range(16)]
        
        # Create image artists
        self.im_wavelet = self.ax_wav.imshow(
            np.zeros((64, N0)), origin="lower", aspect="auto", 
            extent=(0, N0, 1, 250), vmin=-60, vmax=0
        )
        self.im_specgram = self.ax_sg.imshow(
            np.zeros((64, N0)), origin="lower", aspect="auto",
            extent=(0, N0, 0, 250), vmin=-80, vmax=0
        )
        
        # Create PSD lines
        self.psd_lines = [self.ax_psd.plot([], [], lw=.8)[0] for _ in range(16)]
        self.psd_max = [self.ax_psd.plot([], [], lw=.8, ls="--",
                                         color=self.psd_lines[i].get_color())[0]
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
        self.widget.configure(bg=bg_color, highlightthickness=0)
        
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
        current_amp = self.ax_time.get_ylim()[1]
        current_psd_min, current_psd_max = self.ax_psd.get_ylim()
        
        # Recreate axes labels and settings
        self.ax_dt.set_ylabel("Δt [µs]")
        self.ax_dt.grid(ls=":")
        self.ax_time.set_ylabel("V")
        self.ax_time.grid(ls=":")
        self.ax_time.set_ylim(-current_amp, current_amp)
        self.ax_wav.set_ylabel("f [Hz]")
        self.ax_sg.set_ylabel("f [Hz]")
        self.ax_psd.set_ylabel("dB")
        self.ax_psd.set_xlabel("Hz")
        self.ax_psd.grid(ls=":")
        self.ax_psd.set_ylim(current_psd_min, current_psd_max)
        
        # Create new time axis
        N0 = int(duration * fs)
        xs_sec = np.arange(N0) / fs  # X-axis in seconds
        
        # Recreate all artists
        self.dt_line, = self.ax_dt.plot(xs_sec, np.zeros(N0), lw=.8)
        self.time_lines = [self.ax_time.plot(xs_sec, np.zeros(N0), lw=.8)[0]
                          for _ in range(16)]
        
        # Create dummy images with proper extent
        dummy_rows = 64
        self.im_wavelet = self.ax_wav.imshow(
            np.zeros((dummy_rows, N0)), origin="lower", aspect="auto",
            extent=(0, duration, 1, fs/2), vmin=-60, vmax=0
        )
        self.im_specgram = self.ax_sg.imshow(
            np.zeros((dummy_rows, N0)), origin="lower", aspect="auto",
            extent=(0, duration, 0, fs/2), vmin=-80, vmax=0
        )
        
        self.psd_lines = [self.ax_psd.plot([], [], lw=.8)[0] for _ in range(16)]
        self.psd_max = [self.ax_psd.plot([], [], lw=.8, ls="--",
                                         color=self.psd_lines[i].get_color())[0]
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
            ax.set_xlabel("Time (s)")
        
        # Reset max-hold data
        self.maxhold_data = [None] * 16
        
        # Update state
        self._current_fs = fs
        self._current_duration = duration
        
        # Force redraw and update background
        self._bg_cache = None
        self.draw_full()
        
    def update_snapshot(self, data: np.ndarray, fs: int, duration: int, 
                       nfft: int = 512, cheb_db: float = 80.0):
        """
        Update all plots with new data snapshot.
        
        Args:
            data: (N, 16) array of samples
            fs: Sample rate in Hz
            duration: Expected buffer duration in seconds
            nfft: FFT size for PSD
            cheb_db: Chebyshev window attenuation in dB
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
        
        # Update Δt (placeholder - zeros for now)
        self.dt_line.set_ydata(np.zeros(xs_sec.size))
        
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
        
        # Update spectrogram (only if channel 0 is visible)
        if self.channel_visible[0]:
            if data.shape[0] < expected_npts:
                spec_data = np.zeros(expected_npts)
                spec_data[-data.shape[0]:] = data[:, 0]
            else:
                spec_data = data[-expected_npts:, 0]
                
            f_s, t_s, Sxx = sps.spectrogram(
                spec_data, fs=fs, window="hann", nperseg=256, noverlap=128
            )
            self.im_specgram.set_data(10*np.log10(Sxx + 1e-12))
            self.im_specgram.set_extent((0, duration, f_s[0], f_s[-1]))
            
            # Update wavelet (using same data as spectrogram for now)
            self.im_wavelet.set_data(10*np.log10(Sxx + 1e-12))
            self.im_wavelet.set_extent((0, duration, 1, fs/2))
        else:
            # Channel 0 hidden - show empty spectrograms
            empty = np.zeros((64, expected_npts))
            self.im_specgram.set_data(empty)
            self.im_wavelet.set_data(empty)
        
        # Update PSD
        try:
            win = get_window(('chebwin', cheb_db), nfft, fftbins=False)
        except:
            win = np.hamming(nfft)
            
        freqs = np.fft.rfftfreq(nfft, d=1/fs)
        
        for idx in range(16):
            if len(data) >= nfft:
                seg = data[-nfft:, idx] * win
                psd = 20*np.log10(np.abs(np.fft.rfft(seg)) + 1e-15)
                self.psd_lines[idx].set_data(freqs, psd)
                # Ensure visibility is maintained
                self.psd_lines[idx].set_visible(self.channel_visible[idx])
                
                if self.maxhold_enabled and self.channel_visible[idx]:
                    mh = self.maxhold_data[idx]
                    if mh is None or len(mh) != len(psd):
                        self.maxhold_data[idx] = psd.copy()
                    else:
                        self.maxhold_data[idx] = np.maximum(mh, psd)
                    self.psd_max[idx].set_data(freqs, self.maxhold_data[idx])
                    self.psd_max[idx].set_visible(True)
                else:
                    self.psd_max[idx].set_visible(False)
            else:
                # Not enough data for FFT - hide the line
                self.psd_lines[idx].set_visible(False)
                self.psd_max[idx].set_visible(False)
                    
        self.ax_psd.set_xlim(0, fs / 2)
        
        # Perform fast blit update
        self.draw_blit()
        
    def set_amplitude_limits(self, volts: float):
        """Update time plot y-axis limits."""
        self.ax_time.set_ylim(-volts, volts)
        if self.debug:
            print(f"[PLOT_MANAGER] Set amplitude limits: ±{volts}V")
        self.draw_full()
        
    def set_psd_limits(self, min_db: float, max_db: float):
        """Update PSD plot limits."""
        self.ax_psd.set_ylim(min_db, max_db)
        if self.debug:
            print(f"[PLOT_MANAGER] Set PSD limits: {min_db} to {max_db} dB")
        self.draw_full()
        
    def set_maxhold(self, enabled: bool):
        """Toggle max-hold display."""
        self.maxhold_enabled = enabled
        for idx in range(16):
            # Only show max-hold if channel is visible
            self.psd_max[idx].set_visible(enabled and self.channel_visible[idx])
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
                self.ax_dt.set_ylabel(labels['dt'])
            if 'time' in labels:
                self.ax_time.set_ylabel(labels['time'])
            if 'wav' in labels:
                self.ax_wav.set_ylabel(labels['wav'])
            if 'sg' in labels:
                self.ax_sg.set_ylabel(labels['sg'])
            if 'psd' in labels:
                self.ax_psd.set_ylabel(labels['psd'])
                
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