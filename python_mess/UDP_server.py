import matplotlib.pyplot as plt
import numpy as np
import socket

import scipy.signal as sps

def remove_50Hz_noise(signal_in, fs, Q=20.0):
    """
    Removes ~50 Hz noise from 'signal_in' using an IIR notch filter.
    
    Parameters
    ----------
    signal_in : ndarray
        Input 1D signal (length N).
    fs       : float
        Sampling frequency in Hz.
    Q        : float, optional
        Quality factor for the notch filter (higher = narrower notch).
    
    Returns
    -------
    filtered : ndarray
        Output signal of same length as 'signal_in'.
    """
    # Design IIR notch filter centered at 50 Hz
    f0 = 50.0  # Frequency to remove
    b, a = sps.iirnotch(w0=f0, Q=Q, fs=fs)
    
    # Apply zero-phase filtering (filtfilt for no phase distortion)
    filtered = sps.filtfilt(b, a, signal_in)
    return filtered

#########################################################
# PC side: Receive data
#########################################################
PC_IP = "0.0.0.0"    # Listen on all interfaces
PC_PORT = 5555

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((PC_IP, PC_PORT))
sock.setblocking(False)

print(f"[Server] Listening on {PC_IP}:{PC_PORT}...")

Sample_rate = 250 # smaple rate of the ADC
FPS_plot    =   30 # visualisation FPS
time_window =    16 # seconds
window_size = time_window * Sample_rate # size of the samples i have to store to have givin size
data_buffer = np.zeros((window_size, 16), dtype = np.int32) # prepare buffer

# Setup plot
plt.ion()
fig, ax = plt.subplots()
lines = []
for i in range(1):
    line, = ax.plot(np.zeros(window_size))
    lines.append(line)
ax.set_xlim(0      , window_size)
ax.set_ylim(-0.005,      0.005)
ax.set_title("Realtime ADS1299 data (16 channels)")
ax.set_xlabel("Time (frames)")
ax.set_ylabel("ADC value")
#plt.minorticks_on()
plt.grid(which='both')
plt.pause(0.1)
fig.canvas.draw()
plt.show(block = False)

def parse_frame(raw_data):
    """
    Given a single 27-byte frame from ADS1299,
    returns an 8-element list/array of int32 values.
    """
    parsed = [0]*16
    # Example: first 3 bytes might be status, then 8 channels * 3 bytes each
    # Adjust indexing to match your actual packet format
    for i in range(16):
        j = 3 + (i * 3)  # offset within the raw packet
        if i >= 8:
            j = j + 3
        value = ((raw_data[j    ] << 16) |
                 (raw_data[j + 1] <<  8) |
                  raw_data[j + 2])
        # Sign-extend 24-bit two's-complement
        if value & 0x800000:
            value -= 1 << 24
        parsed[i] = value
    
    return parsed

while True:
    # 1) Read ALL pending UDP packets
    frames_received = []
    while True:
        try:
            raw_data, addr = sock.recvfrom(1024)  # Enough for a 27-54 byte packet
        except BlockingIOError:
            # No more packets left in the socket buffer
            break
        
        # 2) Parse the packet into an 8-channel sample
        frame = parse_frame(raw_data)
        frames_received.append(frame)
    
    # If we got new frames, update the buffer
    if frames_received:
        num_new = len(frames_received)
        # 3) Shift the buffer up by 'num_new' rows
        if num_new < window_size:
            data_buffer[:-num_new, :] = data_buffer[num_new:, :]
        else:
            # If we received >= window_size frames in one go,
            # we effectively flush the entire buffer
            data_buffer[:] = 0
        
        # 4) Put new frames in the bottom of the buffer
        #    If more frames than the buffer size, keep only the last ones
        start_idx = max(window_size - num_new, 0)
        for i, fr in enumerate(frames_received[-window_size:]):
            data_buffer[start_idx + i, :] = fr
        
        # Compute the mean across the time axis (axis=0 => average each column separately)
        mean_per_channel = np.mean(data_buffer, axis=0)
        
        # Subtract that mean from each sample in the corresponding channel
        data_buffer_diff = np.diff(data_buffer, axis = 0, prepend = 1)
        
        filtered_data = remove_50Hz_noise(data_buffer_diff[:, 5], 250)
        
        # 5) Update the plot
        for ch in range(1):
            lines[ch].set_ydata(filtered_data * (4.5/(2**22)))
        
        plt.pause(0.001)
        plt.draw()