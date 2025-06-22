import multiprocessing as mp
import numpy as np
import socket
import time
import scipy.signal as sps
import matplotlib.pyplot as plt
import struct
import tkinter as tk


# Processing config
# --------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------
# Sampling frequency
sample_rate  = 250 
N_ch         = 16
time_window  = 16  # seconds
buf_size     = time_window * sample_rate

# No decrease load lets slow down server a little bit allowing to try to pull new data 1/4 of our sample rate
Server_sleeping_time = 1 / sample_rate / 4 

# Build the array of starting indices for each of the 16 channels
IDX_ADC_SAMPLES = np.concatenate([3 + 3*np.arange(8), 3 + 3*(np.arange(8, N_ch)) + 3]).astype(np.int32)

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




# Helper functions
# --------------------------------------------------------------------------------------------
# --------------------------------------------------------------------------------------------
def parse_frame(raw_data):
    """
    Given a single 27-byte frame from ADS1299,
    returns a 16-element NumPy array of int32 values.
    
    Note:
      - The first 3 bytes are considered static and skipped.
      - For i in [0..7], we read at byte index: 3 + 3*i
      - For i in [8..15], we add an extra 3 => byte index: 3 + 3*i + 3
      - This indexing extends out to index 53 for i=15, 
        so in practice it uses up to 54 bytes total.
      - Sign-extend is applied to each 24-bit value (highest bit => negative).
    """
    
    # If we have no lead detection, then first 3 bytes for each blockof 27 bytes should start from 
    # [190 0 0 ...... 192 0 0 ......]
    
    # Interpret raw_data as an array of unsigned bytes
    raw_arr = np.frombuffer(raw_data, dtype = np.uint8).astype(np.int32)
    
    # Prepare an output array of 16 signed 32-bit integers
    parsed = np.zeros(N_ch, dtype = np.int32)
    
    # Extract the three bytes for each channel
    high = (raw_arr[IDX_ADC_SAMPLES]     << 16)
    mid  = (raw_arr[IDX_ADC_SAMPLES + 1] <<  8)
    low  =  raw_arr[IDX_ADC_SAMPLES + 2]
    
    # Combine into a 24-bit value
    value_24 = (high | mid | low).astype(np.int32)

    # Sign-extend 24-bit if the top bit is set
    negative_mask = (value_24 & 0x800000) != 0
    value_24[negative_mask] -= (1 << 24)

    parsed[:] = value_24
    return parsed

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
            data, addr = sock.recvfrom(1024)
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
def udp_reader_process(shared_dict, shared_dict_bat, lock, sample_rate, buf_size, ip, port):
    """
    Background process that reads ADS1299 data via UDP, parses frames,
    and writes the most recent filtered column into shared_dict['latest'].
    Expects 54-byte frames for 16 channels (two ADS1299s).
    Reads ONLY one packet per loop iteration (if any).
    """
    
    global timer

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((ip, port))
    sock.setblocking(False)
    print(f"[UDP Reader] Listening on {ip}:{port}")

    # Pre-allocate buffer: shape = (buf_size, N_ch)
    data_buffer = np.zeros((buf_size, N_ch), dtype = np.int32)
    mean_buffer = np.zeros((buf_size, N_ch), dtype = np.int32)

    try:
        while True:
            
            # Attempt to read exactly one packet
            try:
                raw_data, addr = sock.recvfrom(1024)
            except BlockingIOError:
                # No new packet arrived; do nothing this loop
                pass
            else:
                # We got exactly one UDP packet
                parsed_frame = parse_frame(raw_data[:54])
                
                
                # Read Battery data
                OFFSET = 54            # first battery byte
                FMT    = '<f'          # match endianness of sender
                
                need = OFFSET + struct.calcsize(FMT)   # here: 54 + 4 = 58
                if len(raw_data) < need:
                    raise ValueError(f"need ≥{need} bytes, got {len(raw_data)}")
                
                battery_v = struct.unpack_from(FMT, raw_data, OFFSET)[0]

                # Shift data buffer up by one row
                data_buffer = np.roll(data_buffer, -1, axis = 0)
                mean_buffer = np.roll(mean_buffer, -1, axis = 0)
                
                # Place the new frame in the last row
                data_buffer[-1] = parsed_frame
                mean_buffer[-1] = np.mean(data_buffer, axis = 0)

                # Diff filter to get rid of DC offset
                # devide by two because 
                # data_buffer_diff = np.diff(data_buffer, axis = 0, prepend=data_buffer[:1]) / 2
                
                # Filter 50 and 100 Hz
                filtered_data = remove_50_100Hz_noise(data_buffer)
                
                # Scale to get Volts
                filtered_data_volts = data_buffer * (4.5 / (2**23))

                # Update shared dictionary
                with lock:
                    shared_dict['latest'] = filtered_data_volts
                    shared_dict_bat['latest'] = battery_v
                    
            # Small time delay to decrease cpu load since udp reader is fast enought
            time.sleep(1 / sample_rate / 2)

    except KeyboardInterrupt:
        print("[UDP Reader] Interrupted by user.")
    finally:
        sock.close()
        print("[UDP Reader] Socket closed. Exiting process.")




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
    print("Waiting for ESP32's IP beacon...")
    data, addr = receive_sock.recvfrom(1024)
    ESP_IP = addr[0]
    print("ESP32's IP is " + ESP_IP)

    # Setting up ADCs
    # Full reset at the beginning
    send_sock.sendto(('RESET' + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(1)
    
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
    # Master_conf_1 = 0b10110110; # Daisy ON, Clock OUT ON,  250 SPS
    # Slave_conf_1  = 0b10010110; # Daisy ON, Clock OUT OFF, 250 SPS
    
    # CONFIGURATION 2
    # Test signal settings
    # bit 7        | 6        | 5        | 4                   | 3        | 2                  | 1           0
    # use Always 1 | Always 1 | Always 0 | Test source ext/int | Always 0 | Test sig amplitude | Test sig freq
    #            76543210
    #            110X0YZZ
    #            11010101 Signal is gen internally, amplitude twice more then usual, pulses are 2 time faster than usual
    CONFIG_2 = 0b11010101;
    
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
    lock = mp.Lock()

    reader_proc = mp.Process(
        target=udp_reader_process,
        args=(shared_dict, shared_dict_bat, lock, sample_rate, buf_size, PC_IP, RECEIVE_PORT),
        daemon=True
    )
    reader_proc.start()











    plt.ion()
    # Create 16 stacked subplots
    fig, ax = plt.subplots(constrained_layout = True)
    lock_window_to_bottom_right(fig)
    fig.suptitle("Time-Domain (16 Channels)")
    ax.set_xlim(0, buf_size)
    ax.set_ylim(-0, 5.5)  # adjust Y-limits as needed
    ax.grid(True)
    ax.set_xlabel("Samples")
    ax.set_ylabel("Amp [V]")
    
    # Create lines (one per channel)
    xdata = np.arange(buf_size)
    lines = []
    for n in range(N_ch):
        line, = ax.plot(xdata, np.zeros(buf_size), lw=1, animated=True)
        lines.append(line)
    
    # We'll keep the "clean" background in a mutable container 
    # so we can update it via the draw_event callback
    background = [None]
    
    def on_draw(event):
        """
        Callback triggered after a full figure draw (including resize).
        We copy the updated "clean" background for subsequent blit draws.
        """
        background[0] = fig.canvas.copy_from_bbox(fig.bbox)
    
    # Connect the draw_event so we recapture background after any full draw
    fig.canvas.mpl_connect('draw_event', on_draw)
    
    # Force an initial draw so on_draw is called and the background is captured
    fig.canvas.draw()
    plt.show(block=False)
    
    # --- tiny window ------------------------------------------------
    root = tk.Tk()
    root.title("Battery V")
    root.resizable(False, False)
    
    lbl = tk.Label(root,
                   font=("Consolas", 18),
                   width=12,
                   anchor='e')
    lbl.pack(padx=10, pady=8)
    
    try:
        while True:
            # Check if the figure was closed
            if not plt.fignum_exists(fig.number):
                print("Plot window closed; exiting.")
                break
    
            # Retrieve data from your shared dictionary
            with lock:
                new_data = shared_dict.get('latest', None)  # shape: (buf_size, N_ch)
                battery  = shared_dict_bat.get('latest', None)
    
            if new_data is not None:
                # If we have a valid background, do a blit-based update
                if background[0] is not None:
                    
                    # print(np.mean(new_data, axis = 0))
                    data = new_data - np.array([-0.00040459, -0.00056858, -0.00044878, -0.00048903, -0.00049321, -0.00053085,
                     -0.0005532,  -0.00064267, -0.00043635, -0.00045699, -0.00050553, -0.00044478,
                     -0.00049772, -0.00041176, -0.0004254,  -0.00046826])
                    
                    # new_data = new_data - [-0.00040452 -0.00056878 -0.00044889 -0.00048948 -0.00049335 -0.00053081
                    #  -0.00055296 -0.00064272 -0.00043661 -0.00045694 -0.00050559 -0.00044473
                    #  -0.00049774 -0.00041214 -0.00042575 -0.00046807];
                    
                    lbl.config(text=f"{battery:6.2f} V")
                    # Restore the clean background
                    fig.canvas.restore_region(background[0])
    
                    # Update each channel’s line
                    for ch in range(N_ch):
                        lines[ch].set_ydata(data[:, ch]*2)
                        ax.draw_artist(lines[ch])
    
                    # Blit the updated region
                    fig.canvas.blit(fig.bbox)
                    fig.canvas.flush_events()
                else:
                    # If background is None, do a full redraw as a fallback
                    fig.canvas.draw()
                    fig.canvas.flush_events()
    
    except KeyboardInterrupt:
        print("KeyboardInterrupt. Exiting.")
    finally:
    #plt.ioff()
        print("Done.")


if __name__ == "__main__":
    main()