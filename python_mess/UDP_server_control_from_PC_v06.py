import multiprocessing as mp
import numpy as np
import socket
import time
import scipy.signal as sps
from scipy import signal
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import struct
import pywt
import tkinter as tk
from matplotlib.widgets import Slider, CheckButtons, Button
from scipy.signal.windows import chebwin
from scipy.signal import firwin2
# Processing config
import time as _time  # Always available for timing


# --------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------
# Sampling frequency
sample_rate  = 500 
N_ch         = 16
time_window  = 8  # seconds
buf_size     = time_window * sample_rate

# No decrease load lets slow down server a little bit allowing to try to pull new data 1/4 of our sample rate
Server_sleeping_time = 1 / sample_rate / 40

# Build the array of starting indices for each of the 16 channels
IDX_ADC_SAMPLES = np.concatenate([3*np.arange(16)]).astype(np.int32)

# Settings for 50 and 100 Hz notch filter
Q = 1.5
b50 , a50  = sps.iirnotch( 50.0, Q, sample_rate)
b100, a100 = sps.iirnotch(100.0, Q, sample_rate)
b_comb     = np.convolve(b50, b100)
a_comb     = np.convolve(a50, a100)
# Compute DC gain of the combined filter
dc_gain = np.sum(b_comb) / np.sum(a_comb)
# # Compute normalization factor so that the DC gain becomes unity.
# norm_factor = 1 / dc_gain
# # Normalize the numerator coefficients
# b_comb_normalized = b_comb * norm_factor
# # Design a high-pass Butterworth filter for DC removal.
# # Here we use a 2nd order filter with a cutoff at 0.5 Hz.
# cutoff = 2  # cutoff frequency in Hz
order = 2
# b_dc, a_dc = sps.butter(order, cutoff / (sample_rate / 2), btype='highpass')
# b_comb = np.convolve(b_comb, b_dc)
# a_comb = np.convolve(a_comb, a_dc)

# Network configuration
PC_IP        = "0.0.0.0"
RECEIVE_PORT = 5001       # Port to receive data from ESP32
SEND_PORT    = 5000          # Port to send commands to ESP32

# Global time counter
timer = time.time()

IP = "225.1.1.1"   # stay consistent with what you enter in the GUI
PORT      = 6677

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)

# Helper functions
# --------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------
def parse_frame(raw_data: bytes) -> np.ndarray:
    """
    Return one 16-int32 frame.
    **Requires exactly 48 bytes.**   <-- original comment said 54 B; corrected here, old wording kept for context
    """
    if len(raw_data) != 48:          # was 54 B in the comment – firmware actually sends 48 B per frame
        raise ValueError(f"parse_frame() needs 48 B, got {len(raw_data)} B")
    raw_arr = np.frombuffer(raw_data, dtype=np.uint8).astype(np.int32)

    # 24-bit chunks → sign-extended int32
    high = (raw_arr[IDX_ADC_SAMPLES]     << 16)
    mid  = (raw_arr[IDX_ADC_SAMPLES + 1] <<  8)
    low  =  raw_arr[IDX_ADC_SAMPLES + 2]
    value_24 = (high | mid | low).astype(np.int32)

    neg = (value_24 & 0x800000) != 0
    value_24[neg] -= (1 << 24)
    return value_24          # already shape (16,)

def remove_50_100Hz_noise(signal_in):
    """
    Removes ~50 Hz and ~100 Hz noise from 'signal_in' using a
    single, combined IIR notch filter (4th order).
    """
    filtered = sps.filtfilt(b_comb, a_comb, signal_in, axis = 0)
    return filtered

def flush_udp_buffer(sock):
    """
    Flushes the UDP buffer by reading all available packets until none remain.
    """
    sock.setblocking(False)
    while True:
        try:
            data, addr = sock.recvfrom(65535)
        except BlockingIOError:
            break
    sock.setblocking(True)
    
