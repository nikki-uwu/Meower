#!/usr/bin/env python3
"""
VRChatBoard Comprehensive Test Script
=====================================
This script demonstrates all features of the VRChatBoard:
- Auto-discovery (finding the board without knowing its IP)
- Manual IP connection fallback
- Filter configuration
- Data recording and analysis
- Real-time plotting

The script is designed to be educational - every step is explained.
"""

import sys
import time
import numpy as np
import matplotlib.pyplot as plt
from typing import Optional, Tuple

# ====================================================================
#                        CONFIGURATION
# ====================================================================

# Path to BrainFlow - adjust this to your installation
BRAINFLOW_PATH = "C:/Users/manok/Desktop/BCI/BrainFlowsIntoVRChat-main/brainflow_src/python_package"
sys.path.insert(0, BRAINFLOW_PATH)

# Import BrainFlow after path is set
from brainflow.board_shim import BoardShim, BrainFlowInputParams, BoardIds, BrainFlowError

# Debug mode - set to True to see detailed output from the C++ driver
DEBUG_MODE = True  # When True, shows packet statistics, discovery process, etc.

# Board configuration
DATA_PORT = 5001      # Port for receiving EEG data (high-speed stream)
CONTROL_PORT = 5000   # Port for sending commands (filters, settings)
DISCOVERY_TIMEOUT = 5000  # How long to wait for board beacon (milliseconds)

# Recording settings
DEFAULT_RECORD_DURATION = 10  # Seconds to record
STABILIZATION_TIME = 2        # Wait time before recording (lets stream stabilize)

# Expected board description JSON:
# brainflow_boards_json["boards"]["65"]["default"] =
# {
#     {"name", "VRChatBoard"},
#     {"sampling_rate", 250},
#     {"marker_channel", 18},
#     {"num_rows", 21},
#     {"eeg_channels", {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15}},
#     {"eeg_names", "CH1,CH2,CH3,CH4,CH5,CH6,CH7,CH8,CH9,CH10,CH11,CH12,CH13,CH14,CH15,CH16"},
#     {"battery_channel", 16},
#     {"resistance_channels", {17}},  // Hardware timestamp
#     {"other_channels", {19, 20}}
# };

# Note: If you see values like 969601.8 uV (near 1V), the driver
# has a scaling issue and is returning raw ADC values. The test
# scripts will auto-detect this and scale to millivolts for display.


# ====================================================================
#                      AUTO-DISCOVERY FUNCTIONS
# ====================================================================

def discover_board(timeout_ms: int = DISCOVERY_TIMEOUT, debug: bool = False) -> Optional[BoardShim]:
    """
    Attempt to automatically discover the VRChat EEG board on the network.
    
    How auto-discovery works:
    1. The board broadcasts UDP "beacon" packets on port 5000
    2. Our driver listens for these beacons
    3. When found, it extracts the board's IP address
    4. Connection is established automatically
    
    Args:
        timeout_ms: How long to wait for the board beacon
        debug: Enable detailed debug output
        
    Returns:
        BoardShim object if successful, None if discovery failed
    """
    print("\n" + "=" * 60)
    print("AUTO-DISCOVERY MODE")
    print("=" * 60)
    
    # Configure connection parameters
    params = BrainFlowInputParams()
    params.ip_port = DATA_PORT        # Where to receive EEG data
    params.ip_port_aux = CONTROL_PORT # Where to send commands
    # params.ip_address = ""          # Empty = auto-discovery mode
    
    # Build the other_info string with our settings
    other_info_parts = []
    if debug:
        other_info_parts.append("debug=1")
    other_info_parts.append(f"discovery_timeout={timeout_ms}")
    params.other_info = " ".join(other_info_parts)
    
    print(f"\n[SEARCH] Listening for board beacon on port {CONTROL_PORT}...")
    print(f"   Timeout: {timeout_ms/1000:.1f} seconds")
    print("\n   Make sure:")
    print("   [OK] Board is powered on")
    print("   [OK] Board is connected to WiFi") 
    print("   [OK] Computer and board are on the same network")
    print("   [OK] Firewall allows UDP port 5000\n")
    
    # Create board object
    board = BoardShim(BoardIds.VRCHAT_BOARD.value, params)
    
    try:
        # This call will block until board is found or timeout
        board.prepare_session()
        print("\n[SUCCESS] Board discovered successfully!")
        return board
        
    except BrainFlowError as e:
        print(f"\n[ERROR] Discovery failed: {e}")
        return None


