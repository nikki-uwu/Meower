import multiprocessing as mp
import numpy as np
import socket
import time
import scipy.signal as sps
import matplotlib.pyplot as plt
import struct
import tkinter as tk
from matplotlib.widgets import Slider


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
    send_sock.sendto(('SPI_SR M 3 0x41 0x00 0xB2' + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    flush_udp_buffer(receive_sock)
    send_sock.sendto(('SPI_SR S 3 0x41 0x00 0x92' + ' ').encode(), (ESP_IP, SEND_PORT))
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
        """
        Size window to half the screen and glue it to the bottom-right corner.
        """
        mng = fig.canvas.manager
        win = mng.window
        win.update_idletasks()

        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        taskbar = int(sh * 0.025)

        w, h = sw // 2, (sh - taskbar) // 2          # half-screen
        x, y = sw - w - margin_px, sh - h - taskbar
        win.geometry(f'{w}x{h}+{x}+{y}')

    def lock_window_to_top_right(fig, margin_px: int = 20):
        """
        Same width as the bottom-right helper but aligned to the *top*.
        """
        mng = fig.canvas.manager
        win = mng.window
        win.update_idletasks()

        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h   = sw // 2, sh // 2                      # half-screen width
        x, y   = sw - w - margin_px, margin_px
        win.geometry(f'{w}x{h}+{x}+{y}')

    # ── 16-channel figure (bottom-right) ────────────────────────────────────
    fig_ch, ax_ch = plt.subplots(constrained_layout=True)
    lock_window_to_bottom_right(fig_ch)

    fig_ch.suptitle("Time-Domain (16 channels)")
    ax_ch.set_xlim(0, buf_size)
    ax_ch.set_ylim(-0, 4)
    ax_ch.set_xlabel("Samples")
    ax_ch.set_ylabel("Amp [V]")
    ax_ch.grid(True)

    xdata      = np.arange(buf_size)
    lines_ch   = [ax_ch.plot(xdata, np.zeros(buf_size), lw=1, animated=True)[0]
                  for _ in range(N_ch)]
    bg_ch      = [None]

    def _on_draw_ch(evt):
        bg_ch[0] = fig_ch.canvas.copy_from_bbox(fig_ch.bbox)
    fig_ch.canvas.mpl_connect('draw_event', _on_draw_ch)
    fig_ch.canvas.draw()                              # first clean background

    # ── Δt figure (top-right, same width) ───────────────────────────────────
    fig_dt, ax_dt = plt.subplots(constrained_layout=True)
    lock_window_to_top_right(fig_dt)

    fig_dt.suptitle("Δt between frames  (µs)")
    ax_dt.set_xlim(0, buf_size)
    ax_dt.set_ylim(1800, 2200)           # adjust if needed
    ax_dt.set_xlabel("Samples")
    ax_dt.set_ylabel("Δt [µs]")
    ax_dt.grid(True)

    line_dt, = ax_dt.plot(xdata, np.zeros(buf_size), lw=1,
                          color='tab:red', animated=True)
    bg_dt = [None]

    def _on_draw_dt(evt):
        bg_dt[0] = fig_dt.canvas.copy_from_bbox(fig_dt.bbox)
    fig_dt.canvas.mpl_connect('draw_event', _on_draw_dt)
    fig_dt.canvas.draw()

    # ── tiny Tk window (battery read-out) ───────────────────────────────────
    root = tk.Tk()
    root.title("Battery V")
    root.resizable(False, False)
    lbl = tk.Label(root, font=("Consolas", 18), width=12, anchor='e')
    lbl.pack(padx=10, pady=8)

    # ───────────────────────────  MAIN LOOP  ────────────────────────────────
    pkt = 0
    previous_time = time.time()
    try:
        while True:

            if not plt.fignum_exists(fig_ch.number):
                print("Plot window closed; exiting.")
                break

            with lock:
                data_  = shared_dict.get('latest', None)
                batt_  = shared_dict_bat.get('latest', None)
                timer_ = shared_dict_timer.get('latest', None)

            if data_ is None or timer_ is None or timer_.size == 0:
                time.sleep(0.001)
                continue


            current_time = time.time();
            if ((current_time - previous_time) > 20):
                send_sock.sendto(('floof' + ' ').encode(), (ESP_IP, SEND_PORT))
                previous_time = current_time
            
            # 1-D timer view → Δt in µs
            t      = np.asarray(timer_, dtype=np.int64).ravel()
            dt_us  = np.diff(t, prepend=t[0]) * 8

            # simple DC-offset removal (table)
            data = data_ - np.array([
                -4.0459e-04, -5.6858e-04, -4.4878e-04, -4.8903e-04,
                -4.9321e-04, -5.3085e-04, -5.5320e-04, -6.4267e-04,
                -4.3635e-04, -4.5699e-04, -5.0553e-04, -4.4478e-04,
                -4.9772e-04, -4.1176e-04, -4.2540e-04, -4.6826e-04])

            # ----- fast blit update : 16-channel figure ---------------------
            if bg_ch[0] is not None:
                fig_ch.canvas.restore_region(bg_ch[0])
                for ln, y in zip(lines_ch, data.T):
                    ln.set_ydata(y)
                    ax_ch.draw_artist(ln)
                fig_ch.canvas.blit(fig_ch.bbox)

            # ----- fast blit update : Δt figure ----------------------------
            if bg_dt[0] is not None:
                fig_dt.canvas.restore_region(bg_dt[0])
                line_dt.set_ydata(dt_us)
                ax_dt.draw_artist(line_dt)
                fig_dt.canvas.blit(fig_dt.bbox)

            # flush both canvases
            fig_ch.canvas.flush_events()
            fig_dt.canvas.flush_events()

            # battery label
            if batt_ is not None:
                lbl.config(text=f"{batt_:6.2f} V")
                root.update_idletasks()

            # optional multicast of latest sample
            eeg16 = data[-1].astype(np.float64)
            aux7  = np.zeros(7)
            udp_frame = np.concatenate((eeg16, aux7,
                                        [pkt & 0xFF, time.time(), 0.0]))
            sock.sendto(udp_frame.astype('<f8').tobytes(), (IP, PORT))
            pkt = (pkt + 1) & 0xFF

            time.sleep(Server_sleeping_time)

    except KeyboardInterrupt:
        print("KeyboardInterrupt. Exiting.")
    finally:
        plt.close('all')
        print("Done.")


if __name__ == "__main__":
    main()