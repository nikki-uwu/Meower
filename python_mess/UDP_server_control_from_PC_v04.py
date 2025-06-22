import multiprocessing as mp
import numpy as np
import socket
import time
import scipy.signal as sps
from scipy import signal
import matplotlib.pyplot as plt
import struct
import tkinter as tk
from matplotlib.widgets import Slider, CheckButtons, Button
from scipy.signal import firwin2


# Processing config
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
# --------------------------------------------------------------------------
# safer 48-byte → 16-channel converter
# --------------------------------------------------------------------------
def parse_frame(raw_data: bytes) -> np.ndarray:
    """Return one 16-int32 frame.  **Requires exactly 54 bytes.**"""
    if len(raw_data) != 48:
        raise ValueError(f"parse_frame() needs 54 B, got {len(raw_data)} B")
    raw_arr = np.frombuffer(raw_data, dtype=np.uint8).astype(np.int32)

    # 24-bit chunks → sign-extended int32
    high = (raw_arr[IDX_ADC_SAMPLES]     << 16)
    mid  = (raw_arr[IDX_ADC_SAMPLES + 1] <<  8)
    low  =  raw_arr[IDX_ADC_SAMPLES + 2]
    value_24 = (high | mid | low).astype(np.int32)

    neg = (value_24 & 0x800000) != 0
    value_24[neg] -= (1 << 24)
    return value_24          # already shape (16,)




# FIlter 50 and 100 Hz from signal
def remove_50_100Hz_noise(signal_in):
    """
    Removes ~50 Hz and ~100 Hz noise from 'signal_in' using a
    single, combined IIR notch filter (4th order).
    """
    filtered = sps.filtfilt(b_comb, a_comb, signal_in, axis = 0)
    return filtered

# Just clean UDP buffer from all messages which are storred inside at the moment
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
    
# Force plot window be at the right bottom corner
def lock_window_to_bottom_right(fig):
    """
    Resize the TkAgg window for the given matplotlib figure to half the screen size,
    then reposition it so that its bottom-right corner aligns with the screen's bottom-right.
    
    Parameters:
        fig: matplotlib.figure.Figure
            The figure whose Tk window will be resized and repositioned.
    """
    # Access the Tk window from the figure's canvas manager
    mng = fig.canvas.manager
    window = mng.window

    # Force an update of window properties
    window.update_idletasks()

    # Get full screen dimensions
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    
    # Get rid of task bar
    task_bar_height = round(screen_height*0.025);

    # Set new window size to half of the screen dimensions
    new_width  = screen_width // 2
    new_height = (screen_height - task_bar_height) // 2

    # Calculate the top-left coordinates so the window's bottom-right corner lands at (screen_width, screen_height)
    x = screen_width - new_width
    y = screen_height - new_height - task_bar_height
    y = y - round(screen_height*0.02)

    # Define a function to update the window geometry after a short delay
    def set_geometry():
        window.geometry(f"{new_width}x{new_height}+{x}+{y}")
    # Schedule the geometry update shortly after the window is drawn
    window.after(10, set_geometry)
    
    # Draw plot so it gets into proper position
    fig.canvas.draw()
    plt.show()




