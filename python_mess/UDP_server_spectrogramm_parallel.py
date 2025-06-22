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

    # First remove 50 Hz, then 100 Hz
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
# Background process (UDP reader) that writes the latest data to a shared dict
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

    # Prepare a ring buffer for storing frames
    data_buffer = np.zeros((buf_size, 16), dtype=np.int32)

    try:
        while True:
            frames_received = []
            # Non-blocking read from UDP
            while True:
                try:
                    raw_data, addr = sock.recvfrom(1024)
                except BlockingIOError:
                    break
                frame = parse_frame(raw_data)
                frames_received.append(frame)

            if frames_received:
                num_new = len(frames_received)

                # Shift old data
                if num_new < buf_size:
                    data_buffer[:-num_new, :] = data_buffer[num_new:, :]
                else:
                    data_buffer[:] = 0

                # Insert new data at the bottom of the buffer
                start_idx = max(buf_size - num_new, 0)
                for i, fr in enumerate(frames_received[-buf_size:]):
                    data_buffer[start_idx + i, :] = fr

                # Example channel #5
                data_buffer_diff = np.diff(data_buffer, axis=0, prepend=1)
                filtered_data = remove_50_100Hz_noise(
                    data_buffer_diff[:, 5],
                    fs=sample_rate
                )
                # Convert raw units to volts
                filtered_data_volts = filtered_data * (4.5 / (2**22))

                # ===== Critical Section =====
                # We lock, then store the new data
                with lock:
                    # Overwrite 'latest' in shared dict
                    # If the main process doesn't read it in time, we discard old.
                    shared_dict['latest'] = filtered_data_volts

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("[UDP Reader] Interrupted by user.")
    finally:
        sock.close()
        print("[UDP Reader] Socket closed. Exiting process.")

###############################################################################
# Main process: sets up the plots and reads from the shared dict in real-time
###############################################################################
def main():
    
    # Configuration
    PC_IP       = "0.0.0.0"
    PC_PORT     = 5000
    sample_rate = 250
    time_window = 16  # seconds
    buf_size    = time_window * sample_rate

    # Create a multiprocessing manager for shared data
    manager = mp.Manager()
    shared_dict = manager.dict()
    shared_dict['latest'] = None  # start with nothing

    # Create a lock to protect shared access
    lock = mp.Lock()

    # Start the background UDP reader
    reader_proc = mp.Process(
        target=udp_reader_process,
        args=(shared_dict, lock, sample_rate, buf_size, PC_IP, PC_PORT),
        daemon=True
    )
    reader_proc.start()

    ######################
    # Setup the figure
    ######################
    plt.ion()
    fig, (ax_time, ax_spec) = plt.subplots(2, 1, figsize=(8, 6), constrained_layout=True)
    fig.suptitle("Realtime Time-Domain + Spectrogram (Channel 5)")

    # Time-domain subplot
    line_time, = ax_time.plot(np.zeros(buf_size), lw=1)
    ax_time.set_xlim(0, buf_size)
    ax_time.set_ylim(-0.1, 0.1)
    ax_time.set_title("Time-Domain")
    ax_time.set_xlabel("Samples")
    ax_time.set_ylabel("Amplitude [V]")
    ax_time.grid(True)

    # Spectrogram subplot
    ax_spec.set_title("Spectrogram")
    ax_spec.set_xlabel("Time [s]")
    ax_spec.set_ylabel("Frequency [Hz]")
    # Initialize an empty spectrogram
    im = ax_spec.pcolormesh([0, 1], [0, 1], np.array([[0]]), shading='auto')

    plt.show(block=False)

    # Plot loop
    try:
        while True:
            # If figure is closed, break
            if not plt.fignum_exists(fig.number):
                print("[Main] Plot window closed; exiting.")
                break

            # Read the latest data from shared dict
            # (Protected by lock so we don't clash with the writer)
            with lock:
                new_data = shared_dict['latest']
                # We can set it back to None if we want to know
                # that we've "consumed" it, but not strictly necessary
                # shared_dict['latest'] = None

            # If there's a new vector
            if new_data is not None:
                # Update time-domain
                line_time.set_ydata(new_data)

                # Compute spectrogram
                fvals, tvals, Sxx = compute_spectrogram(
                    new_data,
                    fs=sample_rate,
                    window_size=256,
                    step=16
                )
                Sxx_dB = 10 * np.log10(Sxx + 1e-12)  # convert to dB

                # Re-plot spectrogram
                ax_spec.cla()
                ax_spec.set_title("Spectrogram")
                ax_spec.set_xlabel("Time [s]")
                ax_spec.set_ylabel("Frequency [Hz]")
                im = ax_spec.pcolormesh(tvals, fvals, Sxx_dB, shading='auto')

            # Brief pause so the figure can update
            plt.pause(0.001)  # e.g. ~20 FPS
            plt.draw()  # e.g. ~20 FPS

    except KeyboardInterrupt:
        print("[Main] KeyboardInterrupt. Exiting.")
    finally:
        # Cleanup
        if reader_proc.is_alive():
            reader_proc.terminate()
        plt.close('all')
        print("[Main] Done.")

if __name__ == "__main__":
    main()