def connect_with_retries(max_attempts: int = 3) -> Optional[BoardShim]:
    """
    Try to discover the board multiple times with retries.
    
    Sometimes discovery fails due to:
    - Network congestion
    - Firewall delays
    - Board still booting
    
    Args:
        max_attempts: How many times to try
        
    Returns:
        BoardShim object if successful, None if all attempts failed
    """
    print("\n" + "=" * 60)
    print("DISCOVERY WITH RETRIES")
    print("=" * 60)
    
    for attempt in range(max_attempts):
        print(f"\n[RETRY] Attempt {attempt + 1} of {max_attempts}")
        
        board = discover_board(timeout_ms=DISCOVERY_TIMEOUT, debug=DEBUG_MODE)
        
        if board is not None:
            return board
            
        if attempt < max_attempts - 1:
            print("   Waiting 2 seconds before retry...")
            time.sleep(2)
    
    print("\n[ERROR] All discovery attempts failed")
    return None


def connect_manual_ip() -> Optional[BoardShim]:
    """
    Connect to board using manually entered IP address.
    
    This is useful when:
    - Auto-discovery doesn't work (different subnet, VPN, etc.)
    - You know the board's IP address
    - Faster connection (skips discovery)
    
    Returns:
        BoardShim object if successful, None if user cancels
    """
    print("\n" + "=" * 60)
    print("MANUAL IP CONNECTION")
    print("=" * 60)
    
    print("\nEnter board IP address (or 'cancel' to exit): ", end='')
    ip_input = input().strip()
    
    if ip_input.lower() == 'cancel':
        return None
        
    # Validate IP format (basic check)
    ip_parts = ip_input.split('.')
    if len(ip_parts) != 4:
        print("[ERROR] Invalid IP format. Expected: xxx.xxx.xxx.xxx")
        return None
        
    # Configure connection
    params = BrainFlowInputParams()
    params.ip_address = ip_input
    params.ip_port = DATA_PORT
    params.ip_port_aux = CONTROL_PORT
    if DEBUG_MODE:
        params.other_info = "debug=1"
    
    print(f"\n[CONNECT] Connecting to {ip_input}...")
    
    board = BoardShim(BoardIds.VRCHAT_BOARD.value, params)
    
    try:
        board.prepare_session()
        print("[SUCCESS] Connected successfully!")
        return board
    except BrainFlowError as e:
        print(f"[ERROR] Connection failed: {e}")
        return None


# ====================================================================
#                    BOARD CONFIGURATION FUNCTIONS
# ====================================================================

def configure_board_filters(board: BoardShim) -> None:
    """
    Configure the board's signal processing filters.
    
    Filters clean up the EEG signal by removing:
    - DC offset (slow drift)
    - Power line noise (50/60 Hz hum)
    - High frequency noise
    
    Args:
        board: Connected BoardShim object
    """
    print("\n" + "=" * 60)
    print("CONFIGURING FILTERS")
    print("=" * 60)
    
    # Define configuration commands with explanations
    commands = [
        # Reset the ADC (Analog-to-Digital Converter) to ensure clean start
        ("Resetting ADC chip", "sys adc_reset", 
         "Ensures the ADS1299 chip starts fresh"),
         
        # Enable all filters at once
        ("Enabling all filters", "sys filters_on",
         "Turns on DC blocking, equalizer, and notch filters"),
         
        # Configure individual filters
        ("Setting DC blocking to 1Hz", "sys dccutofffreq 1",
         "Removes slow drift below 1Hz (breathing, movement)"),
         
        ("Setting mains frequency to 60Hz", "sys networkfreq 60",
         "Configures notch filter for US power grid (use 50 for EU/Asia)"),
         
        # For this demo, disable notch filters to see raw signal
        ("Disabling 50/60Hz filter", "sys filter_5060_off",
         "Allows power line noise through (for testing)"),
         
        ("Disabling 100/120Hz filter", "sys filter_100120_off",
         "Allows harmonics through (for testing)"),
         
        # Set amplification
        ("Setting gain to 8x", "sys digitalgain 1",
         "Amplifies weak brain signals (1-100 uV) to measurable range"),
    ]
    
    # Send each command
    for description, command, explanation in commands:
        print(f"\n-> {description}")
        print(f"  Command: '{command}'")
        print(f"  Purpose: {explanation}")
        
        try:
            response = board.config_board(command)
            if response:
                print(f"  Response: {response}")
            else:
                print("  [OK] Command sent (no response expected)")
        except Exception as e:
            print(f"  [ERROR] Error: {e}")
            
        # Small delay between commands to avoid overwhelming the board
        time.sleep(0.2)