# Background process (UDP reader)
# --------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------
# robust UDP reader (runs in its own Process)
# --------------------------------------------------------------------------
def udp_reader_process(shared_dict, shared_bat, shared_tim,
                       lock, sample_rate, buf_size, ip, port):

    import traceback, logging
    DEBUG = True                                 # flip to False to silence prints
    log   = (lambda *a, **k: None) if not DEBUG else \
            (lambda *a, **k: print("[UDP]", *a, **k))

    FR_LEN   = 52                # 48 ADC + 4 timestamp
    MIN_LEN  = FR_LEN            # shortest thing we accept

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((ip, port))
    sock.setblocking(False)
    log(f"Reader up on {ip}:{port}")

    # rolling buffers
    data_buf  = np.zeros((buf_size, N_ch),    np.int32)
    time_buf  = np.zeros(buf_size,           np.uint32)

    while True:
        try:
            try:
                raw, _ = sock.recvfrom(2048)          # non-blocking
            except BlockingIOError:
                time.sleep(0.0005)                    # yield CPU
                continue

            L = len(raw)
            if L < MIN_LEN:
                log(f"Drop tiny pkt {L} B")
                continue

            frames = (L - 4) // FR_LEN               # how many full frames?
            if frames == 0:
                log(f"Pkt {L} B has header only (?) – skipped")
                continue
            if frames * FR_LEN + 4 != L:
                log(f"Pkt {L} B not multiple of 58 → trunc at {frames} frames")

            # battery float is the *last* 4 bytes
            batt = struct.unpack_from('<f', raw, frames * FR_LEN)[0]

            # slide window
            for n in range(frames):
                base = n * FR_LEN

                try:
                    frame = parse_frame(raw[base : base + 48])
                except Exception as e:
                    log("Bad frame:", e)
                    continue

                ts = struct.unpack_from('<I', raw, base + 48)[0]

                data_buf  = np.roll(data_buf, -1, axis=0)
                time_buf  = np.roll(time_buf, -1)
                data_buf[-1] = frame
                time_buf[-1] = ts

            # --- share latest snapshot with GUI / main process ------------
            with lock:
                shared_dict['latest']   = (data_buf * (4.5 / (2**23))).copy()
                shared_bat ['latest']   = batt
                shared_tim ['latest']   = time_buf.copy()

        except Exception as e:
            log("!! reader error – packet skipped:", e)
            traceback.print_exc()
            continue                    # stay alive & keep listening