def lock_window_to_bottom_right(fig):
    """
    Resize the TkAgg window for the given matplotlib figure to half the screen size,
    then reposition it so that its bottom-right corner aligns with the screen's bottom-right.
    """
    mng = fig.canvas.manager
    window = mng.window
    window.update_idletasks()
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    task_bar_height = round(screen_height*0.025);
    new_width  = screen_width // 2
    new_height = (screen_height - task_bar_height) // 2
    x = screen_width - new_width
    y = screen_height - new_height - task_bar_height
    y = y - round(screen_height*0.02)
    def set_geometry():
        window.geometry(f"{new_width}x{new_height}+{x}+{y}")
    window.after(10, set_geometry)
    fig.canvas.draw()
    plt.show()

# Background process (UDP reader)
# --------------------------------------------------------------------------------------------
def udp_reader_process(shared_dict, shared_bat, shared_tim,
                       lock, sample_rate, buf_size, ip, port):
    import traceback
    DEBUG = False
    log   = (lambda *a, **k: None) if not DEBUG else (lambda *a, **k: print("[UDP]", *a, **k))
    FR_LEN   = 52                # 48 ADC + 4 timestamp  (comment kept, value unchanged)
    MIN_LEN  = FR_LEN            # shortest thing we accept
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((ip, port))
    sock.setblocking(False)
    log(f"Reader up on {ip}:{port}")

    data_buf  = np.zeros((buf_size, N_ch),    np.int32)
    time_buf  = np.zeros(buf_size,           np.uint32)
    # Precompute the scale factor to avoid per-frame division
    scale = 4.5 / (2**23)

    while True:
        try:
            try:
                raw, _ = sock.recvfrom(2048)          # non-blocking
            except BlockingIOError:
                time.sleep(0.0005)                    # yield CPU
                continue

            L = len(raw)
            if L < MIN_LEN:
                continue
            frames = (L - 4) // FR_LEN
            if frames == 0:
                continue

            batt = struct.unpack_from('<f', raw, frames * FR_LEN)[0]

            # SLIDE BUFFER: batch move if possible for speed
            for n in range(frames):
                base = n * FR_LEN
                try:
                    frame = parse_frame(raw[base : base + 48])
                except Exception as e:
                    continue
                ts = struct.unpack_from('<I', raw, base + 48)[0]
                # Roll in place for faster update, no realloc
                data_buf[:-1] = data_buf[1:]
                time_buf[:-1] = time_buf[1:]
                data_buf[-1]  = frame
                time_buf[-1]  = ts

            # Only copy once per batch
            with lock:
                shared_dict['latest'] = (data_buf * scale).copy()
                shared_bat ['latest'] = batt
                shared_tim ['latest'] = time_buf.copy()
        except Exception as e:
            continue