# ====================================================================
#                      DATA RECORDING FUNCTIONS
# ====================================================================

def record_eeg_data(board: BoardShim, duration_seconds: int) -> Optional[np.ndarray]:
    """
    Record EEG data from all 16 channels for the specified duration.
    
    The recording process:
    1. Start BrainFlow's data buffering
    2. Tell the board to start continuous transmission
    3. Wait while data accumulates in the buffer
    4. Stop transmission and retrieve all data
    
    Args:
        board: Connected BoardShim object
        duration_seconds: How long to record
        
    Returns:
        NumPy array with shape (channels, samples) or None if failed
    """
    print("\n" + "=" * 60)
    print(f"RECORDING DATA ({duration_seconds} seconds)")
    print("=" * 60)
    
    try:
        # Get board specifications
        sampling_rate = BoardShim.get_sampling_rate(BoardIds.VRCHAT_BOARD.value)
        print(f"\n[INFO] Board info:")
        print(f"   Sampling rate: {sampling_rate} Hz")
        print(f"   Expected samples: ~{sampling_rate * duration_seconds:,}")
        
        # Calculate buffer size (2x duration for safety margin)
        buffer_size = int(sampling_rate * duration_seconds * 2)
        print(f"   Buffer size: {buffer_size:,} samples")
        
        # Start BrainFlow streaming
        print("\n[START] Starting data stream...")
        board.start_stream(buffer_size)
        
        # Wait for stream to stabilize
        print(f"[WAIT] Waiting {STABILIZATION_TIME}s for stream to stabilize...")
        time.sleep(STABILIZATION_TIME)
        
        # Clear any initial data (could be partial packets)
        initial_data = board.get_board_data()
        if initial_data.shape[1] > 0:
            print(f"[CLEAR] Cleared {initial_data.shape[1]} initial samples")
        
        # Start continuous mode on the board
        print("\n[TRANSMIT] Starting continuous transmission...")
        board.config_board("sys start_cnt")
        time.sleep(0.5)  # Give board time to process command
        
        # Recording loop with progress updates
        print(f"\n[REC] Recording for {duration_seconds} seconds:")
        start_time = time.time()
        
        for second in range(duration_seconds):
            time.sleep(1)
            elapsed = time.time() - start_time
            expected_samples = int(sampling_rate * elapsed)
            
            # Show progress
            progress = "#" * (second + 1) + "." * (duration_seconds - second - 1)
            print(f"   [{progress}] {second + 1}/{duration_seconds}s", end='\r')
            
        print(f"\n[SUCCESS] Recording complete!")
        
        # Stop continuous mode BEFORE retrieving data
        print("\n[STOP] Stopping transmission...")
        board.config_board("sys stop_cnt")
        time.sleep(0.5)
        
        # Stop the stream
        print("[RETRIEVE] Retrieving data from buffer...")
        board.stop_stream()
        
        # Get all the data
        data = board.get_board_data()
        
        # Validate what we got
        actual_duration = time.time() - start_time
        expected_samples = int(sampling_rate * actual_duration * 0.9)  # 90% threshold
        
        print(f"\n[STATS] Recording statistics:")
        print(f"   Collected samples: {data.shape[1]:,}")
        print(f"   Expected samples: ~{expected_samples:,}")
        print(f"   Actual duration: {actual_duration:.2f}s")
        print(f"   Effective duration: {data.shape[1] / sampling_rate:.2f}s")
        
        # Check for data loss
        if data.shape[1] < expected_samples * 0.5:
            print("\n[WARNING] Significant data loss detected!")
            print("   Possible causes:")
            print("   - Network congestion")
            print("   - Buffer overflow")
            print("   - Board not in continuous mode")
        
        return data
        
    except Exception as e:
        print(f"\n[ERROR] Recording failed: {e}")
        # Always try to stop stream on error
        try:
            board.stop_stream()
        except:
            pass
        return None


