import matplotlib.pyplot as plt
import numpy as np
import socket
import scipy.signal as sps

#######################
#  Existing functions
#######################
def remove_50Hz_noise(signal_in, fs, Q=20.0):
    """
    Removes ~50 Hz noise from 'signal_in' using an IIR notch filter.
    """
    f0 = 50.0
    b, a = sps.iirnotch(w0=f0, Q=Q, fs=fs)
    filtered = sps.filtfilt(b, a, signal_in)
    f0 = 100.0
    b, a = sps.iirnotch(w0=f0, Q=Q, fs=fs)
    filtered = sps.filtfilt(b, a, filtered)
    return filtered

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
        value = ((raw_data[j    ] << 16) |
                 (raw_data[j + 1] <<  8) |
                  raw_data[j + 2])
        if value & 0x800000:
            value -= 1 << 24
        parsed[i] = value
    return parsed

#######################
#  NEW spectrogram function
#######################
def compute_spectrogram(x, fs, window_size, step):
    """
    Compute spectrogram (Hamming window) of signal x with given window size and step.

    Parameters
    ----------
    x : 1D array-like
        Input signal.
    fs : float
        Sampling frequency.
    window_size : int
        Number of samples per window (nperseg).
    step : int
        Hop size between successive windows. Overlap = window_size - step.

    Returns
    -------
    f : 1D array
        Frequency array (only the first half).
    t : 1D array
        Time array for the spectrogram.
    Sxx : 2D array
        Spectrogram values (only the first half of freq).
    """
    noverlap = window_size - step
    f, t, Sxx = sps.spectrogram(x, fs=fs,
                                window='hamming',
                                nperseg=window_size,
                                noverlap=noverlap)
    # Keep only the first half of the frequency range
    # half_len = len(f) // 2
    # f = f[:half_len]
    # Sxx = Sxx[:half_len, :]
    return f, t, Sxx

#######################
#  PC side: Receive data
#######################
PC_IP = "0.0.0.0"
PC_PORT = 5555

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((PC_IP, PC_PORT))
sock.setblocking(False)

print(f"[Server] Listening on {PC_IP}:{PC_PORT}...")

Sample_rate = 250    # ADC sampling rate
FPS_plot    = 30
time_window = 16     # seconds
window_size = 2048
data_buffer = np.zeros((window_size, 16), dtype = np.int32)

#######################
#  Setup plot (time-series)
#######################
plt.ion()
fig, ax = plt.subplots()
lines = []
for i in range(1):
    line, = ax.plot(np.zeros(window_size))
    lines.append(line)
ax.set_xlim(0, window_size)
ax.set_ylim(-0.005, 0.005)
ax.set_title("Realtime ADS1299 data (16 channels)")
ax.set_xlabel("Time (frames)")
ax.set_ylabel("ADC value")
plt.grid(which='both')
plt.pause(0.1)
fig.canvas.draw()
plt.show(block=False)

#######################
#  Setup a second figure (or subplot) for spectrogram
#######################
fig_spec, ax_spec = plt.subplots()
ax_spec.set_title("Spectrogram")
ax_spec.set_xlabel("Time [s]")
ax_spec.set_ylabel("Frequency [Hz]")

#######################
#  Main loop
#######################
while True:
    # 1) Read ALL pending UDP packets
    frames_received = []
    while True:
        try:
            raw_data, addr = sock.recvfrom(1024)
        except BlockingIOError:
            # No more packets
            break
        frame = parse_frame(raw_data)
        frames_received.append(frame)
    
    # 2) Update the data buffer if new frames arrived
    if frames_received:
        num_new = len(frames_received)
        if num_new < window_size:
            data_buffer[:-num_new, :] = data_buffer[num_new:, :]
        else:
            data_buffer[:] = 0
        
        start_idx = max(window_size - num_new, 0)
        for i, fr in enumerate(frames_received[-window_size:]):
            data_buffer[start_idx + i, :] = fr

        # Example channel: channel 5 (index = 5)
        # Remove DC (via differencing) and 50Hz:
        data_buffer_diff = np.diff(data_buffer, axis=0, prepend=1)
        filtered_data = remove_50Hz_noise(data_buffer_diff[:, 5], Sample_rate)

        # Convert raw units -> volts (or your scale)
        filtered_data_volts = filtered_data * (4.5 / (2**22))

        # Update the time-domain plot
        lines[0].set_ydata(filtered_data_volts)
        plt.pause(0.001)
        plt.draw()
        
        # ---- Compute & update spectrogram below ----
        # E.g., using 512-sample windows and 256-step
        # (you can tune these to suit your needs)
        fvals, tvals, Sxx = compute_spectrogram(
            x=filtered_data_volts,
            fs=Sample_rate,
            window_size=512,
            step=256
        )
        
        # Clear old spectrogram, plot new
        ax_spec.cla()
        ax_spec.set_title("Spectrogram")
        ax_spec.set_xlabel("Time [s]")
        ax_spec.set_ylabel("Frequency [Hz]")
        
        # Plot in dB
        im = ax_spec.pcolormesh(tvals, fvals, 10*np.log10(Sxx), shading='auto')
        
        # Optional colorbar (requires fig_spec.colorbar)
        # fig_spec.colorbar(im, ax=ax_spec, label='Power [dB]')
        
        fig_spec.canvas.draw()
        plt.pause(0.001)