# Main process: listens for beacon, then starts reader and plots
# --------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------
def main():

    # Create receiving socket
    receive_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receive_sock.bind((PC_IP, RECEIVE_PORT))
    
    # Create sending socket
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # ESP sends beacons or if it;s already running it sends data so the idea is to get at least
    # one message from it and pull IP
    flush_udp_buffer(receive_sock)
    print("Waiting for ESP32's IP beacon...")
    data, addr = receive_sock.recvfrom(2048)
    ESP_IP = addr[0]
    print("ESP32's IP is " + ESP_IP)

    # Setting up ADCs
    # Full reset at the beginning
    send_sock.sendto(('RESET' + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(2)
    
    # Clean buffer from beacon messages from ESP.
    # ESP stops Beacon as soon as we send it at least something
    flush_udp_buffer(receive_sock)
    
    # RESET IS INCLUDED INTO ADC FULL RESET
    # Reset Registers to Default Values for both ADCs
    # send_sock.sendto(('SPI_SR 3 1 0x06' + ' ').encode(), (ESP_IP, SEND_PORT)) # Datasheet - 9.5.3 SPI command definitions, p.40
    # time.sleep(0.1)
    # flush_udp_buffer(receive_sock)

    # SDATAC IS INCLUDED INTO RESET AND STOP CONTINIOUS MODE
    # Stop continious data mode (SDATAC)
    # send_sock.sendto(('SPI_SR 3 1 0x10' + ' ').encode(), (ESP_IP, SEND_PORT)) # Datasheet - 9.5.3 SPI command definitions, p.40
    # time.sleep(0.1)
    # flush_udp_buffer(receive_sock)

    # STOP COMMAND IS ALSO INCLUDED IN RESET OR STOP_CONT
    # Stop conversion just in case (STOP)
    # send_sock.sendto(('SPI_SR 3 1 0x0A' + ' ').encode(), (ESP_IP, SEND_PORT)) # Datasheet - 9.5.3 SPI command definitions, p.40
    # time.sleep(0.1)
    # flush_udp_buffer(receive_sock)

    # Read ID
    send_sock.sendto(('SPI_SR M 3 0x20 0x00 0x00' + ' ').encode(), (ESP_IP, SEND_PORT)) # Datasheet - 9.5.3.10 PREG, p.43
    time.sleep(0.1)
    data, addr = receive_sock.recvfrom(1024)
    print(' '.join(f'{b:02x}' for b in data))

    # REFERENCE IS SET IN RESET FUNCTION BY DEFAULT
    # Check reference
    send_sock.sendto(('SPI_SR M 3 0x23 0x00 0x00' + ' ').encode(), (ESP_IP, SEND_PORT)) 
    time.sleep(0.1)
    data, addr = receive_sock.recvfrom(1024)
    print(' '.join(f'{b:02x}' for b in data))
    
    # CONFIGURATION 1
    # DONE ON ESP SIDE
    # Then we need to setup up clock for slave and update reference signal again, otherwise
    # slave is in different state comparing to master
    # Configuration 1 - Daisy-chain, reference clock, sample rate
    # bit 7        | 6                  | 5                 | 4        | 3        | 2   | 1   | 0
    # use Always 1 | Daisy-chain enable | Clock output mode | always 1 | always 0 | DR2 | DR1 | DR0
    #                   76543210
    #                   1XY10ZZZ
    # Master_conf_1 = 0b10110010; # Daisy ON, Clock OUT ON,  250 SPS
    # Slave_conf_1  = 0b10010010; # Daisy ON, Clock OUT OFF, 250 SPS
    time.sleep(0.1)
    send_sock.sendto(('SPI_SR M 3 0x41 0x00 0xB5' + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    flush_udp_buffer(receive_sock)
    send_sock.sendto(('SPI_SR S 3 0x41 0x00 0x95' + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    flush_udp_buffer(receive_sock)
    
    # CONFIGURATION 2
    # Test signal settings
    # bit 7        | 6        | 5        | 4                   | 3        | 2                  | 1           0
    # use Always 1 | Always 1 | Always 0 | Test source ext/int | Always 0 | Test sig amplitude | Test sig freq
    #            76543210
    #            110X0YZZ
    #            11010101 Signal is gen internally, amplitude twice more then usual, pulses are 2 time faster than usual
    CONFIG_2 = 0b11010100;
    
    send_sock.sendto(('SPI_SR B 3 0x42 0x00 ' + hex(CONFIG_2) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    flush_udp_buffer(receive_sock)
    send_sock.sendto(('SPI_SR M 3 0x22 0x00 0x00' + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    data, addr = receive_sock.recvfrom(1024)
    print(' '.join(f'{b:02x}' for b in data))
    
    # CONFIGURATION CHANNELS
    # Channels settings
    # bit 7                 | 6 5 4 | 3                | 2 1 0
    # use Power down On/Off | GAIN  | SRB2 open/closed | Channel input
    #                76543210
    Channel_conf = 0b00001000;

    send_sock.sendto(('SPI_SR B 3 0x45 0x00 ' + hex(Channel_conf) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    send_sock.sendto(('SPI_SR B 3 0x46 0x00 ' + hex(Channel_conf) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    send_sock.sendto(('SPI_SR B 3 0x47 0x00 ' + hex(Channel_conf) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    send_sock.sendto(('SPI_SR B 3 0x48 0x00 ' + hex(Channel_conf) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    send_sock.sendto(('SPI_SR B 3 0x49 0x00 ' + hex(Channel_conf) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    send_sock.sendto(('SPI_SR B 3 0x4A 0x00 ' + hex(Channel_conf) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    send_sock.sendto(('SPI_SR B 3 0x4B 0x00 ' + hex(Channel_conf) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    send_sock.sendto(('SPI_SR B 3 0x4C 0x00 ' + hex(Channel_conf) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    
    # CONFIGURATION 3
    # Reference and bias
    # bit 7                | 6        | 5        | 4         | 3                | 2                  | 1                      | 0 read only
    # use Power ref buffer | Always 1 | Always 1 | BIAS meas | BIAS ref ext/int | BIAS power Down/UP | BIAS sence lead OFF/ON | LEAD OFF status
    # THIS ONE IS A MUST 1 |
    # FOR MY DESIGN        |
    #                 76543210
    #                 111YZMKR
    Master_conf_3 = 0b11101100;
    Slave_conf_3  = 0b11101000;

    send_sock.sendto(('SPI_SR M 3 0x43 0x00 ' + hex(Master_conf_3) + ' ').encode(), (ESP_IP, SEND_PORT))
    send_sock.sendto(('SPI_SR S 3 0x43 0x00 ' + hex(Slave_conf_3 ) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    flush_udp_buffer(receive_sock)
    
    send_sock.sendto(('SPI_SR M 3 0x23 0x00 0x00 ' + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    data, addr = receive_sock.recvfrom(1024)
    print(' '.join(f'{b:02x}' for b in data))
    
    """
    # SAME FOR BASE SETTINGS FOR CONFIG 1
    # It's in reset because we want both ADCs to be ready to go
    # Configuration 1 - Daisy-chain, reference clock, sample rate
    # bit 7        | 6                  | 5                 | 4        | 3        | 2   | 1   | 0
    # use Always 1 | Daisy-chain enable | Clock output mode | always 1 | always 0 | DR2 | DR1 | DR0
    #                 76543210
    #                 1XY10ZZZ
    Master_conf_1 = 0b10110110; # Daisy ON, Clock OUT ON,  250 SPS
    Slave_conf_1  = 0b10010110; # Daisy ON, Clock OUT OFF, 250 SPS
    send_sock.sendto(('SPI_SR 1 3 0x41 0x00 ' + hex(Master_conf_1) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    send_sock.sendto(('SPI_SR 2 3 0x41 0x00 ' + hex(Slave_conf_1 ) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    flush_udp_buffer(receive_sock)
    
    send_sock.sendto(('SPI_SR 1 3 0x21 0x00 0x00' + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    data, addr = receive_sock.recvfrom(1024)
    print(' '.join(f'{b:02x}' for b in data))
    
    # when we have clock on slave we can try to set bias again
    send_sock.sendto(('SPI_SR 3 3 0x43 0x00 0xE0' + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    flush_udp_buffer(receive_sock)
    send_sock.sendto(('SPI_SR 1 3 0x23 0x00 0x00' + ' ').encode(), (ESP_IP, SEND_PORT)) 
    time.sleep(0.1)
    data, addr = receive_sock.recvfrom(1024)
    print(' '.join(f'{b:02x}' for b in data))
    """


    
    
    # Start signal sampling
    send_sock.sendto(('START_CONT' + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    receive_sock.close()
    
    #flush_udp_buffer(receive_sock)
    #raw_data, addr = receive_sock.recvfrom(1024)
    #parsed_frame = parse_frame(raw_data)
    #raw_arr = np.frombuffer(raw_data, dtype = np.uint8).astype(np.int32)

    # Step 2: Start the background UDP reader for data frames
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
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    











    # ──────────────────────────  PLOT WINDOWS  ──────────────────────────────
    def lock_window_to_bottom_right(fig, margin_px: int = 20):
        mng, win = fig.canvas.manager, fig.canvas.manager.window
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        taskbar = int(sh * 0.025)
        w, h = sw // 2, (sh - taskbar) // 2
        x, y = sw - w - margin_px, sh - h - taskbar
        win.geometry(f'{w}x{h}+{x}+{y}')
    
    # ────────────────────────  FILTER SETUP  ─────────────────────────────────
    from scipy.signal import firwin2
    fs_design = 500.0
    nyq = fs_design / 2
    f_dense = np.linspace(0, nyq, 256)
    H_sinc3 = np.sinc(f_dense / fs_design)**3
    H_inv   = np.ones_like(H_sinc3)
    H_inv[1:] = 1.0 / H_sinc3[1:]
    norm_freqs = f_dense / nyq
    h_eq = firwin2(numtaps=7, freq=norm_freqs, gain=H_inv, window='hamming')
    
    # ────────────────────────  COMMON UTILS  ─────────────────────────────────
    def safe_get(var, default):
        try:
            return float(var.get())
        except:
            return default
    
    # ────────────────────────  COMBINED FIGURE SETUP  ──────────────────────────
    fig_ts, (ax_dt, ax_time, ax_specgram, ax_freq) = plt.subplots(4, 1, constrained_layout=True)
    lock_window_to_bottom_right(fig_ts)
    
    # Δt subplot
    ax_dt.set_title("Sample Δt (μs)")
    ax_dt.set_xlim(0, buf_size)
    ax_dt.set_ylim(1800, 2200)
    ax_dt.set_ylabel("Δt [μs]")
    ax_dt.grid(True)
    
    # Time-domain subplot
    ax_time.set_title("Time-Domain (16 channels)")
    ax_time.set_xlim(0, buf_size)
    ax_time.set_ylim(0.4, 1.6)
    ax_time.set_ylabel("Amp [V]")
    ax_time.grid(True)
    
    # Spectrogram subplot
    ax_specgram.set_title("Spectrogram (Ch1)")
    ax_specgram.set_xlim(0, buf_size)
    ax_specgram.set_ylim(0, fs_design/2)
    ax_specgram.set_xlabel("Sample Index")
    ax_specgram.set_ylabel("Frequency [Hz]")
    ax_specgram.grid(True)
    
    # initialize spectrogram image for live update
    im_sgram = ax_specgram.imshow(
        np.zeros((len(f_dense), buf_size)),
        origin='lower',
        aspect='auto',
        extent=(0, buf_size, 0, fs_design/2),
        vmin=-80,
        vmax=40
    )
    
    # Spectrum subplot
    ax_freq.set_title("Spectrum (16 channels)")
    ax_freq.set_xlabel("Frequency [Hz]")
    ax_freq.set_ylabel("Power [dB]")
    ax_freq.set_ylim(-80, 40)
    ax_freq.grid(True)
    
    # Animated lines & background buffers
    xdata      = np.arange(buf_size)
    lines_dt   = ax_dt.plot(xdata, np.zeros(buf_size), lw=1, animated=True)[0]
    lines_time = [ax_time.plot(xdata, np.zeros(buf_size), lw=1, animated=True)[0] for _ in range(N_ch)]
    lines_spec = [ax_freq.plot([], [], lw=1, animated=True)[0] for _ in range(N_ch)]
    lines_max  = [ax_freq.plot([], [], lw=1, ls='--', animated=True,
                   color=lines_spec[i].get_color())[0] for i in range(N_ch)]
    bg_dt, bg_time, bg_spec, bg_freq = [None], [None], [None], [None]
    max_hold = [np.full(1, -np.inf) for _ in range(N_ch)]
    
    # Capture backgrounds (except specgram)
    fig_ts.canvas.mpl_connect('draw_event', lambda ev: bg_dt.__setitem__(0, fig_ts.canvas.copy_from_bbox(ax_dt.bbox)))
    fig_ts.canvas.mpl_connect('draw_event', lambda ev: bg_time.__setitem__(0, fig_ts.canvas.copy_from_bbox(ax_time.bbox)))
    fig_ts.canvas.mpl_connect('draw_event', lambda ev: bg_spec.__setitem__(0, fig_ts.canvas.copy_from_bbox(ax_specgram.bbox)))
    fig_ts.canvas.mpl_connect('draw_event', lambda ev: bg_freq.__setitem__(0, fig_ts.canvas.copy_from_bbox(ax_freq.bbox)))
    fig_ts.canvas.draw()
    
    # ───────────────────────────  TKINTER CONTROLS  ───────────────────────────
    root = tk.Tk()
    root.title("Controls")
    cf = tk.Frame(root); cf.pack(padx=10, pady=10)
    
    # Battery
    batt_label = tk.Label(cf, text="Battery: N/A")
    batt_label.grid(row=0, column=0, columnspan=4, sticky='w')
    
    # FFT points slider (default 500)
    tk.Label(cf, text="FFT pts:").grid(row=1, column=0, sticky='e')
    fft_var = tk.IntVar(root, 500)
    def on_fft_change(val=None):
        Nwin = fft_var.get(); Nfft = Nwin*2
        fs = safe_get(fs_var, fs_design)
        freqs = np.fft.rfftfreq(Nfft, d=1/fs)
        zero = np.zeros_like(freqs)
        for ln in lines_spec: ln.set_data(freqs, zero)
        for ln in lines_max: ln.set_data(freqs, zero)
        ax_freq.set_xlim(0, fs/2)
        fig_ts.canvas.draw()
    tk.Scale(cf, from_=32, to=buf_size, orient='horizontal', variable=fft_var,
             command=on_fft_change, length=200).grid(row=1, column=1, columnspan=3, sticky='we')
    
    # Sampling rate entry (default 500)
    tk.Label(cf, text="Fs (Hz):").grid(row=2, column=0, sticky='e')
    fs_var = tk.DoubleVar(root, 500.0)
    fs_entry = tk.Entry(cf, textvariable=fs_var, width=6)
    fs_entry.grid(row=2, column=1, sticky='w')
    fs_entry.bind('<Return>', lambda e: on_fft_change())
    fs_entry.bind('<FocusOut>', lambda e: on_fft_change())
    
    # Voltage Y-limits (0.4–1.6)
    tk.Label(cf, text="Vmin:").grid(row=3, column=0, sticky='e')
    Vmin = tk.DoubleVar(root, 0.4)
    tk.Entry(cf, textvariable=Vmin, width=6).grid(row=3, column=1)
    tk.Label(cf, text="Vmax:").grid(row=3, column=2, sticky='e')
    Vmax = tk.DoubleVar(root, 1.6)
    tk.Entry(cf, textvariable=Vmax, width=6).grid(row=3, column=3)
    
    # Δt Y-limits (1800–2200)
    tk.Label(cf, text="Dmin:").grid(row=4, column=0, sticky='e')
    Dmin = tk.DoubleVar(root, 1800.0)
    tk.Entry(cf, textvariable=Dmin, width=6).grid(row=4, column=1)
    tk.Label(cf, text="Dmax:").grid(row=4, column=2, sticky='e')
    Dmax = tk.DoubleVar(root, 2200.0)
    tk.Entry(cf, textvariable=Dmax, width=6).grid(row=4, column=3)
    
    # Spectrum Y-limits (–80–40)
    tk.Label(cf, text="Pmin:").grid(row=5, column=0, sticky='e')
    Pmin = tk.DoubleVar(root, -80.0)
    tk.Entry(cf, textvariable=Pmin, width=6).grid(row=5, column=1)
    tk.Label(cf, text="Pmax:").grid(row=5, column=2, sticky='e')
    Pmax = tk.DoubleVar(root, 40.0)
    tk.Entry(cf, textvariable=Pmax, width=6).grid(row=5, column=3)
    
    # Spectrogram dB limits (–80–40)
    tk.Label(cf, text="Smin:").grid(row=6, column=0, sticky='e')
    Smin = tk.DoubleVar(root, -80.0)
    tk.Entry(cf, textvariable=Smin, width=6).grid(row=6, column=1)
    tk.Label(cf, text="Smax:").grid(row=6, column=2, sticky='e')
    Smax = tk.DoubleVar(root, 40.0)
    tk.Entry(cf, textvariable=Smax, width=6).grid(row=6, column=3)
    
    # Window size slider
    tk.Label(cf, text="Win size:").grid(row=7, column=0, sticky='e')
    win_size_var = tk.IntVar(root, 128)
    tk.Scale(cf, from_=32, to=buf_size, orient='horizontal',
             variable=win_size_var, length=200).grid(row=7, column=1, columnspan=3, sticky='we')
    
    # Overlap % slider
    tk.Label(cf, text="Overlap %:").grid(row=8, column=0, sticky='e')
    overlap_var = tk.IntVar(root, 50)
    tk.Scale(cf, from_=0, to=90, orient='horizontal',
             variable=overlap_var, length=200).grid(row=8, column=1, columnspan=3, sticky='we')
    
    # Spectrogram channel selector
    tk.Label(cf, text="Spect Ch:").grid(row=9, column=0, sticky='e')
    channel_var = tk.IntVar(root, 1)
    tk.Spinbox(cf, from_=1, to=N_ch, textvariable=channel_var, width=4).grid(row=9, column=1)
    
    # Show Max-Hold checkbox
    maxhold_var = tk.BooleanVar(root, True)
    tk.Checkbutton(cf, text="Show Max-Hold", variable=maxhold_var)\
        .grid(row=9, column=2, columnspan=2, sticky='w')
    
    # Update Limits button (centered)
    def update_ylims():
        ax_dt.set_ylim(safe_get(Dmin, 1800), safe_get(Dmax, 2200))
        ax_time.set_ylim(safe_get(Vmin, 0.4), safe_get(Vmax, 1.6))
        ax_freq.set_ylim(safe_get(Pmin, -80), safe_get(Pmax, 40))
        fig_ts.canvas.draw()
        bg_dt[0]   = fig_ts.canvas.copy_from_bbox(ax_dt.bbox)
        bg_time[0] = fig_ts.canvas.copy_from_bbox(ax_time.bbox)
        bg_freq[0] = fig_ts.canvas.copy_from_bbox(ax_freq.bbox)
    
    tk.Button(cf, text="Update Limits", command=update_ylims)\
        .grid(row=10, column=0, columnspan=4, pady=(5,10))
    
    # Channel checkboxes
    check_vars = []
    for i in range(N_ch):
        var = tk.BooleanVar(root, value=(i==0))
        tk.Checkbutton(cf, text=f"Ch{i+1}", variable=var)\
            .grid(row=11 + i//4, column=i%4, sticky='w')
        check_vars.append(var)
    
    # Reset Max button (below checkboxes)
    tk.Button(cf, text="Reset Max", command=lambda: [mh.fill(-np.inf) for mh in max_hold])\
        .grid(row=15, column=0, columnspan=4, pady=(5,0))
    
    # Initial spectrum draw
    on_fft_change()
    
    # ───────────────────────────  MAIN LOOP  ────────────────────────────────
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
    
            # Δt calculation (fixed truth check)
            if timer_ is not None and len(timer_) > 0:
                t     = np.asarray(timer_, np.int64).ravel()
                dt_us = np.diff(t, prepend=t[0]) * 8
    
            # Update battery label
            if batt_ is not None:
                v = np.asarray(batt_).ravel()[0] if hasattr(batt_, '__iter__') else batt_
                batt_label.config(text=f"{v:.2f} V")
    
            # Ping ESP32
            now = time.time()
            if now - prev_time > 20:
                send_sock.sendto(b'floof ', (ESP_IP, SEND_PORT))
                prev_time = now
    
            # DC-offset removal + filter
            offsets = np.array([
                -4.0459e-04, -5.6858e-04, -4.4878e-04, -4.8903e-04,
                -4.9321e-04, -5.3085e-04, -5.5320e-04, -6.4267e-04,
                -4.3635e-04, -4.5699e-04, -5.0553e-04, -4.4478e-04,
                -4.9772e-04, -4.1176e-04, -4.2540e-04, -4.6826e-04
            ])
            data   = np.asarray(data_) - offsets
            data_f = np.zeros_like(data)
            for idx in range(N_ch):
                data_f[:, idx] = np.convolve(data[:, idx], h_eq, mode='same')
    
            # Δt blit
            if bg_dt[0] is not None:
                fig_ts.canvas.restore_region(bg_dt[0])
                lines_dt.set_ydata(dt_us)
                ax_dt.draw_artist(lines_dt)
                fig_ts.canvas.blit(ax_dt.bbox)
    
            # Time blit
            if bg_time[0] is not None:
                fig_ts.canvas.restore_region(bg_time[0])
                for ln, y, chk in zip(lines_time, data_f.T, check_vars):
                    if chk.get():
                        ln.set_ydata(y)
                        ax_time.draw_artist(ln)
                fig_ts.canvas.blit(ax_time.bbox)
    
            # Spectrogram blit (live, full width)
            if bg_spec[0] is not None:
                win      = win_size_var.get()
                noverlap = int(win * overlap_var.get() / 100)
                fs       = safe_get(fs_var, fs_design)
                ch       = channel_var.get() - 1
                f_s, t_s, Sxx = sps.spectrogram(
                    data_f[:, ch], fs=fs,
                    window='hamming', nperseg=win, noverlap=noverlap
                )
                Sxx_dB = 10 * np.log10(Sxx + 1e-12)
                im_sgram.set_data(Sxx_dB)
                im_sgram.set_extent((0, buf_size, 0, fs/2))
                im_sgram.set_clim(vmin=safe_get(Smin, -80.0), vmax=safe_get(Smax, 40.0))
                fig_ts.canvas.restore_region(bg_spec[0])
                ax_specgram.draw_artist(im_sgram)
                fig_ts.canvas.blit(ax_specgram.bbox)
    
            # Spectrum blit
            if bg_freq[0] is not None:
                Nwin = fft_var.get(); Nfft = Nwin*2
                win_h = np.hamming(Nwin)
                fs    = safe_get(fs_var, fs_design)
                freqs = np.fft.rfftfreq(Nfft, d=1/fs)
                fig_ts.canvas.restore_region(bg_freq[0])
                for idx, (ln_s, ln_m, chk) in enumerate(zip(lines_spec, lines_max, check_vars)):
                    if not chk.get(): continue
                    seg = data_f[-Nwin:, idx] - data_f[-Nwin:, idx].mean()
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
    
            fig_ts.canvas.flush_events()
            root.update_idletasks()
            root.update()
            time.sleep(Server_sleeping_time)
    
    except KeyboardInterrupt:
        pass
    finally:
        plt.close('all')
        print("Done.")









if __name__ == "__main__":
    main()