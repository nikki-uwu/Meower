import multiprocessing as mp
import numpy as np
import socket
import time
import scipy.signal as sps
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt
import struct
import tkinter as tk
from scipy.signal.windows import chebwin
from scipy.signal import firwin2
import time as _time

# ----------------------------- Config and Net -----------------------------
sample_rate  = 500 
N_ch         = 16
time_window  = 8
buf_size     = time_window * sample_rate
Server_sleeping_time = 1 / sample_rate / 40
IDX_ADC_SAMPLES = np.concatenate([3*np.arange(16)]).astype(np.int32)

Q = 1.5
b50 , a50  = sps.iirnotch( 50.0, Q, sample_rate)
b100, a100 = sps.iirnotch(100.0, Q, sample_rate)
b_comb     = np.convolve(b50, b100)
a_comb     = np.convolve(a50, a100)

PC_IP        = "0.0.0.0"
CTRL_PORT    = 5000 # Control/command port on ESP32
DATA_PORT    = 5001 # Data stream port (from ESP32 to PC)
IP           = "225.1.1.1"
PORT         = 6677

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)

def parse_frame(raw_data: bytes) -> np.ndarray:
    if len(raw_data) != 48:
        raise ValueError(f"parse_frame() needs 48 B, got {len(raw_data)} B")
    raw_arr = np.frombuffer(raw_data, dtype=np.uint8).astype(np.int32)
    high = (raw_arr[IDX_ADC_SAMPLES]     << 16)
    mid  = (raw_arr[IDX_ADC_SAMPLES + 1] <<  8)
    low  =  raw_arr[IDX_ADC_SAMPLES + 2]
    value_24 = (high | mid | low).astype(np.int32)
    neg = (value_24 & 0x800000) != 0
    value_24[neg] -= (1 << 24)
    return value_24

def remove_50_100Hz_noise(signal_in):
    return sps.filtfilt(b_comb, a_comb, signal_in, axis = 0)

def flush_udp_buffer(sock):
    sock.setblocking(False)
    while True:
        try:
            sock.recvfrom(65535)
        except BlockingIOError:
            break
    sock.setblocking(True)
    
def send_cmd_sync(sock, msg, addr, timeout=0.5, expected_prefix=None, max_retries=3):
    for attempt in range(max_retries):
        flush_udp_buffer(sock)
        sock.sendto(msg.encode(), addr)
        sock.settimeout(timeout)
        try:
            reply, _ = sock.recvfrom(256)
            text = reply.decode('ascii', errors='ignore').strip()
            print(f"RX < {text}")
            if expected_prefix is None or text.startswith(expected_prefix):
                return text
            else:
                print("Unexpected reply, will retry")
        except socket.timeout:
            print(f"Timeout waiting for reply (try {attempt+1}/{max_retries})")
    raise RuntimeError("No valid reply after retries")
    
def lock_window_to_bottom_right(fig):
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

def udp_reader_process(shared_dict, shared_bat, shared_tim,
                       lock, sample_rate, buf_size, ip, port):
    DEBUG = False
    log   = (lambda *a, **k: None) if not DEBUG else (lambda *a, **k: print("[UDP]", *a, **k))
    FR_LEN   = 52
    MIN_LEN  = FR_LEN
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((ip, port))
    sock.setblocking(False)
    data_buf  = np.zeros((buf_size, N_ch),    np.int32)
    time_buf  = np.zeros(buf_size,           np.uint32)
    scale = 4.5 / (2**23)
    prev_time = time.time()
    print("UDP reader started")
    while True:
        try:
            try:
                raw, _ = sock.recvfrom(2048)
            except BlockingIOError:
                time.sleep(0.0005)
                continue
            except Exception as e:
                print(f"[UDP ERROR] socket.recvfrom: {e}")
                time.sleep(0.005)
                continue

            L = len(raw)
            if L < MIN_LEN:
                continue
            frames = (L - 4) // FR_LEN
            if frames == 0:
                continue

            batt = struct.unpack_from('<f', raw, frames * FR_LEN)[0]

            for n in range(frames):
                base = n * FR_LEN
                try:
                    frame = parse_frame(raw[base : base + 48])
                    ts = struct.unpack_from('<I', raw, base + 48)[0]
                except Exception as e:
                    print(f"[UDP ERROR] frame parse failed: {e}")
                    continue  # skip this frame

                data_buf[:-1] = data_buf[1:]
                time_buf[:-1] = time_buf[1:]
                data_buf[-1]  = frame
                time_buf[-1]  = ts

            # Update shared memory only once per packet
            with lock:
                shared_dict['latest'] = (data_buf * scale).copy()
                shared_bat ['latest'] = batt
                shared_tim ['latest'] = time_buf.copy()
                
            time.sleep(0.0001)

        except Exception as e:
            print(f"[UDP ERROR] outer loop: {e}")
            time.sleep(0.01)
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

