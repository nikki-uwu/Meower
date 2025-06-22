import multiprocessing as mp
import numpy as np
import socket
import time
import scipy.signal as sps
import matplotlib.pyplot as plt

###############################################################################
# Helper functions
###############################################################################
def parse_frame(raw_data):
    """
    Given a single 27-byte frame from ADS1299,
    returns a 16-element list of int32 values.
    """
    parsed = [0]*16
    for i in range(16):
        j = 3 + (i * 3)
        if i >= 8:
            j += 3
        value = ((raw_data[j] << 16) |
                 (raw_data[j + 1] << 8) |
                 raw_data[j + 2])
        # Sign-extend 24-bit
        if value & 0x800000:
            value -= 1 << 24
        parsed[i] = value
    return parsed

def remove_50_100Hz_noise(signal_in, fs, Q=1.5):
    """
    Removes ~50 Hz and ~100 Hz noise from 'signal_in' using two cascaded IIR notches.
    """
    b50, a50 = sps.iirnotch(w0=50.0, Q=Q, fs=fs)
    b100, a100 = sps.iirnotch(w0=100.0, Q=Q, fs=fs)
    tmp = sps.filtfilt(b50, a50, signal_in)
    filtered = sps.filtfilt(b100, a100, tmp)
    return filtered

def compute_spectrogram(x, fs, window_size, step):
    """
    Compute the spectrogram of the 1D signal x (full frequency range).
    """
    noverlap = window_size - step
    f, t, Sxx = sps.spectrogram(
        x, fs=fs,
        window='hamming',
        nperseg=window_size,
        noverlap=noverlap
    )
    return f, t, Sxx