# ====================================================================
#                      DATA ANALYSIS FUNCTIONS
# ====================================================================

def analyze_signal_quality(board: BoardShim, data: np.ndarray) -> None:
    """
    Analyze the recorded EEG data for quality metrics.
    
    This function checks:
    - Hardware timing consistency (from board's internal clock)
    - Signal amplitude (are values in expected range?)
    - Channel statistics (mean, std, min, max)
    - Battery voltage status
    
    Args:
        board: BoardShim object (for metadata)
        data: Recorded data array
    """
    if data is None or data.shape[1] == 0:
        print("\n[ERROR] No data to analyze")
        return
        
    print("\n" + "=" * 60)
    print("SIGNAL QUALITY ANALYSIS")
    print("=" * 60)
    
    # Get board metadata
    sampling_rate = BoardShim.get_sampling_rate(BoardIds.VRCHAT_BOARD.value)
    eeg_channels = BoardShim.get_eeg_channels(BoardIds.VRCHAT_BOARD.value)
    
    try:
        battery_channel = BoardShim.get_battery_channel(BoardIds.VRCHAT_BOARD.value)
    except:
        battery_channel = 16  # Default position
    
    # Hardware timestamp is in channel 17 (resistance_channels[0])
    try:
        resistance_channels = BoardShim.get_resistance_channels(BoardIds.VRCHAT_BOARD.value)
        hw_timestamp_channel = resistance_channels[0] if resistance_channels else 17
    except:
        hw_timestamp_channel = 17  # Default position
    
    print(f"\n[DATA] Data overview:")
    print(f"   Total channels: {data.shape[0]}")
    print(f"   Total samples: {data.shape[1]:,}")
    print(f"   Duration: {data.shape[1] / sampling_rate:.2f}s")
    print(f"   Data rate: {data.shape[1] / (data.shape[1] / sampling_rate):.1f} Hz")
    
    # Analyze battery voltage
    if 0 <= battery_channel < data.shape[0]:
        battery_voltages = data[battery_channel, :]
        avg_battery = np.mean(battery_voltages)
        
        print(f"\n[BATTERY] Power status:")
        print(f"   Average voltage: {avg_battery:.2f}V")
        print(f"   Min voltage: {np.min(battery_voltages):.2f}V")
        print(f"   Max voltage: {np.max(battery_voltages):.2f}V")
        
        if avg_battery < 3.3:
            print("   [WARNING] Low battery voltage!")
        elif avg_battery > 4.3:
            print("   [WARNING] Voltage higher than expected for LiPo battery")
    
    # Analyze hardware timestamps for timing consistency
    if 0 <= hw_timestamp_channel < data.shape[0]:
        hw_timestamps = data[hw_timestamp_channel, :]
        if np.any(hw_timestamps > 0):
            # Hardware timestamp in seconds since board power-on
            time_diffs = np.diff(hw_timestamps)
            expected_interval = 1.0 / sampling_rate
            
            print(f"\n[TIMING] Hardware timestamp analysis:")
            print(f"   Board uptime: {hw_timestamps[-1]:.1f} seconds")
            print(f"   Expected interval: {expected_interval * 1000:.2f} ms")
            print(f"   Actual mean: {np.mean(time_diffs) * 1000:.2f} ms")
            print(f"   Std deviation: {np.std(time_diffs) * 1000:.3f} ms")
            print(f"   Min interval: {np.min(time_diffs) * 1000:.3f} ms")
            print(f"   Max interval: {np.max(time_diffs) * 1000:.3f} ms")
            
            # Check for dropped packets
            gaps = time_diffs > (expected_interval * 2)
            if np.any(gaps):
                gap_count = np.sum(gaps)
                print(f"\n[WARNING] Found {gap_count} timing gaps (possible packet loss)")
                print("   First few gaps:")
                gap_indices = np.where(gaps)[0]
                for idx in gap_indices[:3]:
                    print(f"   - Sample {idx}: {time_diffs[idx] * 1000:.1f} ms gap")
    
    # Analyze EEG channels
    print(f"\n[CHANNELS] Channel statistics (in microvolts):")
    print(f"{'Ch':<4} {'Mean':>8} {'Std':>8} {'Min':>10} {'Max':>10} {'Range':>10}")
    print("-" * 52)
    
    # Check if we're seeing raw ADC values instead of voltage
    first_channel_mean = abs(np.mean(data[eeg_channels[0], :] * 1e6)) if len(eeg_channels) > 0 else 0
    if first_channel_mean > 10000:  # More than 10mV average suggests scaling issue
        print("\n[WARNING] Values appear to be raw ADC counts, not voltage!")
        print("          Displaying raw values divided by 1000 for readability:")
        scale_factor = 1e3  # Show in thousands
        unit = "k"
    else:
        scale_factor = 1e6  # Normal microvolt scaling
        unit = ""
    
    for i in range(min(16, len(eeg_channels))):
        if eeg_channels[i] < data.shape[0]:
            # Scale the data appropriately
            ch_data = data[eeg_channels[i], :] * scale_factor
            
            mean_val = np.mean(ch_data)
            std_val = np.std(ch_data)
            min_val = np.min(ch_data)
            max_val = np.max(ch_data)
            range_val = max_val - min_val
            
            print(f"{i:<4} {mean_val:>8.1f} {std_val:>8.1f} "
                  f"{min_val:>10.1f} {max_val:>10.1f} {range_val:>10.1f}{unit}")
            
            # Check for issues (adjust thresholds based on scaling)
            if scale_factor == 1e6:  # Normal microvolt mode
                if range_val > 1000:  # More than 1000 uV range
                    print(f"     [!] High range - possible noise or movement")
                if abs(mean_val) > 100:  # Large DC offset
                    print(f"     [!] Large DC offset - check electrode contact")
                if std_val < 0.1:  # Almost no variation
                    print(f"     [!] Low variation - possible bad connection")