# --------- Filter toggling helpers ---------
def send_filter_command(name, on, ESP_IP, ctrl_sock):
    cmd = f"sys {name}_{'on' if on else 'off'}"
    print("Sending CMD:", repr(cmd))
    reply = send_cmd_sync(ctrl_sock, cmd, (ESP_IP, CTRL_PORT), expected_prefix="OK:")

def set_all_filters(state, ESP_IP, receive_sock):
    send_filter_command('filters', state, ESP_IP, receive_sock)
def set_filter_equalizer(state, ESP_IP, receive_sock):
    send_filter_command('filter_equalizer', state, ESP_IP, receive_sock)
def set_filter_dc(state, ESP_IP, receive_sock):
    send_filter_command('filter_dc', state, ESP_IP, receive_sock)
def set_filter_5060(state, ESP_IP, receive_sock):
    send_filter_command('filter_5060', state, ESP_IP, receive_sock)
def set_filter_100120(state, ESP_IP, receive_sock):
    send_filter_command('filter_100120', state, ESP_IP, receive_sock)
def check_command_replies(ctrl_sock, print_every=0.5):
    """Non-blocking read of command port; prints all available replies."""
    import select
    static = getattr(check_command_replies, "_static", {"last_print": 0})
    now = time.time()
    if now - static["last_print"] < print_every:
        return
    static["last_print"] = now
    check_command_replies._static = static

    # Read ALL pending messages in the queue
    while True:
        ready, _, _ = select.select([ctrl_sock], [], [], 0)
        if not ready:
            break
        try:
            data, addr = ctrl_sock.recvfrom(512)
            msg = data.decode("ascii", errors="replace").strip()
            print(f"[CTRL RECV] {msg}")
            if msg.startswith("[FLOOF]"):
                print(f"[FW STATUS] {msg}")
        except Exception as e:
            print(f"[CTRL RECV] decode error: {e}")
            
def send_integer_command(cmd_name, var, ESP_IP, ctrl_sock):
    value = var.get()
    if isinstance(value, (int, float)) and value >= 0:
        msg = f"sys {cmd_name} {value}"
        print(f"Sending CMD: {msg!r}")
        try:
            ctrl_sock.settimeout(5.0)
            ctrl_sock.sendto(msg.encode(), (ESP_IP, CTRL_PORT))
            reply, _ = ctrl_sock.recvfrom(256)
            text = reply.decode('ascii', errors='ignore').strip()
            print(f"RX < {text}")
        except socket.timeout:
            print("No reply received.")
        except Exception as e:
            print("Error receiving reply:", e)
    else:
        print("Value must be positive integer.")
        
        

        
        
