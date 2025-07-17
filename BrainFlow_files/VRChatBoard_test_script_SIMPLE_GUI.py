#!/usr/bin/env python3
"""
VRChatBoard Simple Test Script
==============================
Just added continuous plotting to the ORIGINAL WORKING CODE

Changes from original:
1. Plot created before the loop instead of after
2. While loop updates plot continuously
3. Added DC centering with 0.5Hz filter
4. Fixed X-axis to 0-4 seconds
5. Used blitting for faster updates
"""

import sys
import time
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, CheckButtons, Slider

# Path to BrainFlow - adjust this to your installation
BRAINFLOW_PATH = "C:/Users/manok/Desktop/BCI/BrainFlowsIntoVRChat-main/brainflow_src/python_package"
sys.path.insert(0, BRAINFLOW_PATH)

from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds
from scipy import signal

# Connection settings
USE_AUTO_DISCOVERY = True  # Set to False to use manual IP

# Recording settings  
RECORD_DURATION = 4  # Seconds to show in window

# Global board reference
board = None

print("VRChatBoard Continuous Monitor")
print("=" * 40)
print("Note: Make sure board is powered on and on the same network!")

# ---------- STEP 1: CONNECT TO BOARD ----------
print("\n1. Connecting to board...")

# Configure connection parameters
params = BrainFlowInputParams()
params.ip_port = 5001      # Data port (where EEG data arrives)
params.ip_port_aux = 5000  # Control port (for sending commands)

params.ip_address = ""  # Empty = auto-discovery
print("   Using auto-discovery mode")

# Create board object and connect
board = BoardShim(BoardIds.VRCHAT_BOARD.value, params)
board.prepare_session()
print("   [OK] Connected!")

# ---------- STEP 2: CONFIGURE BOARD ----------
print("\n2. Configuring board...")

# Reboot esp
board.config_board("sys esp_reboot")
time.sleep(0.5)

# Reset the ADC chip for clean start
board.config_board("sys adc_reset")
time.sleep(0.5)

# Configure filters
board.config_board("sys filter_5060_off")    # No 50/60 Hz filtering
board.config_board("sys filter_100120_off")  # No 100/120 Hz filtering
board.config_board("sys digitalgain 8")      # 8x amplification
print("   [OK] Filters configured")

# ---------- STEP 3: START RECORDING ----------
print(f"\n3. Starting continuous display...")

# Start BrainFlow streaming (this creates an internal buffer)
board.start_stream()
time.sleep(1)  # Let stream stabilize

# Tell board to start sending data continuously
board.config_board("sys start_cnt")

# Get board specifications
fs = BoardShim.get_sampling_rate(BoardIds.VRCHAT_BOARD.value)
eeg_channels = BoardShim.get_eeg_channels(BoardIds.VRCHAT_BOARD.value)
window_samples = int(fs * RECORD_DURATION)

# DC filter for center tracking (0.5 Hz butterworth)
dc_b, dc_a = signal.butter(2, 0.5/(fs/2), 'low')
dc_zi = []
for i in range(16):
    dc_zi.append(signal.lfilter_zi(dc_b, dc_a) * 0.0)
dc_offset = np.zeros(16)

# Create figure
plt.ion()  # Interactive mode
fig, ax = plt.subplots(figsize=(14, 10))
ax.set_facecolor('white')

# Time axis
time_axis = np.arange(window_samples) / fs

# Create lines for each channel
lines = []
for i in range(16):
    offset = i * 0.0002  # 0.2mV spacing in Volts
    line, = ax.plot(time_axis, np.zeros(window_samples) + offset, 
                    linewidth=0.5, label=f'Ch{i}', alpha=0.8)
    lines.append(line)

# Configure plot
ax.set_xlabel('Time (seconds)', fontsize=12)
ax.set_ylabel('Amplitude (V)', fontsize=12)
ax.set_title('VRChatBoard - Continuous Monitor', fontsize=14)
ax.grid(True, alpha=0.3, which='both')  # Show both major and minor grid
ax.minorticks_on()  # Enable minor ticks
ax.legend(loc='center left', bbox_to_anchor=(1, 0.5), ncol=2, fontsize=8)
ax.set_xlim(0, RECORD_DURATION)  # Fix X-axis to 0-4 seconds