# ====================================================================
#                      DATA VISUALIZATION FUNCTIONS
# ====================================================================

def plot_eeg_channels(board: BoardShim, data: np.ndarray) -> None:
    """
    Create a comprehensive plot of all 16 EEG channels.
    
    The plot shows:
    - Individual subplots for each channel
    - Time on X-axis, amplitude in microvolts on Y-axis
    - Statistics overlay (mean and standard deviation)
    - Grid for easier reading
    
    Args:
        board: BoardShim object (for metadata)
        data: Recorded data array
    """
    if data is None or data.shape[1] == 0:
        print("\n[ERROR] No data to plot")
        return
        
    print("\n" + "=" * 60)
    print("CREATING VISUALIZATION")
    print("=" * 60)
    
    # Get metadata
    eeg_channels = BoardShim.get_eeg_channels(BoardIds.VRCHAT_BOARD.value)
    sampling_rate = BoardShim.get_sampling_rate(BoardIds.VRCHAT_BOARD.value)
    
    print(f"\n[PLOT] Preparing plot:")
    print(f"   Samples to plot: {data.shape[1]:,}")
    print(f"   Time range: 0 to {data.shape[1] / sampling_rate:.2f}s")
    
    # Create time axis (in seconds)
    time_axis = np.arange(data.shape[1]) / sampling_rate
    
    # Create figure with subplots
    fig, axes = plt.subplots(4, 4, figsize=(16, 12))
    fig.suptitle(
        f'VRChat EEG Board (ID: {BoardIds.VRCHAT_BOARD.value}) - 16 Channel Recording\n'
        f'{data.shape[1]:,} samples @ {sampling_rate} Hz = {data.shape[1]/sampling_rate:.1f} seconds',
        fontsize=16
    )
    axes = axes.flatten()
    
    # Plot each channel
    for i in range(min(16, len(eeg_channels))):
        if i < len(axes) and eeg_channels[i] < data.shape[0]:
            ax = axes[i]
            
            # Get channel data and check if it needs scaling
            ch_data_raw = data[eeg_channels[i], :]
            
            # Auto-detect if we have raw ADC values or proper voltage
            if abs(np.mean(ch_data_raw)) > 0.01:  # Mean > 10mV suggests raw ADC
                ch_data = ch_data_raw / 1000  # Convert to millivolts
                unit_label = 'Amplitude (mV)'
                scale_note = ' [Scaled from ADC]'
            else:
                ch_data = ch_data_raw * 1e6  # Convert to microvolts
                unit_label = 'Amplitude (uV)'
                scale_note = ''
            
            # Plot the signal
            if data.shape[1] < 1000:
                # For short recordings, show individual points
                ax.plot(time_axis, ch_data, 'b.-', linewidth=1, markersize=2)
            else:
                # For longer recordings, just show the line
                ax.plot(time_axis, ch_data, 'b-', linewidth=0.5)
            
            # Configure subplot
            ax.set_title(f'Channel {i}{scale_note}', fontsize=10, fontweight='bold')
            ax.set_xlabel('Time (s)', fontsize=8)
            ax.set_ylabel(unit_label, fontsize=8)
            ax.grid(True, alpha=0.3, linestyle='--')
            
            # Set reasonable Y-axis limits
            ylim_range = max(np.ptp(ch_data) * 0.1, np.std(ch_data) * 4)  # At least 4 std or 10% of range
            ax.set_ylim(np.mean(ch_data) - ylim_range, np.mean(ch_data) + ylim_range)
            
            # Add statistics box
            stats_text = f'u={np.mean(ch_data):.1f}\ns={np.std(ch_data):.1f}'
            ax.text(0.02, 0.98, stats_text, 
                   transform=ax.transAxes, 
                   verticalalignment='top',
                   fontsize=8,
                   bbox=dict(boxstyle='round,pad=0.3', 
                            facecolor='yellow', 
                            alpha=0.7))
    
    # Adjust layout and show
    plt.tight_layout()
    print("\n[DISPLAY] Displaying plot...")
    plt.show()


