import multiprocessing as mp
import numpy as np
import socket
import time
import scipy.signal as sps
import matplotlib.pyplot as plt
import pywt

def parse_frame(raw_data):
    parsed = [0]*16
    for i in range(16):
        j = 3 + (i * 3)
        if i >= 8:
            j += 3
        value = ((raw_data[j] << 16) |
                 (raw_data[j + 1] <<  8) |
                  raw_data[j + 2])
        if value & 0x800000:
            value -= 1 << 24
        parsed[i] = value
    return parsed

def remove_50_100Hz_noise(signal_in, fs, Q=4):
    b50, a50 = sps.iirnotch(w0=50.0, Q=Q, fs=fs)
    b100, a100 = sps.iirnotch(w0=100.0, Q=Q, fs=fs)
    tmp = sps.filtfilt(b50, a50, signal_in)
    filtered = sps.filtfilt(b100, a100, tmp)
    return filtered

def compute_spectrogram(x, fs, window_size, step):
    noverlap = window_size - step
    f, t, Sxx = sps.spectrogram(
        x, fs=fs,
        window='hamming',
        nperseg=window_size,
        noverlap=noverlap
    )
    return f, t, Sxx

def compute_wavelet(x, fs):
    """
    Returns:
        coef: 2D array [num_scales, padded_length]
        full_time: 1D array for padded_time, length = padded_length
        scales: 1D array of scales
    """
    pad_amount = 512
    padded_signal = np.pad(x, (0, pad_amount), mode='constant')

    scales = np.arange(1, 128)
    dt = 1.0 / fs
    coef, freqs = pywt.cwt(padded_signal, scales, wavelet='morl', sampling_period=dt)

    N_padded = len(padded_signal)
    full_time = np.linspace(0, N_padded/fs, N_padded)
    return coef, full_time, scales

def udp_reader_process(shared_dict, lock, sample_rate, buf_size, ip, port):
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
                filtered_data = remove_50_100Hz_noise(data_buffer_diff[:, 5], fs=sample_rate)
                filtered_data_volts = filtered_data * (4.5 / (2**22))

                with lock:
                    shared_dict['latest'] = filtered_data_volts

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("[UDP Reader] Interrupted by user.")
    finally:
        sock.close()
        print("[UDP Reader] Socket closed. Exiting process.")

def main():
    PC_IP       = "0.0.0.0"
    PC_PORT     = 5555
    sample_rate = 250

    # If you want to store exactly 16 seconds of data, use:
    time_window = 16
    buf_size    = 2048  # 4000

    manager = mp.Manager()
    shared_dict = manager.dict()
    shared_dict['latest'] = None

    lock = mp.Lock()

    reader_proc = mp.Process(
        target=udp_reader_process,
        args=(shared_dict, lock, sample_rate, buf_size, PC_IP, PC_PORT),
        daemon=True
    )
    reader_proc.start()

    plt.ion()
    fig, (ax_time, ax_spec, ax_wave) = plt.subplots(3, 1, figsize=(8, 9), constrained_layout=True)
    fig.suptitle("Realtime: Time-Domain, Spectrogram, Wavelet (Channel 5)")

    line_time, = ax_time.plot(np.zeros(buf_size), lw=1)
    ax_time.set_xlim(0, buf_size)  # horizontally 0..4000 samples
    ax_time.set_ylim(-0.0025, 0.0025)
    ax_time.set_title("Time-Domain")
    ax_time.set_xlabel("Samples")
    ax_time.set_ylabel("Amplitude [V]")
    ax_time.grid(True)

    ax_spec.set_title("Spectrogram")
    ax_spec.set_xlabel("Time [s]")
    ax_spec.set_ylabel("Frequency [Hz]")
    im_spec = ax_spec.pcolormesh([0, 1], [0, 1], np.array([[0]]), shading='auto')

    ax_wave.set_title("Wavelet Transform (Morlet)")
    ax_wave.set_xlabel("Time [s]")
    ax_wave.set_ylabel("Scale")
    im_wave = ax_wave.imshow([[0]], aspect='auto', origin='lower')

    plt.show(block=False)

    try:
        while True:
            if not plt.fignum_exists(fig.number):
                print("[Main] Plot window closed; exiting.")
                break

            with lock:
                new_data = shared_dict['latest']

            if new_data is not None:
                # --- Time-domain ---
                npts = len(new_data)
                line_time.set_ydata(new_data)

                # -- SPECTROGRAM --
                fvals, tvals, Sxx = compute_spectrogram(
                    new_data,
                    fs=sample_rate,
                    window_size=256,
                    step=32
                )
                Sxx_dB = 10 * np.log10(Sxx + 1e-12)

                ax_spec.cla()
                ax_spec.set_title("Spectrogram")
                ax_spec.set_xlabel("Time [s]")
                ax_spec.set_ylabel("Frequency [Hz]")
                # tvals goes from 0.. ~ (npts/fs)
                im_spec = ax_spec.pcolormesh(tvals, fvals, Sxx_dB, shading='auto')

                # -- WAVELET --
                coef, full_time, scales = compute_wavelet(new_data, sample_rate)
                coef_mag = 20 * np.log10(np.abs(coef) + 1e-12)

                # Crop the padded wavelet result to the real data length
                real_len = npts  # how many real samples
                if real_len < coef_mag.shape[1]:
                    coef_mag = coef_mag[:, :real_len]      # keep only columns that map to real data
                    wave_time = full_time[:real_len]       # same range
                else:
                    # in case new_data is bigger than we planned? (unlikely)
                    wave_time = full_time

                ax_wave.cla()
                ax_wave.set_title("Wavelet Transform (Morlet)")
                ax_wave.set_xlabel("Time [s]")
                ax_wave.set_ylabel("Scale")

                extent = [wave_time[0], wave_time[-1], scales[0], scales[-1]]
                im_wave = ax_wave.imshow(coef_mag, aspect='auto', origin='lower',
                                         extent=extent)
                im_wave.set_clim(-80, -40)  # Example clim

            plt.pause(0.01)

    except KeyboardInterrupt:
        print("[Main] KeyboardInterrupt. Exiting.")
    finally:
        if reader_proc.is_alive():
            reader_proc.terminate()
        plt.close('all')
        print("[Main] Done.")

if __name__ == "__main__":
    main()