# Controls
running = True
center_on_dc = False
y_range = 0.05  # 50mV in Volts
background = None  # For blitting

def on_stop(event):
    global running, board
    running = False
    if board and board.is_prepared():
        try:
            board.config_board("sys stop_cnt")
            board.stop_stream()
            board.release_session()
            board = None
        except:
            pass
    btn_stop.label.set_text('STOPPED')
    plt.draw()

def on_center(label):
    global center_on_dc, dc_zi, dc_b, dc_a, background, ax, lines, time_axis, data_buffer, y_range, fig, scale_note, dc_offset
    center_on_dc = cb_center.get_status()[0]
    print(f"Center on DC: {center_on_dc}")
    if center_on_dc:
        # Reset DC filter states when enabling
        for i in range(16):
            dc_zi[i] = signal.lfilter_zi(dc_b, dc_a) * 0.0
    
    # Clear axes and redraw to get clean background
    ax.clear()
    
    # Recreate lines with current data
    for i in range(16):
        offset = i * 0.0002  # 0.2mV spacing in Volts
        if center_on_dc:
            line, = ax.plot(time_axis, data_buffer[:, i] - dc_offset[i] + offset, 
                            linewidth=0.5, label=f'Ch{i}', alpha=0.8)
        else:
            line, = ax.plot(time_axis, data_buffer[:, i] + offset, 
                            linewidth=0.5, label=f'Ch{i}', alpha=0.8)
        lines[i] = line
    
    # Restore plot settings
    ax.set_xlabel('Time (seconds)', fontsize=12)
    ax.set_ylabel('Amplitude (V)', fontsize=12)
    ax.set_title('VRChatBoard - Continuous Monitor' + scale_note, fontsize=14)
    ax.grid(True, alpha=0.3, which='both')
    ax.minorticks_on()
    ax.set_xlim(0, RECORD_DURATION)
    
    # Set Y limits
    if center_on_dc:
        avg_dc = np.mean(dc_offset)
        center = 7.5 * 0.0002 + avg_dc
    else:
        center = 7.5 * 0.0002
    ax.set_ylim(center - y_range/2, center + y_range/2)
    
    # Update background
    fig.canvas.draw()
    background = fig.canvas.copy_from_bbox(ax.bbox)

def on_range(val):
    global y_range, background
    y_range = 10 ** val
    # Set Y limits centered around the middle of all channels
    center = 7.5 * 200  # Middle of 16 channels
    ax.set_ylim(center - y_range/2, center + y_range/2)
    # Clear and redraw background
    ax.clear()
    # Recreate lines
    for i in range(16):
        offset = i * 200
        line, = ax.plot(time_axis, data_buffer[:, i] + offset, 
                        linewidth=0.5, label=f'Ch{i}', alpha=0.8)
        lines[i] = line
    # Restore plot settings
    ax.set_xlabel('Time (seconds)', fontsize=12)
    ax.set_ylabel('Amplitude (µV) + offset', fontsize=12)
    ax.set_title('VRChatBoard - Continuous Monitor' + scale_note, fontsize=14)
    ax.grid(True, alpha=0.3, axis='x')
    ax.set_xlim(0, RECORD_DURATION)
    ax.set_ylim(center - y_range/2, center + y_range/2)
    # Update background
    fig.canvas.draw()
    background = fig.canvas.copy_from_bbox(ax.bbox)

ax_stop = plt.axes([0.1, 0.02, 0.08, 0.04])
btn_stop = Button(ax_stop, 'STOP')
btn_stop.on_clicked(on_stop)

ax_center = plt.axes([0.25, 0.02, 0.12, 0.04])
cb_center = CheckButtons(ax_center, ['Center on DC'])
cb_center.on_clicked(on_center)