def plot_channel_stack(board: BoardShim, data: np.ndarray) -> None:
    """
    Create a stacked plot showing all channels together.
    
    This view is useful for:
    - Seeing patterns across channels
    - Identifying common artifacts
    - Quick visual inspection
    - Monitoring battery voltage trend
    
    Args:
        board: BoardShim object (for metadata)
        data: Recorded data array
    """
    if data is None or data.shape[1] < 100:
        return  # Skip if too little data
        
    # Get metadata
    eeg_channels = BoardShim.get_eeg_channels(BoardIds.VRCHAT_BOARD.value)
    sampling_rate = BoardShim.get_sampling_rate(BoardIds.VRCHAT_BOARD.value)
    
    try:
        battery_channel = BoardShim.get_battery_channel(BoardIds.VRCHAT_BOARD.value)
    except:
        battery_channel = 16  # Default position
    
    # Try to get hardware timestamps
    try:
        resistance_channels = BoardShim.get_resistance_channels(BoardIds.VRCHAT_BOARD.value)
        hw_timestamp_channel = resistance_channels[0] if resistance_channels else 17
        
        if hw_timestamp_channel < data.shape[0] and np.any(data[hw_timestamp_channel, :] > 0):
            time_axis = data[hw_timestamp_channel, :]
            time_label = 'Time since board start (seconds)'
        else:
            time_axis = np.arange(data.shape[1]) / sampling_rate
            time_label = 'Time (seconds)'
    except:
        time_axis = np.arange(data.shape[1]) / sampling_rate
        time_label = 'Time (seconds)'
    
    # Create figure with subplots (only add battery subplot if battery channel exists)
    try:
        battery_channel = BoardShim.get_battery_channel(BoardIds.VRCHAT_BOARD.value)
    except:
        battery_channel = 16  # Default position
        
    has_battery = 0 <= battery_channel < data.shape[0] and np.any(data[battery_channel, :] > 0)
    
    if has_battery:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 12), height_ratios=[4, 1])
    else:
        fig, ax1 = plt.subplots(1, 1, figsize=(14, 10))
    
    # Main plot - EEG channels
    channel_data = []
    
    # Check if we need to scale the data
    first_channel = data[eeg_channels[0], :] if len(eeg_channels) > 0 else np.array([0])
    if abs(np.mean(first_channel)) > 0.01:  # Mean > 10mV suggests raw ADC
        scale_factor = 1e-3  # Convert to millivolts
        unit_label = 'mV'
        scale_note = ' (Scaled from ADC values)'
    else:
        scale_factor = 1e6  # Convert to microvolts
        unit_label = 'uV'
        scale_note = ''
    
    for i in range(min(16, len(eeg_channels))):
        if eeg_channels[i] < data.shape[0]:
            channel_data.append(data[eeg_channels[i], :] * scale_factor)
    
    # Use 95th percentile for robust offset calculation
    offset = np.percentile([np.ptp(ch) for ch in channel_data], 95)
    
    # Plot each channel with offset
    for i, ch_data in enumerate(channel_data):
        ax1.plot(time_axis, ch_data + i * offset, linewidth=0.5, label=f'Ch{i}')
    
    ax1.set_xlabel(time_label, fontsize=12)
    ax1.set_ylabel('Channel (with offset)', fontsize=12)
    ax1.set_title(f'VRChat EEG - All Channels Stacked View{scale_note}\n'
                  f'Duration: {data.shape[1]/sampling_rate:.1f}s, '
                  f'Offset: {offset:.0f} {unit_label} between channels', 
                  fontsize=14)
    ax1.grid(True, alpha=0.3, axis='x')
    
    # Add channel labels on the right
    ax1_right = ax1.twinx()
    ax1_right.set_ylim(ax1.get_ylim())
    ax1_right.set_yticks([i * offset for i in range(len(channel_data))])
    ax1_right.set_yticklabels([f'Ch{i}' for i in range(len(channel_data))])
    ax1_right.set_ylabel('Channel Number', fontsize=12)
    
    # Battery voltage plot (only if battery channel exists)
    if has_battery:
        battery_voltages = data[battery_channel, :]
        ax2.plot(time_axis, battery_voltages, 'r-', linewidth=1)
        ax2.set_xlabel(time_label, fontsize=12)
        ax2.set_ylabel('Battery (V)', fontsize=12)
        ax2.grid(True, alpha=0.3)
        ax2.set_ylim(min(3.0, np.min(battery_voltages) - 0.1), 
                     max(4.5, np.max(battery_voltages) + 0.1))
        
        # Add battery status text
        avg_battery = np.mean(battery_voltages)
        battery_status = f'Avg: {avg_battery:.2f}V'
        if avg_battery < 3.3:
            battery_status += ' - LOW!'
        ax2.text(0.02, 0.95, battery_status, transform=ax2.transAxes,
                 verticalalignment='top', fontsize=10,
                 bbox=dict(boxstyle='round,pad=0.3', 
                          facecolor='yellow' if avg_battery < 3.5 else 'lightgreen',
                          alpha=0.7))
    
    plt.tight_layout()
    plt.show()