###############################################################################
# Background process (UDP reader) - unchanged
###############################################################################
def udp_reader_process(shared_dict, lock, sample_rate, buf_size, ip, port):
    """
    Background process that reads ADS1299 data via UDP and writes the most recent
    vector into a shared dictionary { 'latest': np.array(...) } with a lock.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((ip, port))
    sock.setblocking(False)
    print(f"[UDP Reader] Listening on {ip}:{port}")

    data_buffer = np.zeros((buf_size, 16), dtype=np.int32)

    try:
        while True:
            frames_received = []
            while True:
                try:
                    raw_data, addr = sock.recvfrom(1024)
                except BlockingIOError:
                    break
                frame = parse_frame(raw_data)
                frames_received.append(frame)

            if frames_received:
                num_new = len(frames_received)
                if num_new < buf_size:
                    data_buffer[:-num_new, :] = data_buffer[num_new:, :]
                else:
                    data_buffer[:] = 0
                start_idx = max(buf_size - num_new, 0)
                for i, fr in enumerate(frames_received[-buf_size:]):
                    data_buffer[start_idx + i, :] = fr

                data_buffer_diff = np.diff(data_buffer, axis=0, prepend=1)
                filtered_data = remove_50_100Hz_noise(
                    data_buffer_diff[:, 5],
                    fs=sample_rate
                )
                filtered_data_volts = filtered_data * (4.5 / (2**22))

                with lock:
                    shared_dict['latest'] = filtered_data_volts

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("[UDP Reader] Interrupted by user.")
    finally:
        sock.close()
        print("[UDP Reader] Socket closed. Exiting process.")
        
def flush_udp_buffer(sock):
    """
    Flushes the UDP buffer by reading all available packets until none remain.
    sock: A UDP socket object (socket.socket).
    """
    sock.setblocking(False)  # Ensure non-blocking mode
    while True:
        try:
            # Attempt to read any available data (buffer size of 1024 bytes)
            data, addr = sock.recvfrom(1024)
            # print(f"Flushed data: {data}")  # Optional: print what was flushed
        except BlockingIOError:
            # No more data to read, buffer is empty
            break
    sock.setblocking(True)  # Restore blocking mode if needed

###############################################################################
# Main process: listens for beacon, then starts reader and plots
###############################################################################
def main():
    # Configuration
    PC_IP        = "0.0.0.0"
    RECEIVE_PORT = 5001       # Port to receive data from ESP32
    SEND_PORT    = 5000          # Port to send commands to ESP32
    sample_rate  = 250
    time_window  = 16  # seconds
    buf_size     = time_window * sample_rate

    # Step 1: Listen for the ESP32's IP beacon
    print("Waiting for ESP32's IP beacon...")


    # Create receiving socket
    receive_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receive_sock.bind((PC_IP, RECEIVE_PORT))
    data, addr = receive_sock.recvfrom(1024)
    ESP_IP = addr[0]
    # Create sending socket
    send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    send_sock.sendto(('0' + ' ').encode(), (ESP_IP, SEND_PORT))
    # Clean buffer from beacon messages from ESP.
    # ESP stops Beacon as soon as we send it at least something
    flush_udp_buffer(receive_sock)
    
    
    
    





    # Setting up ADCs
    # Full reset at the beginning
    send_sock.sendto(('RESET' + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.5)
    
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
    send_sock.sendto(('SPI_SR 1 3 0x20 0x00 0x00' + ' ').encode(), (ESP_IP, SEND_PORT)) # Datasheet - 9.5.3.10 PREG, p.43
    time.sleep(0.1)
    data, addr = receive_sock.recvfrom(1024)
    print(' '.join(f'{b:02x}' for b in data))

    # Set reference and check it
    send_sock.sendto(('SPI_SR 3 3 0x43 0x00 0xE0' + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    flush_udp_buffer(receive_sock)

    send_sock.sendto(('SPI_SR 1 3 0x23 0x00 0x00' + ' ').encode(), (ESP_IP, SEND_PORT)) 
    time.sleep(0.1)
    data, addr = receive_sock.recvfrom(1024)
    print(' '.join(f'{b:02x}' for b in data))
    
    # Configuration 1 - Daisy-chain, reference clock, sample rate
    # bit 7        | 6                  | 5                 | 4        | 3        | 2   | 1   | 0
    # use Always 1 | Daisy-chain enable | Clock output mode | always 1 | always 0 | DR2 | DR1 | DR0
    #                 76543210
    #                 1XY10ZZZ
    Master_conf_1 = 0b10110110; # Daisy ON, Clock OUT ON,  250 SPS
    Slave_conf_1  = 0b10010110; # Daisy ON, Clock OUT OFF, 250 SPS
    
    send_sock.sendto(('SPI_SR 1 3 0x41 0x00 ' + hex(Master_conf_1) + ' ').encode(), (ESP_IP, SEND_PORT))
    send_sock.sendto(('SPI_SR 2 3 0x41 0x00 ' + hex(Slave_conf_1 ) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    flush_udp_buffer(receive_sock)
    
    send_sock.sendto(('SPI_SR 1 3 0x21 0x00 0x00' + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    data, addr = receive_sock.recvfrom(1024)
    print(' '.join(f'{b:02x}' for b in data))

    # Configuration 2 - Test signal settings
    # bit 7        | 6        | 5        | 4                   | 3        | 2                  | 1           0
    # use Always 1 | Always 1 | Always 0 | Test source ext/int | Always 0 | Test sig amplitude | Test sig freq
    #                 76543210
    #                 110X0YZZ
    Master_conf_2 = 0b11010000;
    Slave_conf_2  = 0b11010000;
    
    send_sock.sendto(('SPI_SR 1 3 0x42 0x00 ' + hex(Master_conf_2) + ' ').encode(), (ESP_IP, SEND_PORT))
    send_sock.sendto(('SPI_SR 2 3 0x42 0x00 ' + hex(Slave_conf_2 ) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    flush_udp_buffer(receive_sock)
    
    send_sock.sendto(('SPI_SR 1 3 0x22 0x00 0x00' + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    data, addr = receive_sock.recvfrom(1024)
    print(' '.join(f'{b:02x}' for b in data))

    # Configuration 3 - Reference and bias
    # bit 7                | 6        | 5        | 4         | 3                | 2                  | 1                      | 0 read only
    # use Power ref buffer | Always 1 | Always 1 | BIAS meas | BIAS ref ext/int | BIAS power Down/UP | BIAS sence lead OFF/ON | LEAD OFF status
    #                 76543210
    #                 X11YZMKR
    Master_conf_3 = 0b11111100;
    Slave_conf_3  = 0b01111000;

    send_sock.sendto(('SPI_SR 1 3 0x43 0x00 ' + hex(Master_conf_3) + ' ').encode(), (ESP_IP, SEND_PORT))
    send_sock.sendto(('SPI_SR 2 3 0x43 0x00 ' + hex(Slave_conf_3 ) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    flush_udp_buffer(receive_sock)
    
    send_sock.sendto(('SPI_SR 1 3 0x23 0x00 0x00 ' + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    data, addr = receive_sock.recvfrom(1024)
    print(' '.join(f'{b:02x}' for b in data))

    # Configuration 4 - Channels settings
    # bit 7                 | 6 5 4 | 3                | 2 1 0
    # use Power down On/Off | GAIN  | SRB2 open/closed | Channel input
    #                     76543210
    Channel_conf      = 0b01100000;
    Channel_conf_bias = 0b00000010;

    send_sock.sendto(('SPI_SR 3 3 0x45 0x00 ' + hex(Channel_conf_bias) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    send_sock.sendto(('SPI_SR 3 3 0x46 0x00 ' + hex(Channel_conf     ) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    send_sock.sendto(('SPI_SR 3 3 0x47 0x00 ' + hex(Channel_conf     ) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    send_sock.sendto(('SPI_SR 3 3 0x48 0x00 ' + hex(Channel_conf     ) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    send_sock.sendto(('SPI_SR 3 3 0x49 0x00 ' + hex(Channel_conf     ) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    send_sock.sendto(('SPI_SR 3 3 0x4A 0x00 ' + hex(Channel_conf     ) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    send_sock.sendto(('SPI_SR 3 3 0x4B 0x00 ' + hex(Channel_conf     ) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    send_sock.sendto(('SPI_SR 3 3 0x4C 0x00 ' + hex(Channel_conf     ) + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    
    
    # Start signal sampling
    send_sock.sendto(('START_CONT' + ' ').encode(), (ESP_IP, SEND_PORT))
    time.sleep(0.1)
    receive_sock.close()


    # Step 2: Start the background UDP reader for data frames
    manager = mp.Manager()
    shared_dict = manager.dict()
    shared_dict['latest'] = None
    lock = mp.Lock()

    reader_proc = mp.Process(
        target=udp_reader_process,
        args=(shared_dict, lock, sample_rate, buf_size, PC_IP, RECEIVE_PORT),
        daemon=True
    )
    reader_proc.start()

    ######################
    # Setup the figure
    ######################
    plt.ion()
    fig, (ax_time, ax_spec) = plt.subplots(2, 1, figsize=(8, 6), constrained_layout=True)
    fig.suptitle("Realtime Time-Domain + Spectrogram (Channel 5)")

    line_time, = ax_time.plot(np.zeros(buf_size), lw=1)
    ax_time.set_xlim(0, buf_size)
    ax_time.set_ylim(-0.025, 0.025)
    ax_time.set_title("Time-Domain")
    ax_time.set_xlabel("Samples")
    ax_time.set_ylabel("Amplitude [V]")
    ax_time.grid(True)

    ax_spec.set_title("Spectrogram")
    ax_spec.set_xlabel("Time [s]")
    ax_spec.set_ylabel("Frequency [Hz]")
    im = ax_spec.pcolormesh([0, 1], [0, 1], np.array([[0]]), shading='auto')

    plt.show(block=False)

    # Plot loop
    try:
        while True:
            if not plt.fignum_exists(fig.number):
                print("[Main] Plot window closed; exiting.")
                break

            with lock:
                new_data = shared_dict['latest']

            if new_data is not None:
                line_time.set_ydata(new_data)
                fvals, tvals, Sxx = compute_spectrogram(
                    new_data,
                    fs=sample_rate,
                    window_size=256,
                    step=16
                )
                Sxx_dB = 10 * np.log10(Sxx + 1e-12)
                ax_spec.cla()
                ax_spec.set_title("Spectrogram")
                ax_spec.set_xlabel("Time [s]")
                ax_spec.set_ylabel("Frequency [Hz]")
                im = ax_spec.pcolormesh(tvals, fvals, Sxx_dB, shading='auto')

            plt.pause(0.001)
            plt.draw()

    except KeyboardInterrupt:
        print("[Main] KeyboardInterrupt. Exiting.")
    finally:
        if reader_proc.is_alive():
            reader_proc.terminate()
        plt.close('all')
        print("[Main] Done.")

if __name__ == "__main__":
    main()