ax_range = plt.axes([0.45, 0.025, 0.35, 0.03])
sld_range = Slider(ax_range, 'Range (V):', -6, -1, valinit=np.log10(0.05), valfmt='%.3f')
sld_range.on_changed(on_range)

# Initial Y limits
center = 7.5 * 0.0002  # Middle of 16 channels in Volts
ax.set_ylim(center - y_range/2, center + y_range/2)

# Adjust layout
plt.tight_layout()
plt.subplots_adjust(bottom=0.12)

# Buffer for data
data_buffer = np.zeros((window_samples, 16))

# ---------- CONTINUOUS LOOP ----------
scale_note = ''
plt.show(block=False)  # Non-blocking show

# Store background for blitting
fig.canvas.draw()
background = fig.canvas.copy_from_bbox(ax.bbox)

while running and plt.fignum_exists(fig.number):
    # Get data exactly like original
    data = board.get_board_data()
    
    if data.shape[1] > 0:
        # Extract EEG channels and transpose to (n_samples, n_channels)
        eeg_data = data[eeg_channels, :].T
        
        # Check if we need to scale (auto-detect raw ADC vs voltage)
        if scale_note == '':
            if np.max(np.abs(eeg_data)) > 900:
                scale_note = ' (ADC values auto-scaled)'
                ax.set_title('VRChatBoard - Continuous Monitor' + scale_note, fontsize=14)
                fig.canvas.draw()  # Redraw title
                background = fig.canvas.copy_from_bbox(ax.bbox)  # Update background
        
        # Scale data
        eeg_data = eeg_data * 1e-6  # Convert to Volts (from microvolts)
        
        # Update DC offset if centering is on
        if center_on_dc and eeg_data.shape[0] > 0:
            for i in range(min(16, eeg_data.shape[1])):  # Safety check
                filtered, dc_zi[i] = signal.lfilter(dc_b, dc_a, eeg_data[:, i], zi=dc_zi[i])
                dc_offset[i] = filtered[-1]
        
        # Update buffer - rolling window
        n_new = eeg_data.shape[0]
        if n_new > 0:
            if n_new >= window_samples:
                # Got more data than window size - take last window_samples
                data_buffer[:, :] = eeg_data[-window_samples:, :]
            else:
                # Shift old data left and append new data
                data_buffer[:-n_new, :] = data_buffer[n_new:, :]
                data_buffer[-n_new:, :] = eeg_data
        
        # Update plot
        for i in range(min(16, data_buffer.shape[1])):  # Safety check
            offset = i * 0.0002  # 0.2mV spacing in Volts
            if center_on_dc:
                # Center on DC offset
                lines[i].set_ydata(data_buffer[:, i] - dc_offset[i] + offset)
            else:
                # Normal offset  
                lines[i].set_ydata(data_buffer[:, i] + offset)
        
        # Update Y-axis when centering to follow the DC offset
        if center_on_dc:
            avg_dc = np.mean(dc_offset)
            center = 7.5 * 0.0002 + avg_dc  # Move center based on average DC
            ax.set_ylim(center - y_range/2, center + y_range/2)
        
        # Faster redraw using blitting
        if center_on_dc:
            # When centering, we need to update Y-axis, so can't use blitting
            fig.canvas.draw_idle()
            fig.canvas.flush_events()
            # Update background after drawing
            background = fig.canvas.copy_from_bbox(ax.bbox)
        else:
            # Normal mode - use blitting for speed
            fig.canvas.restore_region(background)
            for line in lines:
                ax.draw_artist(line)
            fig.canvas.blit(ax.bbox)
            fig.canvas.flush_events()
    
    # Small pause for GUI responsiveness  
    # If still slow, increase to 0.01 or 0.02
    plt.pause(0.001)  # Minimal pause for event handling

print("\n[OK] Stopped")

# Cleanup
if board and board.is_prepared():
    try:
        board.config_board("sys stop_cnt")
        board.stop_stream()
        board.release_session()
    except:
        pass

plt.close('all')