def main():
    # ─── 1. Open sockets ─────────────────────────────────────────────
    ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ctrl_sock.bind((PC_IP, CTRL_PORT))
    ctrl_sock.settimeout(5.0)
    
    
    
    
    
    def send_cmd_and_print(cmd):
        ctrl_sock.sendto(cmd.encode(), (ESP_IP, CTRL_PORT))
        try:
            reply, _ = ctrl_sock.recvfrom(256)
            txt = reply.decode('ascii', errors='ignore').strip()
            print("RX <", repr(txt))
        except Exception as e:
            print("No reply:", e)
    
    

    
    
    
    
    
    flush_udp_buffer(ctrl_sock)
    print("Waiting for ESP32's IP beacon …")
    data, addr = ctrl_sock.recvfrom(256)
    ESP_IP = addr[0]
    print("ESP32's IP is", ESP_IP)
    ctrl_sock.sendto(b"sys adc_reset ", (ESP_IP, CTRL_PORT))

    ctrl_sock.sendto(b'WOOF_WOOF', (ESP_IP, CTRL_PORT))
    # flush_udp_buffer(ctrl_sock)
    # for reg in (0x20, 0x23):
    #     cmd = f"spi M 3 0x{reg:02X} 0x00 0x00 "
    #     ctrl_sock.sendto(cmd.encode(), (ESP_IP, CTRL_PORT))
    #     time.sleep(0.1)
    #     data, _ = ctrl_sock.recvfrom(256)
    #     print("RX <", ' '.join(f'{b:02x}' for b in data))
    # ctrl_sock.sendto(b"spi M 3 0x41 0x00 0xB6 ", (ESP_IP, CTRL_PORT))
    # time.sleep(0.1)
    # ctrl_sock.sendto(b"spi S 3 0x41 0x00 0x96 ", (ESP_IP, CTRL_PORT))
    # time.sleep(0.1)
    # flush_udp_buffer(ctrl_sock)
    # CONFIG_2 = 0xD4
    # cmd = f"spi B 3 0x42 0x00 0x{CONFIG_2:02X} "
    # ctrl_sock.sendto(cmd.encode(), (ESP_IP, CTRL_PORT))
    # time.sleep(0.1)
    # flush_udp_buffer(ctrl_sock)
    CHANNEL_CONF = 0x08
    for reg in range(0x45, 0x4D):
        cmd = f"spi B 3 0x{reg:02X} 0x00 0x{CHANNEL_CONF:02X} "
        ctrl_sock.sendto(cmd.encode(), (ESP_IP, CTRL_PORT))
        time.sleep(0.1)
    # # CHANNEL_CONF = 0x68
    # # cmd = f"spi M 3 0x45 0x00 0x{CHANNEL_CONF:02X} "
    # # ctrl_sock.sendto(cmd.encode(), (ESP_IP, CTRL_PORT))
    # # time.sleep(0.1)
    # MASTER_CONF_3 = 0xEC
    # SLAVE_CONF_3  = 0xE8
    # ctrl_sock.sendto(f"spi M 3 0x43 0x00 0x{MASTER_CONF_3:02X} ".encode(), (ESP_IP, CTRL_PORT))
    # ctrl_sock.sendto(f"spi S 3 0x43 0x00 0x{SLAVE_CONF_3:02X} ".encode(),  (ESP_IP, CTRL_PORT))
    # time.sleep(0.1)
    # ctrl_sock.sendto(b"spi B 3 0x4D 0x00 0x02 ", (ESP_IP, CTRL_PORT))
    # ctrl_sock.sendto(b"spi B 3 0x4E 0x00 0x00 ", (ESP_IP, CTRL_PORT))
    # #ctrl_sock.sendto(f"spi B 3 0x4E 0x00 0x00 ".encode(), (ESP_IP, CTRL_PORT))
    # #time.sleep(0.1)
    # flush_udp_buffer(ctrl_sock)
    # ctrl_sock.sendto(b"spi M 3 0x23 0x00 0x00 ", (ESP_IP, CTRL_PORT))
    # time.sleep(0.1)
    # data, _ = ctrl_sock.recvfrom(256)
    # print("RX <", ' '.join(f'{b:02x}' for b in data))

    ctrl_sock.sendto(b'WOOF_WOOF', (ESP_IP, CTRL_PORT))

    # Start continuous streaming
    ctrl_sock.sendto(b"sys start_cnt ", (ESP_IP, CTRL_PORT))
    time.sleep(0.1)



    msg = "sys xx"
    ctrl_sock.sendto(msg.encode(), (ESP_IP, CTRL_PORT))
    try:
        reply, _ = ctrl_sock.recvfrom(256)
        print("RX <", reply)
    except Exception as e:
        print("Error:", e)


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
        args=(shared_dict, shared_dict_bat, shared_dict_timer, lock, sample_rate, buf_size, PC_IP, DATA_PORT),
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
    nyq = fs_design / 2
    N_freqs = 256
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
        vmax=0
    )
    ax_freq.set_title("Spectrum (16 channels)")
    ax_freq.set_xlabel("Frequency [Hz]")
    ax_freq.set_ylabel("Power [dB]")
    ax_freq.set_ylim(-150, -10)
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
    
    # --- FILTER PANEL --- now row=1
    filter_names = ["ALL", "Equalizer", "DC Block", "50/60 Hz", "100/120 Hz"]
    filter_vars = []
    
    filter_frame = tk.LabelFrame(cf, text="Filter toggles", padx=5, pady=5)
    filter_frame.grid(row=1, column=0, columnspan=4, sticky='we', pady=(5,7))
    
    def filter_callback(idx):
        name = filter_names[idx]
        state = filter_vars[idx].get()
        print(f"[C-STYLE] {name}: {int(state)}")
        if name == "ALL":
            for i in range(1, len(filter_names)):
                filter_vars[i].set(state)
                filter_callback(i)
            set_all_filters(state, ESP_IP, ctrl_sock)
        elif name == "Equalizer":
            set_filter_equalizer(state, ESP_IP, ctrl_sock)
        elif name == "DC Block":
            set_filter_dc(state, ESP_IP, ctrl_sock)
        elif name == "50/60 Hz":
            set_filter_5060(state, ESP_IP, ctrl_sock)
        elif name == "100/120 Hz":
            set_filter_100120(state, ESP_IP, ctrl_sock)
    
    for i, name in enumerate(filter_names):
        var = tk.BooleanVar(root, value=False)
        cb = tk.Checkbutton(filter_frame, text=name, variable=var,
                            command=lambda idx=i: filter_callback(idx))
        cb.grid(row=0, column=i, sticky='w')
        filter_vars.append(var)
    
    # --- Numeric parameter entry boxes after filter toggles ---
    # --- New: Number boxes after filters for DigitalGain, NetworkFreq, DCcutoffFreq ---
    tk.Label(cf, text="Digital gain:").grid(row=2, column=0, sticky='e')
    gain_var = tk.IntVar(root, 1)
    gain_entry = tk.Entry(cf, textvariable=gain_var, width=6)
    gain_entry.grid(row=2, column=1)
    
    tk.Label(cf, text="Network Freq:").grid(row=2, column=2, sticky='e')
    netfreq_var = tk.IntVar(root, 50)
    netfreq_entry = tk.Entry(cf, textvariable=netfreq_var, width=6)
    netfreq_entry.grid(row=2, column=3)
    
    tk.Label(cf, text="DC Cutoff Freq:").grid(row=3, column=0, sticky='e')
    dccutoff_var = tk.IntVar(root, 8.0)
    dccutoff_entry = tk.Entry(cf, textvariable=dccutoff_var, width=6)
    dccutoff_entry.grid(row=3, column=1)
    
    def send_cmd_and_print(cmd):
        ctrl_sock.sendto(cmd.encode(), (ESP_IP, CTRL_PORT))
        try:
            reply, _ = ctrl_sock.recvfrom(256)
            txt = reply.decode('ascii', errors='ignore').strip()
            print("RX <", repr(txt))
        except Exception as e:
            print("No reply:", e)
    
    def on_gain_change(event=None):
        val = gain_var.get()
        if str(val).isdigit() and int(val) >= 0:
            cmd = f"sys DigitalGain {val}"
            print(f"Sending CMD: {repr(cmd)}")
            send_cmd_and_print(cmd)
    gain_entry.bind('<Return>', on_gain_change)
    gain_entry.bind('<FocusOut>', on_gain_change)
    
    def on_netfreq_change(event=None):
        val = netfreq_var.get()
        if str(val).isdigit() and int(val) >= 0:
            cmd = f"sys NetworkFreq {val}"
            print(f"Sending CMD: {repr(cmd)}")
            send_cmd_and_print(cmd)
    netfreq_entry.bind('<Return>', on_netfreq_change)
    netfreq_entry.bind('<FocusOut>', on_netfreq_change)
    
    def on_dccutoff_change(event=None):
        val = dccutoff_var.get()
        try:
            val_f = float(val)
            if val_f in (0.5, 1, 2, 4, 8):
                cmd = f"sys DCcutoffFreq {val_f}"
                print(f"Sending CMD: {repr(cmd)}")
                send_cmd_and_print(cmd)
        except ValueError:
            pass  # Invalid input; do nothing

    
    # --- FFT and all controls start at row=5 (after 3 parameter boxes) ---
    tk.Label(cf, text="FFT pts:").grid(row=5, column=0, sticky='e')
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
             command=on_fft_change, length=200).grid(row=5, column=1, columnspan=3, sticky='we')
    
    tk.Label(cf, text="Fs (Hz):").grid(row=6, column=0, sticky='e')
    fs_var = tk.DoubleVar(root, 250.0)
    fs_entry = tk.Entry(cf, textvariable=fs_var, width=6)
    fs_entry.grid(row=6, column=1, sticky='w')
    fs_entry.bind('<Return>', lambda e: on_fft_change())
    fs_entry.bind('<FocusOut>', lambda e: on_fft_change())
    
    tk.Label(cf, text="Vmin:").grid(row=7, column=0, sticky='e')
    Vmin = tk.DoubleVar(root, -0.5)
    tk.Entry(cf, textvariable=Vmin, width=6).grid(row=7, column=1)
    tk.Label(cf, text="Vmax:").grid(row=7, column=2, sticky='e')
    Vmax = tk.DoubleVar(root, 0.5)
    tk.Entry(cf, textvariable=Vmax, width=6).grid(row=7, column=3)
    
    tk.Label(cf, text="Dmin:").grid(row=8, column=0, sticky='e')
    Dmin = tk.DoubleVar(root, 3900.0)
    tk.Entry(cf, textvariable=Dmin, width=6).grid(row=8, column=1)
    tk.Label(cf, text="Dmax:").grid(row=8, column=2, sticky='e')
    Dmax = tk.DoubleVar(root, 4100.0)
    tk.Entry(cf, textvariable=Dmax, width=6).grid(row=8, column=3)
    
    tk.Label(cf, text="Pmin:").grid(row=9, column=0, sticky='e')
    Pmin = tk.DoubleVar(root, -150)
    tk.Entry(cf, textvariable=Pmin, width=6).grid(row=9, column=1)
    tk.Label(cf, text="Pmax:").grid(row=9, column=2, sticky='e')
    Pmax = tk.DoubleVar(root, 0)
    tk.Entry(cf, textvariable=Pmax, width=6).grid(row=9, column=3)
    
    tk.Label(cf, text="Smin:").grid(row=10, column=0, sticky='e')
    Smin = tk.DoubleVar(root, -80.0)
    tk.Entry(cf, textvariable=Smin, width=6).grid(row=10, column=1)
    tk.Label(cf, text="Smax:").grid(row=10, column=2, sticky='e')
    Smax = tk.DoubleVar(root, 0)
    tk.Entry(cf, textvariable=Smax, width=6).grid(row=10, column=3)
    
    tk.Label(cf, text="Win size:").grid(row=11, column=0, sticky='e')
    win_size_var = tk.IntVar(root, 128)
    tk.Scale(cf, from_=32, to=buf_size, orient='horizontal',
             variable=win_size_var, length=200).grid(row=11, column=1, columnspan=3, sticky='we')
    
    tk.Label(cf, text="Cheb Atten (dB):").grid(row=12, column=0, sticky='e')
    cheb_atten_var = tk.DoubleVar(root, 100.0)
    tk.Scale(cf, from_=40, to=180, resolution=1, orient='horizontal',
         variable=cheb_atten_var, length=200).grid(row=12, column=1, columnspan=3, sticky='we')
    
    tk.Label(cf, text="Overlap %:").grid(row=13, column=0, sticky='e')
    overlap_var = tk.IntVar(root, 50)
    tk.Scale(cf, from_=0, to=90, orient='horizontal',
             variable=overlap_var, length=200).grid(row=13, column=1, columnspan=3, sticky='we')
    
    tk.Label(cf, text="Spect Ch:").grid(row=14, column=0, sticky='e')
    channel_var = tk.IntVar(root, 1)
    tk.Spinbox(cf, from_=1, to=N_ch, textvariable=channel_var, width=4).grid(row=14, column=1)
    maxhold_var = tk.BooleanVar(root, True)
    tk.Checkbutton(cf, text="Show Max-Hold", variable=maxhold_var)\
        .grid(row=14, column=2, columnspan=2, sticky='w')
    
    def update_ylims():
        ax_dt.set_ylim(safe_get(Dmin, 3900), safe_get(Dmax, 4100))
        ax_time.set_ylim(safe_get(Vmin, -0.5), safe_get(Vmax, 0.5))
        ax_freq.set_ylim(safe_get(Pmin, -80), safe_get(Pmax, 40))
        fig_ts.canvas.draw()
        bg_dt[0]   = fig_ts.canvas.copy_from_bbox(ax_dt.bbox)
        bg_time[0] = fig_ts.canvas.copy_from_bbox(ax_time.bbox)
        bg_freq[0] = fig_ts.canvas.copy_from_bbox(ax_freq.bbox)
    tk.Button(cf, text="Update Limits", command=update_ylims)\
        .grid(row=15, column=0, columnspan=4, pady=(5,10))
    
    check_vars = []
    for i in range(N_ch):
        var = tk.BooleanVar(root, value=(i==0))
        tk.Checkbutton(cf, text=f"Ch{i+1}", variable=var)\
            .grid(row=16 + i//4, column=i%4, sticky='w')
        check_vars.append(var)
    
    tk.Button(cf, text="Reset Max", command=lambda: [mh.fill(-np.inf) for mh in max_hold])\
        .grid(row=20, column=0, columnspan=4, pady=(5,0))
    
    tk.Label(cf, text="Wav Overlap %:").grid(row=21, column=0, sticky='e')
    wav_overlap_var = tk.IntVar(root, 99)
    tk.Scale(cf, from_=0, to=99, orient='horizontal', variable=wav_overlap_var, length=200)\
        .grid(row=21, column=1, columnspan=3, sticky='we')
    tk.Label(cf, text="Wav Pow min:").grid(row=22, column=0, sticky='e')
    wav_min_var = tk.DoubleVar(root, -60.0)
    tk.Entry(cf, textvariable=wav_min_var, width=6).grid(row=22, column=1)
    tk.Label(cf, text="Wav Pow max:").grid(row=22, column=2, sticky='e')
    wav_max_var = tk.DoubleVar(root, 0.0)
    tk.Entry(cf, textvariable=wav_max_var, width=6).grid(row=22, column=3)
    tk.Label(cf, text="Wav Freqs:").grid(row=23, column=0, sticky='e')
    N_freqs_var = tk.IntVar(root, 256)
    N_freqs_var.trace_add('write', lambda *a: update_wavelet_image())
    tk.Scale(cf, from_=8, to=256, orient='horizontal', variable=N_freqs_var, length=200).grid(row=23, column=1, columnspan=3, sticky='we')
    on_fft_change()

    
    # --- FILTER PANEL --- now row=1
    # Filter GUI panel states
    # --- FILTER PANEL --- now row=1
    filter_names = ["ALL", "Equalizer", "DC Block", "50/60 Hz", "100/120 Hz"]
    filter_vars = []

    filter_frame = tk.LabelFrame(cf, text="Filter toggles", padx=5, pady=5)
    filter_frame.grid(row=1, column=0, columnspan=4, sticky='we', pady=(5,7))

    # --- Numeric parameter entry boxes after filter toggles ---
    param_names = [
        ("Digital gain",    "DigitalGain"),
        ("Network Freq",    "NetworkFreq"),
        ("DC Cutoff Freq",  "DCcutoffFreq")
    ]
    param_vars = []
    for idx, (label, field) in enumerate(param_names):
        var = tk.IntVar(root, 0)
        param_vars.append(var)
        tk.Label(cf, text=label + ":").grid(row=2+idx, column=0, sticky='e')
        entry = tk.Entry(cf, textvariable=var, width=8, validate='all')
        entry.grid(row=2+idx, column=1, sticky='w')
        btn = tk.Button(cf, text="Send", width=6,
            command=lambda v=var, f=field: send_integer_command(f, v, ESP_IP, ctrl_sock))
        btn.grid(row=2+idx, column=2, sticky='w')

    def filter_callback(idx):
        name = filter_names[idx]
        state = filter_vars[idx].get()
        print(f"[C-STYLE] {name}: {int(state)}")
        # Direct, explicit C-style logic
        if name == "ALL":
            for i in range(1, len(filter_names)):
                filter_vars[i].set(state)
                filter_callback(i)
            set_all_filters(state, ESP_IP, ctrl_sock)
        elif name == "Equalizer":
            set_filter_equalizer(state, ESP_IP, ctrl_sock)
        elif name == "DC Block":
            set_filter_dc(state, ESP_IP, ctrl_sock)
        elif name == "50/60 Hz":
            set_filter_5060(state, ESP_IP, ctrl_sock)
        elif name == "100/120 Hz":
            set_filter_100120(state, ESP_IP, ctrl_sock)

    for i, name in enumerate(filter_names):
        var = tk.BooleanVar(root, value=False)
        cb = tk.Checkbutton(filter_frame, text=name, variable=var,
                            command=lambda idx=i: filter_callback(idx))
        cb.grid(row=0, column=i, sticky='w')
        filter_vars.append(var)


    
    
    
        
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
                dt_us = 4000 - t * 8
            if batt_ is not None:
                v = np.asarray(batt_).ravel()[0] if hasattr(batt_, '__iter__') else batt_
                batt_label.config(text=f"{v:.2f} V")

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
                    window=chebwin(win, cheb_atten_var.get()), nperseg=win, noverlap=noverlap
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
                win_h = chebwin(Nwin, cheb_atten_var.get())
                # win_h = 1
                fs    = safe_get(fs_var, fs_design)
                freqs = np.fft.rfftfreq(Nfft, d=1/fs)
                fig_ts.canvas.restore_region(bg_freq[0])
                for idx, (ln_s, ln_m, chk) in enumerate(zip(lines_spec, lines_max, check_vars)):
                    if not chk.get(): continue
                    seg = data_f[-Nwin:, idx]
                    mag = np.abs(np.fft.rfft(seg / Nwin * win_h, n=Nfft))
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
            check_command_replies(ctrl_sock)
            now = time.time()
            if (now - prev_time) > 0.005:
                #print(f"[PY] Sending floof at {now:.2f}")
                ctrl_sock.sendto(b'WOOF_WOOF', (ESP_IP, CTRL_PORT))
                #ctrl_sock.sendto(b'sys erase_flash', (ESP_IP, CTRL_PORT))
                prev_time = now
            root.update_idletasks()
            root.update()
            # --- Reduce CPU use by adaptive sleep, but keep UI smooth ---
            if Server_sleeping_time > 1:
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