# Pure Python Ricker (Mexican hat) wavelet, always works even if scipy.signal.ricker is missing
def ricker_wavelet(points, width):
    A = 2 / (np.sqrt(3 * width) * (np.pi**0.25))
    t = np.linspace(-points//2, points//2, points)
    wsq = width**2
    return A * (1 - (t**2) / wsq) * np.exp(-(t**2) / (2 * wsq))

def _ricker_cwt(x, widths, min_points=6):
    output = np.zeros((len(widths), len(x)), dtype=np.float32)
    for idx, width in enumerate(widths):
        points = max(2 * int(width), min_points)
        if points < min_points or points > len(x):
            # Skip wavelets that are too short or longer than signal
            continue
        wavelet = ricker_wavelet(points, width)
        output[idx, :] = np.convolve(x, wavelet, mode='same')
    return output

# Define filter toggles to match firmware commands
def send_filter_command(name, on, ESP_IP, send_sock, receive_sock):
    cmd = f"sys {name}_{'on' if on else 'off'} "
    send_sock.sendto(cmd.encode(), (ESP_IP, SEND_PORT))
    pkt, _ = receive_sock.recvfrom(256)
    try:
        txt = pkt.decode('ascii').strip()
        print("RX <", txt)
    except UnicodeDecodeError:
        print("RX <", ' '.join(f'{b:02x}' for b in pkt))

# --- Toggle all filters ON/OFF ---
def set_all_filters(state, ESP_IP, send_sock, receive_sock):
    send_filter_command('filters', state, ESP_IP, send_sock, receive_sock)

# --- Toggle each filter individually ---
def set_filter_equalizer(state, ESP_IP, send_sock, receive_sock):
    send_filter_command('filter_equalizer', state, ESP_IP, send_sock, receive_sock)

def set_filter_dc(state, ESP_IP, send_sock, receive_sock):
    send_filter_command('filter_dc', state, ESP_IP, send_sock, receive_sock)

def set_filter_5060(state, ESP_IP, send_sock, receive_sock):
    send_filter_command('filter_5060', state, ESP_IP, send_sock, receive_sock)

def set_filter_100120(state, ESP_IP, send_sock, receive_sock):
    send_filter_command('filter_100120', state, ESP_IP, send_sock, receive_sock)

def main():
    # ─── 1. Open sockets ───────────────────────────────────────────────────
    receive_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receive_sock.bind((PC_IP, RECEIVE_PORT))
    
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # ─── 2. Wait for the ESP32-C3 beacon ───────────────────────────────────
    flush_udp_buffer(receive_sock)
    print("Waiting for ESP32's IP beacon …")
    data, addr = receive_sock.recvfrom(2048)
    ESP_IP = addr[0]
    print("ESP32's IP is", ESP_IP)
    
    # ─── 3. Full chip reset  + ADC idle  ───────────────────────────────────
    send_sock.sendto(b"sys reset ", (ESP_IP, SEND_PORT))
    time.sleep(2)
    flush_udp_buffer(receive_sock)
    
    # ─── 4. Read a few registers to verify link ----------------------------
    for reg in (0x20, 0x23):
        cmd = f"spi M 3 0x{reg:02X} 0x00 0x00 "
        send_sock.sendto(cmd.encode(), (ESP_IP, SEND_PORT))
        time.sleep(0.1)
        data, _ = receive_sock.recvfrom(1024)
        print("RX <", ' '.join(f'{b:02x}' for b in data))
    
    # ─── 5. Configure CONFIG1 on master and slave --------------------------
    send_sock.sendto(b"spi M 3 0x41 0x00 0xB6 ", (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    send_sock.sendto(b"spi S 3 0x41 0x00 0x96 ", (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    flush_udp_buffer(receive_sock)
    
    # ─── 6. CONFIG2: enable test signal (both ADCs) ------------------------
    CONFIG_2 = 0xD4
    cmd = f"spi B 3 0x42 0x00 0x{CONFIG_2:02X} "
    send_sock.sendto(cmd.encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    flush_udp_buffer(receive_sock)
    
    # ─── 7. Channel settings (all 16 inputs to normal mode) ----------------
    CHANNEL_CONF = 0x00
    for reg in range(0x45, 0x4D):          # CH1SET … CH8SET on both ADCs
        cmd = f"spi B 3 0x{reg:02X} 0x00 0x{CHANNEL_CONF:02X} "
        send_sock.sendto(cmd.encode(), (ESP_IP, SEND_PORT))
        time.sleep(0.1)
    
    # ─── 8. CONFIG3 master / slave ----------------------------------------
    MASTER_CONF_3 = 0xEC
    SLAVE_CONF_3  = 0xE8
    send_sock.sendto(f"spi M 3 0x43 0x00 0x{MASTER_CONF_3:02X} ".encode(), (ESP_IP, SEND_PORT))
    send_sock.sendto(f"spi S 3 0x43 0x00 0x{SLAVE_CONF_3:02X} ".encode(),  (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    flush_udp_buffer(receive_sock)
    
    # quick sanity read
    send_sock.sendto(b"spi M 3 0x23 0x00 0x00 ", (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    data, _ = receive_sock.recvfrom(1024)
    print("RX <", ' '.join(f'{b:02x}' for b in data))
    
    # ─── 9. Enable DSP blocks if desired -----------------------------------
    # ─── Toggle both DSP blocks OFF and echo firmware reply ───────────────
    def show_reply(pkt: bytes) -> None:
        """
        Pretty-print an UDP reply: ASCII text if it decodes cleanly,
        otherwise fall back to hex-dump.
        """
        try:
            txt = pkt.decode('ascii').strip()
            print("RX <", txt)
        except UnicodeDecodeError:
            print("RX <", ' '.join(f'{b:02x}' for b in pkt))
    
    # Example: turn all filters ON at once
    set_all_filters(True, ESP_IP, send_sock, receive_sock)
    # Or control individually
    set_filter_equalizer(True, ESP_IP, send_sock, receive_sock)
    set_filter_dc(True, ESP_IP, send_sock, receive_sock)
    set_filter_5060(True, ESP_IP, send_sock, receive_sock)
    set_filter_100120(True, ESP_IP, send_sock, receive_sock)
    
    # ───10. Start continuous streaming ------------------------------------
    send_sock.sendto(b"sys start_cnt ", (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    
    receive_sock.close()

    # Start background UDP reader immediately
    manager = mp.Manager()
    shared_dict = manager.dict()
    shared_dict['latest'] = None
    shared_dict_bat = manager.dict()
    shared_dict_bat['latest'] = None
    shared_dict_timer = manager.dict()
    shared_dict_timer['latest'] = None
    lock = mp.Lock()
    reader_proc = mp.Process(
        target=udp_reader_process,
        args=(shared_dict, shared_dict_bat, shared_dict_timer, lock, sample_rate, buf_size, PC_IP, RECEIVE_PORT),
        daemon=True
    )
    reader_proc.start()

    # Plot/filter setup
    fs_design = 500.0
    nyq = fs_design / 2
    f_dense = np.linspace(0, nyq, 256)
    H_sinc3 = np.sinc(f_dense / fs_design)**3
    H_inv   = np.ones_like(H_sinc3)
    H_inv[1:] = 1.0 / H_sinc3[1:]
    norm_freqs = f_dense / nyq
    h_eq = firwin2(numtaps=7, freq=norm_freqs, gain=H_inv, window='hamming')

    def safe_get(var, default):
        try:
            return float(var.get())
        except:
            return default

    fig_ts, (ax_dt, ax_time, ax_wavelet, ax_specgram, ax_freq) = plt.subplots(5, 1, constrained_layout=True)
    lock_window_to_bottom_right(fig_ts)
    ax_dt.set_title("Sample Δt (μs)")
    ax_dt.set_xlim(0, buf_size)
    ax_dt.set_ylim(0, 500)
    ax_dt.set_ylabel("Δt [μs]")
    ax_dt.grid(True)
    ax_time.set_title("Time-Domain (16 channels)")
    ax_time.set_xlim(0, buf_size)
    ax_time.set_ylim(-0.005, 0.005)
    ax_time.set_ylabel("Amp [V]")
    ax_time.grid(True)
    
    # ─────────────── Wavelet plot (scalogram, Ch1) ───────────────
    nyq = fs_design / 2
    N_freqs = 256  # default number of frequency bins
    freqs = np.linspace(1, nyq, N_freqs)
    ax_wavelet.set_title("Wavelets (Ch1)")
    ax_wavelet.set_xlim(0, buf_size)
    ax_wavelet.set_ylim(freqs[0], freqs[-1])
    ax_wavelet.set_ylabel("Freq [Hz]")
    ax_wavelet.set_xlabel("Sample Index")
    ax_wavelet.grid(True)
    im_wavelet = ax_wavelet.imshow(
        np.zeros((N_freqs, buf_size)),
        origin='lower',
        aspect='auto',
        extent=(0, buf_size, freqs[0], freqs[-1]),
        vmin=-60,
        vmax=0
    )
    ax_specgram.set_title("Spectrogram (Ch1)")
    ax_specgram.set_xlim(0, buf_size)
    ax_specgram.set_ylim(0, fs_design/2)
    ax_specgram.set_xlabel("Sample Index")
    ax_specgram.set_ylabel("Frequency [Hz]")
    ax_specgram.grid(True)
    im_sgram = ax_specgram.imshow(
        np.zeros((len(f_dense), buf_size)),
        origin='lower',
        aspect='auto',
        extent=(0, buf_size, 0, fs_design/2),
        vmin=-80,
        vmax=40
    )
    ax_freq.set_title("Spectrum (16 channels)")
    ax_freq.set_xlabel("Frequency [Hz]")
    ax_freq.set_ylabel("Power [dB]")
    ax_freq.set_ylim(-80, 40)
    ax_freq.grid(True)
    xdata      = np.arange(buf_size)
    lines_dt   = ax_dt.plot(xdata, np.zeros(buf_size), lw=1, animated=True)[0]
    lines_time = [ax_time.plot(xdata, np.zeros(buf_size), lw=1, animated=True)[0] for _ in range(N_ch)]
    lines_spec = [ax_freq.plot([], [], lw=1, animated=True)[0] for _ in range(N_ch)]
    lines_max  = [ax_freq.plot([], [], lw=1, ls='--', animated=True,
                   color=lines_spec[i].get_color())[0] for i in range(N_ch)]
    bg_dt, bg_time, bg_wavelet, bg_spec, bg_freq = [None], [None], [None], [None], [None]
    max_hold = [np.full(1, -np.inf) for _ in range(N_ch)]

    fig_ts.canvas.mpl_connect('draw_event', lambda ev: bg_dt.__setitem__(0, fig_ts.canvas.copy_from_bbox(ax_dt.bbox)))
    fig_ts.canvas.mpl_connect('draw_event', lambda ev: bg_time.__setitem__(0, fig_ts.canvas.copy_from_bbox(ax_time.bbox)))
    fig_ts.canvas.mpl_connect('draw_event', lambda ev: bg_wavelet.__setitem__(0, fig_ts.canvas.copy_from_bbox(ax_wavelet.bbox)))
    fig_ts.canvas.mpl_connect('draw_event', lambda ev: bg_spec.__setitem__(0, fig_ts.canvas.copy_from_bbox(ax_specgram.bbox)))
    fig_ts.canvas.mpl_connect('draw_event', lambda ev: bg_freq.__setitem__(0, fig_ts.canvas.copy_from_bbox(ax_freq.bbox)))
    fig_ts.canvas.draw()

    root = tk.Tk()
    root.title("Controls")
    cf = tk.Frame(root); cf.pack(padx=10, pady=10)
    batt_label = tk.Label(cf, text="Battery: N/A")
    batt_label.grid(row=0, column=0, columnspan=4, sticky='w')
    tk.Label(cf, text="FFT pts:").grid(row=1, column=0, sticky='e')
    fft_var = tk.IntVar(root, 250)
    def on_fft_change(val=None):
        Nwin = fft_var.get(); Nfft = Nwin*2
        fs = safe_get(fs_var, fs_design)
        freqs = np.fft.rfftfreq(Nfft, d=1/fs)
        zero = np.zeros_like(freqs)
        for ln in lines_spec: ln.set_data(freqs, zero)
        for ln in lines_max: ln.set_data(freqs, zero)
        ax_freq.set_xlim(0, fs/2)
        ax_specgram.set_ylim(0, fs/2)
        fig_ts.canvas.draw()
    tk.Scale(cf, from_=32, to=buf_size, orient='horizontal', variable=fft_var,
             command=on_fft_change, length=200).grid(row=1, column=1, columnspan=3, sticky='we')
    tk.Label(cf, text="Fs (Hz):").grid(row=2, column=0, sticky='e')
    fs_var = tk.DoubleVar(root, 250.0)
    fs_entry = tk.Entry(cf, textvariable=fs_var, width=6)
    fs_entry.grid(row=2, column=1, sticky='w')
    fs_entry.bind('<Return>', lambda e: on_fft_change())
    fs_entry.bind('<FocusOut>', lambda e: on_fft_change())
    tk.Label(cf, text="Vmin:").grid(row=3, column=0, sticky='e')
    Vmin = tk.DoubleVar(root, -0.5)
    tk.Entry(cf, textvariable=Vmin, width=6).grid(row=3, column=1)
    tk.Label(cf, text="Vmax:").grid(row=3, column=2, sticky='e')
    Vmax = tk.DoubleVar(root, 0.5)
    tk.Entry(cf, textvariable=Vmax, width=6).grid(row=3, column=3)
    tk.Label(cf, text="Dmin:").grid(row=4, column=0, sticky='e')
    Dmin = tk.DoubleVar(root, 3900.0)
    tk.Entry(cf, textvariable=Dmin, width=6).grid(row=4, column=1)
    tk.Label(cf, text="Dmax:").grid(row=4, column=2, sticky='e')
    Dmax = tk.DoubleVar(root, 4100.0)
    tk.Entry(cf, textvariable=Dmax, width=6).grid(row=4, column=3)
    tk.Label(cf, text="Pmin:").grid(row=5, column=0, sticky='e')
    Pmin = tk.DoubleVar(root, -80.0)
    tk.Entry(cf, textvariable=Pmin, width=6).grid(row=5, column=1)
    tk.Label(cf, text="Pmax:").grid(row=5, column=2, sticky='e')
    Pmax = tk.DoubleVar(root, 40.0)
    tk.Entry(cf, textvariable=Pmax, width=6).grid(row=5, column=3)
    tk.Label(cf, text="Smin:").grid(row=6, column=0, sticky='e')
    Smin = tk.DoubleVar(root, -80.0)
    tk.Entry(cf, textvariable=Smin, width=6).grid(row=6, column=1)
    tk.Label(cf, text="Smax:").grid(row=6, column=2, sticky='e')
    Smax = tk.DoubleVar(root, 40.0)
    tk.Entry(cf, textvariable=Smax, width=6).grid(row=6, column=3)
    tk.Label(cf, text="Win size:").grid(row=7, column=0, sticky='e')
    win_size_var = tk.IntVar(root, 128)
    tk.Scale(cf, from_=32, to=buf_size, orient='horizontal',
             variable=win_size_var, length=200).grid(row=7, column=1, columnspan=3, sticky='we')
    tk.Label(cf, text="Overlap %:").grid(row=8, column=0, sticky='e')
    overlap_var = tk.IntVar(root, 50)
    tk.Scale(cf, from_=0, to=90, orient='horizontal',
             variable=overlap_var, length=200).grid(row=8, column=1, columnspan=3, sticky='we')
    tk.Label(cf, text="Spect Ch:").grid(row=9, column=0, sticky='e')
    channel_var = tk.IntVar(root, 1)
    tk.Spinbox(cf, from_=1, to=N_ch, textvariable=channel_var, width=4).grid(row=9, column=1)
    maxhold_var = tk.BooleanVar(root, True)
    tk.Checkbutton(cf, text="Show Max-Hold", variable=maxhold_var)\
        .grid(row=9, column=2, columnspan=2, sticky='w')
    def update_ylims():
        ax_dt.set_ylim(safe_get(Dmin, 3900), safe_get(Dmax, 4100))
        ax_time.set_ylim(safe_get(Vmin, -0.5), safe_get(Vmax, 0.5))
        ax_freq.set_ylim(safe_get(Pmin, -80), safe_get(Pmax, 40))
        fig_ts.canvas.draw()
        bg_dt[0]   = fig_ts.canvas.copy_from_bbox(ax_dt.bbox)
        bg_time[0] = fig_ts.canvas.copy_from_bbox(ax_time.bbox)
        bg_freq[0] = fig_ts.canvas.copy_from_bbox(ax_freq.bbox)
    tk.Button(cf, text="Update Limits", command=update_ylims)\
        .grid(row=10, column=0, columnspan=4, pady=(5,10))
    check_vars = []
    for i in range(N_ch):
        var = tk.BooleanVar(root, value=(i==0))
        tk.Checkbutton(cf, text=f"Ch{i+1}", variable=var)\
            .grid(row=11 + i//4, column=i%4, sticky='w')
        check_vars.append(var)
    tk.Button(cf, text="Reset Max", command=lambda: [mh.fill(-np.inf) for mh in max_hold])\
        .grid(row=15, column=0, columnspan=4, pady=(5,0))
    tk.Label(cf, text="Wav Overlap %:").grid(row=16, column=0, sticky='e')
    wav_overlap_var = tk.IntVar(root, 99)
    tk.Scale(cf, from_=0, to=99, orient='horizontal', variable=wav_overlap_var, length=200)\
        .grid(row=16, column=1, columnspan=3, sticky='we')
    tk.Label(cf, text="Wav Pow min:").grid(row=17, column=0, sticky='e')
    wav_min_var = tk.DoubleVar(root, -60.0)
    tk.Entry(cf, textvariable=wav_min_var, width=6).grid(row=17, column=1)
    tk.Label(cf, text="Wav Pow max:").grid(row=17, column=2, sticky='e')
    wav_max_var = tk.DoubleVar(root, 0.0)
    tk.Entry(cf, textvariable=wav_max_var, width=6).grid(row=17, column=3)
    tk.Label(cf, text="Wav Freqs:").grid(row=18, column=0, sticky='e')
    N_freqs_var = tk.IntVar(root, 256)
    N_freqs_var.trace_add('write', lambda *a: update_wavelet_image())
    tk.Scale(cf, from_=8, to=256, orient='horizontal', variable=N_freqs_var, length=200).grid(row=18, column=1, columnspan=3, sticky='we')
    on_fft_change()
    
    def update_wavelet_image(*args):
        nonlocal im_wavelet, bg_wavelet
        fs = safe_get(fs_var, fs_design)
        nyq = fs / 2
        N_freqs = max(8, int(N_freqs_var.get()))
        freqs = np.linspace(1, nyq, N_freqs)
        # Remove previous image
        for im in ax_wavelet.images[:]:
            im.remove()
        im_wavelet = ax_wavelet.imshow(
            np.zeros((N_freqs, buf_size)),
            origin='lower',
            aspect='auto',
            extent=(0, buf_size, freqs[0], freqs[-1]),
            vmin=safe_get(wav_min_var, -60.0),
            vmax=safe_get(wav_max_var, 0.0)
        )
        ax_wavelet.set_ylim(freqs[0], freqs[-1])
        fig_ts.canvas.draw()
        bg_wavelet[0] = fig_ts.canvas.copy_from_bbox(ax_wavelet.bbox)


    try:
        prev_time = time.time()
        while plt.fignum_exists(fig_ts.number):
            with lock:
                data_  = shared_dict.get('latest', None)
                batt_  = shared_dict_bat.get('latest', None)
                timer_ = shared_dict_timer.get('latest', None)
            if data_ is None:
                time.sleep(0.001)
                continue
            if timer_ is not None and len(timer_) > 0:
                t     = np.asarray(timer_, np.int64).ravel()
                dt_us = np.diff(t, prepend=t[0]) * 8
            if batt_ is not None:
                v = np.asarray(batt_).ravel()[0] if hasattr(batt_, '__iter__') else batt_
                batt_label.config(text=f"{v:.2f} V")
            now = time.time()
            if (now - prev_time) > 50:
                send_sock.sendto(b'floof ', (ESP_IP, SEND_PORT))
                prev_time = now
            offsets = np.array([
                -4.0459e-04, -5.6858e-04, -4.4878e-04, -4.8903e-04,
                -4.9321e-04, -5.3085e-04, -5.5320e-04, -6.4267e-04,
                -4.3635e-04, -4.5699e-04, -5.0553e-04, -4.4478e-04,
                -4.9772e-04, -4.1176e-04, -4.2540e-04, -4.6826e-04
            ])
            data   = np.asarray(data_)
            # FAST FIR filtering for all channels, fully vectorized (no Python loop)
            data_f = sps.lfilter(h_eq, 1, data, axis=0)
            data_f = data
            # Δt blit
            if bg_dt[0] is not None:
                fig_ts.canvas.restore_region(bg_dt[0])
                lines_dt.set_ydata(dt_us)
                ax_dt.draw_artist(lines_dt)
                fig_ts.canvas.blit(ax_dt.bbox)
            # Time blit
            if bg_time[0] is not None:
                fig_ts.canvas.restore_region(bg_time[0])
                for i, (ln, chk) in enumerate(zip(lines_time, check_vars)):
                    if chk.get():
                        ln.set_ydata(data_f[:, i])
                        ax_time.draw_artist(ln)
                fig_ts.canvas.blit(ax_time.bbox)
            # Wavelet scalogram blit
            if bg_wavelet[0] is not None:
                t0_cwt = _time.perf_counter()
                fs = safe_get(fs_var, fs_design)
                wavelet_size = data_f.shape[0]
                wav_min = safe_get(wav_min_var, -60.0)
                wav_max = safe_get(wav_max_var, 0.0)
                ch = channel_var.get() - 1
                data_ch = data_f[:, ch] - data_f[:, ch].mean()
                data_slice = data_ch[-wavelet_size:] if len(data_ch) >= wavelet_size else data_ch
                nyq = fs / 2
                N_freqs = max(8, int(N_freqs_var.get()))
                freqs = np.linspace(1, nyq, N_freqs)
                widths = fs / (2 * np.pi * freqs)
                # Only keep widths/freqs with enough points in signal
                valid = (2 * widths >= 6) & (2 * widths < len(data_slice))
                widths = widths[valid]
                freqs = freqs[valid]
                if data_slice.size == 0 or widths.size == 0:
                    print("CWT: Data or widths invalid, skipping frame.")
                else:
                    cwtmatr = _ricker_cwt(data_slice, widths)
                    power_db = 10 * np.log10(np.abs(cwtmatr)**2 + 1e-12)
                    im_wavelet.set_data(power_db)
                    t1_cwt = _time.perf_counter()
                    # print(f'Scipy Ricker CWT calc: {t1_cwt - t0_cwt:.4f} s  [{power_db.shape}]')
                    im_wavelet.set_extent((0, power_db.shape[1], freqs[0], freqs[-1]))
                    im_wavelet.set_clim(vmin=wav_min, vmax=wav_max)
                    ax_wavelet.set_ylim(freqs[0], freqs[-1])
                    fig_ts.canvas.restore_region(bg_wavelet[0])
                    ax_wavelet.draw_artist(im_wavelet)
                    fig_ts.canvas.blit(ax_wavelet.bbox)

                
            # Spectrogram blit
            t0_spec = _time.perf_counter()
            if bg_spec[0] is not None:
                win      = win_size_var.get()
                noverlap = int(win * overlap_var.get() / 100)
                fs       = safe_get(fs_var, fs_design)
                ch       = channel_var.get() - 1
                # --- Only recompute spectrogram if params changed (not implemented in this chunk, but for further speed-up)
                f_s, t_s, Sxx = sps.spectrogram(
                    data_f[:, ch], fs=fs,
                    window='hamming', nperseg=win, noverlap=noverlap
                )
                Sxx_dB = 10 * np.log10(Sxx + 1e-12)
                im_sgram.set_data(Sxx_dB)
                im_sgram.set_extent((0, buf_size, 0, fs/2))
                ax_specgram.set_ylim(0, fs/2)
                im_sgram.set_clim(vmin=safe_get(Smin, -80.0), vmax=safe_get(Smax, 40.0))
                fig_ts.canvas.restore_region(bg_spec[0])
                ax_specgram.draw_artist(im_sgram)
                fig_ts.canvas.blit(ax_specgram.bbox)
                t1_spec = _time.perf_counter()
                #print(f'Spectrogram calc: {t1_spec - t0_spec:.4f} s  [{Sxx_dB.shape}]')
            # Spectrum blit
            t0_fft = _time.perf_counter()
            if bg_freq[0] is not None:
                Nwin = fft_var.get(); Nfft = Nwin*2
                win_h = np.hamming(Nwin)
                # win_h = 1
                fs    = safe_get(fs_var, fs_design)
                freqs = np.fft.rfftfreq(Nfft, d=1/fs)
                fig_ts.canvas.restore_region(bg_freq[0])
                for idx, (ln_s, ln_m, chk) in enumerate(zip(lines_spec, lines_max, check_vars)):
                    if not chk.get(): continue
                    seg = data_f[-Nwin:, idx]
                    mag = np.abs(np.fft.rfft(seg * win_h, n=Nfft))
                    spec= 20 * np.log10(mag + 1e-12)
                    ln_s.set_data(freqs, spec)
                    ax_freq.draw_artist(ln_s)
                    if maxhold_var.get():
                        mh_new = np.maximum(max_hold[idx] if max_hold[idx].size==spec.size else -np.inf, spec)
                        ln_m.set_visible(True)
                        ln_m.set_data(freqs, mh_new)
                        ax_freq.draw_artist(ln_m)
                        max_hold[idx] = mh_new
                    else:
                        ln_m.set_visible(False)
                fig_ts.canvas.blit(ax_freq.bbox)
                t1_fft = _time.perf_counter()
                #print(f'FFT plot calc: {t1_fft - t0_fft:.4f} s  [Nch={N_ch}]')

            fig_ts.canvas.flush_events()
            root.update_idletasks()
            root.update()
            # --- Reduce CPU use by adaptive sleep, but keep UI smooth ---
            if Server_sleeping_time > 0.0005:
                time.sleep(Server_sleeping_time)
            else:
                time.sleep(0.0005)
    except KeyboardInterrupt:
        pass
    finally:
        plt.close('all')
        print("Done.")

if __name__ == "__main__":
    main()
