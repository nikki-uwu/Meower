#!/usr/bin/env python3
"""
VRChatBoard Simple Test Script
==============================
Minimal example showing the essential steps to use VRChatBoard:
1. Connect (auto-discovery or manual IP)
2. Configure filters
3. Record data
4. Plot results
5. Disconnect

This script has minimal error handling - use the comprehensive
script for production or testing unknown boards.

Note: If you see very large values (>1000 uV), the driver may be
returning raw ADC values instead of voltage. The script will
auto-scale to millivolts in this case.
"""

import sys
import time
import numpy as np
import matplotlib.pyplot as plt

# ====================================================================
#                        CONFIGURATION
# ====================================================================

# Path to BrainFlow - adjust this to your installation
BRAINFLOW_PATH = "C:/Users/manok/Desktop/BCI/BrainFlowsIntoVRChat-main/brainflow_src/python_package"
sys.path.insert(0, BRAINFLOW_PATH)

from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds

# Connection settings
USE_AUTO_DISCOVERY = True  # Set to False to use manual IP

# Recording settings  
RECORD_DURATION = 10  # Seconds to record


# ====================================================================
#                         MAIN SCRIPT
# ====================================================================

def main():
    """Simple VRChatBoard test - connect, record, plot, disconnect."""
    
    print("VRChatBoard Simple Test")
    print("=" * 40)
    print("\nExpected channels:")
    print("  0-15: EEG data")
    print("  16:   Battery voltage")
    print("  17:   Hardware timestamp")
    print("  18+:  Markers/Reserved")
    
    # ---------- STEP 1: CONNECT TO BOARD ----------
    print("\n1. Connecting to board...")
    
    # Configure connection parameters
    params = BrainFlowInputParams()

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
    # Turn off notch filters to see raw signal (including 60Hz noise)
    board.config_board("sys filter_5060_off")    # No 50/60 Hz filtering
    board.config_board("sys filter_100120_off")  # No 100/120 Hz filtering
    board.config_board("sys digitalgain 8")      # 8x amplification
    print("   [OK] Filters configured")
    
    # ---------- STEP 3: START RECORDING ----------
    print(f"\n3. Recording {RECORD_DURATION} seconds of data...")
    
    # Start BrainFlow streaming (this creates an internal buffer)
    board.start_stream()
    time.sleep(1)  # Let stream stabilize
    
    # Tell board to start sending data continuously
    board.config_board("sys start_cnt")
    print("   Recording...", end='', flush=True)
    
    # Wait while data accumulates in buffer
    for i in range(RECORD_DURATION):
        time.sleep(1)
        print(".", end='', flush=True)
    print(" Done!")
    
    # ---------- STEP 4: STOP AND GET DATA ----------
    print("\n4. Retrieving data...")
    
    # Stop continuous mode on board
    board.config_board("sys stop_cnt")
    
    # Stop BrainFlow streaming
    board.stop_stream()
    
    # Get all accumulated data
    data = board.get_board_data()
    
    # Disconnect from board
    board.release_session()
    
    print(f"   [OK] Retrieved {data.shape[1]} samples")
    print(f"   [OK] Disconnected from board")
    
    # ---------- STEP 5: PLOT THE DATA ----------
    if data.shape[1] == 0:
        print("\n[X] No data received!")
        return
        
    print("\n5. Creating plot...")
    
    # Get board specifications
    fs = BoardShim.get_sampling_rate(BoardIds.VRCHAT_BOARD.value)
    eeg_channels = BoardShim.get_eeg_channels(BoardIds.VRCHAT_BOARD.value)
    
    try:
        battery_channel = BoardShim.get_battery_channel(BoardIds.VRCHAT_BOARD.value)
    except:
        battery_channel = 16  # Default position if not defined
    
    # Create time axis using hardware timestamps if available
    try:
        resistance_channels = BoardShim.get_resistance_channels(BoardIds.VRCHAT_BOARD.value)
        hw_timestamp_channel = resistance_channels[0] if resistance_channels else 17
        
        if hw_timestamp_channel < data.shape[0]:
            # Use hardware timestamps for more accurate timing
            time_axis = data[hw_timestamp_channel, :]
            print(f"   Using hardware timestamps (board uptime: {time_axis[-1]:.1f}s)")
        else:
            # Fall back to sample-based timing
            time_axis = np.arange(data.shape[1]) / fs
            print("   Using sample-based timing")
    except:
        # Fall back to sample-based timing
        time_axis = np.arange(data.shape[1]) / fs
        print("   Using sample-based timing")
    
    # Display battery status
    avg_battery = 0.0  # Default if no battery channel
    if 0 <= battery_channel < data.shape[0]:
        avg_battery = np.mean(data[battery_channel, :])
        print(f"   Battery voltage: {avg_battery:.2f}V")
    
    # Create figure
    plt.figure(figsize=(14, 10))
    
    # Check if we need to scale the data (auto-detect raw ADC vs voltage)
    first_channel = data[eeg_channels[0], :] if len(eeg_channels) > 0 else np.array([0])
    scale_factor = 1e6  # Convert to microvolts
    unit_label = 'uV'
    offset_step = 0  # 200 uV between channels
    scale_note = ''
    
    # Plot each of the 16 channels
    for i in range(16):
        if i < len(eeg_channels) and eeg_channels[i] < data.shape[0]:
            # Get channel data and convert to appropriate units
            channel_data = data[eeg_channels[i], :] * scale_factor
            
            # Add offset for visual separation
            offset = i * offset_step
            
            # Plot with a label
            plt.plot(time_axis, channel_data + offset, 
                    linewidth=0.5, 
                    label=f'Ch{i}',
                    alpha=0.8)
    
    # Configure plot
    plt.xlabel('Time (seconds)', fontsize=12)
    plt.ylabel(f'Amplitude ({unit_label}) + offset', fontsize=12)
    
    # Build title with battery info if available
    title_lines = [
        f'VRChatBoard - 16 Channel EEG Recording{scale_note}',
        f'{data.shape[1]} samples @ {fs} Hz = {data.shape[1]/fs:.1f} seconds'
    ]
    if avg_battery > 0:
        title_lines.append(f'Battery: {avg_battery:.2f}V')
    
    plt.title('\n'.join(title_lines), fontsize=14)
    plt.grid(True, alpha=0.3, axis='x')
    
    # Add legend
    plt.legend(loc='center left', bbox_to_anchor=(1, 0.5), ncol=2)
    
    # Adjust layout and show
    plt.tight_layout()
    plt.show()
    
    print("\n[OK] Test completed successfully!")


# ====================================================================
#                      ERROR HANDLING
# ====================================================================

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n[X] Error: {e}")
        print("\nCommon issues:")
        print("- Board not powered on")
        print("- Wrong network / firewall blocking")
        print("- Incorrect IP address")
        print("- Board already in use")
        
        # Try to clean up on error
        try:
            board = BoardShim(BoardIds.VRCHAT_BOARD.value, BrainFlowInputParams())
            if board.is_prepared():
                board.release_session()
        except:
            pass