# ====================================================================
#                         MAIN PROGRAM FLOW
# ====================================================================

def main():
    """
    Main program flow - orchestrates the entire test sequence.
    
    The flow:
    1. Try auto-discovery to find the board
    2. Fall back to manual IP if needed  
    3. Configure the board's filters and settings
    4. Record EEG data for specified duration
    5. Analyze signal quality
    6. Create visualizations
    7. Clean up resources
    """
    print("\n" + "=" * 80)
    print(" " * 20 + "VRCHAT EEG BOARD TEST SUITE")
    print(" " * 15 + "Auto-Discovery & Signal Recording")
    print("=" * 80)
    
    # Show debug mode status
    if DEBUG_MODE:
        print("\n[DEBUG] DEBUG MODE ENABLED")
        print("   You will see detailed output from the C++ driver")
        print("   Set DEBUG_MODE = False to disable")
        BoardShim.enable_dev_board_logger()
    else:
        print("\n[QUIET] Debug mode disabled (set DEBUG_MODE = True to enable)")
        BoardShim.disable_board_logger()
    
    # Display expected channel layout
    print("\n[INFO] Expected channel layout:")
    print("   0-15: EEG channels")
    print("   16:   Battery voltage") 
    print("   17:   Hardware timestamp (board uptime)")
    print("   18:   Marker channel")
    print("   19-20: Reserved")
    print("   Total: 21 channels")
    
    board = None
    
    try:
        # ---------- CONNECTION PHASE ----------
        print("\n" + "-" * 60)
        print("PHASE 1: ESTABLISH CONNECTION")
        print("-" * 60)
        
        # Try auto-discovery first
        board = discover_board(timeout_ms=DISCOVERY_TIMEOUT, debug=DEBUG_MODE)
        
        # If that fails, try with retries
        if board is None:
            print("\n[RETRY] Single discovery failed, trying with retries...")
            board = connect_with_retries(max_attempts=3)
        
        # If still no connection, offer manual IP entry
        if board is None:
            print("\n[?] Would you like to enter the board IP manually? (y/n): ", end='')
            if input().strip().lower() == 'y':
                board = connect_manual_ip()
        
        # Exit if no connection
        if board is None:
            print("\n[ERROR] Could not establish connection to board")
            print("   Please check your setup and try again")
            return
        
        # ---------- CONFIGURATION PHASE ----------
        print("\n" + "-" * 60)
        print("PHASE 2: CONFIGURE BOARD SETTINGS")
        print("-" * 60)
        time.sleep(1)  # Brief pause for readability
        
        configure_board_filters(board)
        
        # ---------- RECORDING PHASE ----------
        print("\n" + "-" * 60)
        print("PHASE 3: RECORD EEG DATA")
        print("-" * 60)
        time.sleep(1)
        
        data = record_eeg_data(board, duration_seconds=DEFAULT_RECORD_DURATION)
        
        if data is None:
            print("\n[ERROR] Recording failed - no data to analyze")
            return
        
        # ---------- ANALYSIS PHASE ----------
        print("\n" + "-" * 60)
        print("PHASE 4: ANALYZE SIGNAL QUALITY")
        print("-" * 60)
        time.sleep(1)
        
        analyze_signal_quality(board, data)
        
        # ---------- VISUALIZATION PHASE ----------
        print("\n" + "-" * 60)
        print("PHASE 5: VISUALIZE DATA")
        print("-" * 60)
        time.sleep(1)
        
        plot_eeg_channels(board, data)
        plot_channel_stack(board, data)
        
    except KeyboardInterrupt:
        print("\n\n[!] Test interrupted by user (Ctrl+C)")
        
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # ---------- CLEANUP PHASE ----------
        print("\n" + "-" * 60)
        print("PHASE 6: CLEANUP")
        print("-" * 60)
        
        if board and board.is_prepared():
            try:
                # Make sure streaming is stopped
                if board.is_prepared():
                    try:
                        board.stop_stream()
                    except:
                        pass  # Already stopped
                        
                board.release_session()
                print("\n[SUCCESS] Board session released successfully")
            except Exception as e:
                print(f"\n[WARNING] Error during cleanup: {e}")
        
        print("\n" + "=" * 60)
        print("Test session completed. Thank you!")
        print("=" * 60)


if __name__ == "__main__":
    main()