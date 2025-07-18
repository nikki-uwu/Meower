# ESP32-C3 16-Channel WiFi EEG/BCI Board

## 🧠 Project Overview

A 16-channel biosignal acquisition board built with ESP32-C3 and dual ADS1299 chips. This wireless brain-computer interface captures EEG, ECG, EMG, and other biosignals with research-grade quality. Designed for BCI enthusiasts and researchers who want an easy-to-use board that streams real-time data over WiFi at up to 4000 Hz - just power on, connect, and start recording.

## 📚 What's in This Guide

| Section | Description |
|---------|-------------|
| **1. ⚡ Quick Start** | Get data flowing in under 10 minutes |
| **2. 🔧 Building From Source** | Compile and upload custom firmware |
| **3. 📊 Data Format** | Channel mapping and packet structure |
| **4. 🎛️ Configuration** | Commands and settings |
| **5. 📈 Specifications** | Technical details and performance |
| **6. 🛠️ Troubleshooting** | Common issues and solutions |
| **7. 🔌 Software Integration** | Code examples and compatible apps |
| **8. ⚠️ Safety** | Important usage guidelines |
| **9. 🤝 Community** | Getting help and contributing |
| **10. 📄 License** | Usage rights and credits |

## 1. ⚡ Quick Start

### What You'll Need
- Meower board (this board)
- USB-C cable (data capable, not charge-only)
- 3.7V LiPo battery (optional, 1100mAh gives 10+ hours)
- Computer with WiFi (Windows/Mac/Linux)
- 2.4GHz WiFi network (or use serial configuration)
- No drivers needed - ESP32-C3 has built-in USB!

**Note**: Board IP can be auto-discovered - no need to know it in advance!

### Configure WiFi Settings (Choose One Method)

#### Method 1: WiFi Access Point with Auto-Discovery
1. **Power on** - Board broadcasts UDP beacons
2. **Connect to WiFi hotspot**: `EEG-SETUP` (password: `password`)
3. **Open browser**: Navigate to `http://192.168.4.1`
4. **Enter your settings**:
   - WiFi network name (SSID)
   - WiFi password
   - Your PC's IP address (or leave empty for auto-discovery)
   - Ports (default: 5000 control, 5001 data)
5. **Click "Save and Restart"**

**Auto-Discovery**: If you don't specify board IP in your software, it will automatically find the board via UDP beacons on port 5000 (wait up to 3 seconds by default).

#### Method 2: Serial Configuration (More Control)
1. **Connect via USB** and open serial terminal (115200 baud)
2. **Type commands**:
   ```
   set ssid YourWiFiName
   set pass YourWiFiPassword  
   set ip [Your PC's IP address]
   set port_ctrl 5000
   set port_data 5001
   show
   apply
   ```
3. Board restarts with new settings

**Note**: 
- Serial configuration works at ANY time - even if board is already running
- Password is visible in terminal - use for debugging/setup only
- If board doesn't respond to network commands, connect serial to update settings
- For verbose debug output, set `#define SERIAL_DEBUG 1` in `defines.h`

### LED Status Patterns
After configuration, the LED shows board status:
- **Rapid flashing**: Network setup mode (Access Point active)
- **3 blinks**: Cannot connect to WiFi
- **2 blinks**: Connected to WiFi (not streaming)
- **1 blink every 5 seconds**: Streaming data
- **5 blinks**: [To be confirmed - possibly error state]

## 2. 🔧 Building From Source

### Prerequisites
| Software | Version | Download |
|----------|---------|----------|
| Git | Latest | [git-scm.com](https://git-scm.com) |
| VS Code | Latest | [code.visualstudio.com](https://code.visualstudio.com) |
| PlatformIO | Extension | Install within VS Code |

### Build Steps
1. **Clone the repository** to your local machine
2. **Open VS Code**
3. **Click on PlatformIO extension** in the left sidebar (default layout)
4. **In Quick Access** (usually lower left), find "PlatformIO Home" section
5. **Click "Open"** inside that section - should bring you to PIO Home tab
   - (If lost, google "how to open PIO home" :3)
6. **Click "Open Project"** on the PIO Home page
7. **Select the cloned folder**
8. **Wait for dependencies** to download (first time ~5 minutes)
   - Let it fully download all dependencies
   - **Restart VS Code** after downloads complete
9. **Connect board** via data-capable USB-C cable (not charge-only!)
10. **Click arrow (→)** to build and upload
    - Or click checkmark (✓) to build first, then arrow

### Troubleshooting Upload Issues
- **Other USB devices can interfere**: Disconnect USB audio interfaces, cameras, USB hubs, etc.
- **Ensure no other programs are using the COM port**: Close any serial terminals, Arduino IDE, etc.
- **Windows "Restart apps" setting**: Go to Settings → Accounts → Sign-in options → Turn OFF "Use my sign-in info to automatically finish setting up after an update or restart" - this can keep apps running in background
- **Full restart recommended**: Restart PC and don't open any apps before uploading
- **No BOOT button needed**: Just connect USB and power on
- **CH340 drivers**: ESP32-C3 has built-in USB - no drivers needed! (Unlike older ESP32)
- If still having issues, try a different USB cable or port

## 3. 📊 Data Format & Channel Mapping

### Channel Numbering
```
┌─────────────────────────────────┐
│         CHANNEL MAP             │
├─────────────────────────────────┤
│ Ch 0-7:  Master ADS1299 (U1)    │
│ Ch 8-15: Slave ADS1299 (U2)     │
│                                 │
│ Standard 10-20 Mapping:         │
│ Ch0 → Fp1    Ch8  → Fp2         │
│ Ch1 → F3     Ch9  → F4          │
│ Ch2 → C3     Ch10 → C4          │
│ Ch3 → P3     Ch11 → P4          │
│ Ch4 → O1     Ch12 → O2          │
│ Ch5 → F7     Ch13 → F8          │
│ Ch6 → T3     Ch14 → T4          │
│ Ch7 → T5     Ch15 → T6          │
└─────────────────────────────────┘
```

### UDP Packet Structure

The board always sends data in a single UDP datagram (no fragmentation). You can safely read with a 1500-byte buffer.

```
┌─────────────────────────────────────────────────────────────────────┐
│                    UDP Packet (max 1472 bytes)                      │
├─────────────────────────────────────────────────────────────────────┤
│ Frame 1 │ Frame 2 │ Frame 3 │ ... │ Frame N │ Battery Voltage       │
│ 52 bytes│ 52 bytes│ 52 bytes│     │(max 28) │ 4 bytes (float32)     │
└─────────────────────────────────────────────────────────────────────┘
                          │
                          ▼ Zoom into one frame
        ┌─────────────────────────────────────────────────┐
        │              Data Frame (52 bytes)              │
        ├─────────────────────────────────────────────────┤
        │        ADC Data         │   Hardware Timestamp  │
        │       48 bytes          │   4 bytes (uint32)    │
        └─────────────────────────────────────────────────┘
                    │
                    ▼ Zoom into ADC data
    ┌─────────────────────────────────────────────────────────────────┐
    │                     ADC Data (48 bytes)                         │
    ├─────────────────────────────────────────────────────────────────┤
    │ Ch1   │ Ch2   │ Ch3   │ Ch4   │ Ch5   │ ... │ Ch15  │ Ch16      │
    │3 bytes│3 bytes│3 bytes│3 bytes│3 bytes│     │3 bytes│3 bytes    │
    │ 24bit │ 24bit │ 24bit │ 24bit │ 24bit │     │ 24bit │ 24bit     │
    └─────────────────────────────────────────────────────────────────┘
```

### Why Single UDP Datagram?

The board packs multiple frames into one UDP packet for critical performance reasons:

1. **Latency Optimization**: Each UDP packet has overhead (headers, kernel processing). Sending 28 frames in one packet instead of 28 individual packets reduces this overhead by 28x.

2. **Network Efficiency**: 
   - Single packet: 1472 bytes payload + 28 bytes headers = 1500 bytes total
   - 28 individual packets: 1456 bytes payload + 784 bytes headers = 2240 bytes total
   - That's 49% more bandwidth wasted on headers!

3. **Atomic Delivery**: UDP delivers the entire datagram or nothing. You either get all 28 frames intact or none - no partial data corruption.

4. **Jitter Reduction**: Sending one packet every 56ms (at 500Hz) creates more consistent timing than 28 packets with microsecond gaps.

5. **MTU Compliance**: At 1472 bytes, we stay under the standard Ethernet MTU of 1500 bytes, avoiding fragmentation which can cause packet loss.

**Technical Details**:
- **MTU Calculation**: Ethernet MTU (1500) - IP header (20) - UDP header (8) = 1472 bytes usable
- **Max frames**: (1472 - 4) / 52 = 28 frames maximum per packet
- **Timestamp units**: Hardware timestamp counts in 8 microsecond increments
- **Byte order** (verified from source code): 
  - Channel data: **Big-endian** (MSB first) - ADS1299 outputs this way
  - Timestamp: **Little-endian** - ESP32 native format for efficiency  
  - Battery: **Little-endian** (IEEE 754 float) - ESP32 native format

### Basic Data Parsing

Here's how to parse the UDP datagram, closely following the C implementation:

```python
def parse_24bit_sample(byte0, byte1, byte2):
    """
    Convert 24-bit signed big-endian sample to float.
    This matches the C code exactly from vrchat_board.cpp
    
    Args:
        byte0: MSB (most significant byte)
        byte1: Middle byte  
        byte2: LSB (least significant byte)
        
    Returns:
        Float value of the raw ADC count
    """
    # Combine 3 bytes into 24-bit value (big-endian)
    # This matches C code: (frame_data[byte_offset] << 16) | (frame_data[byte_offset + 1] << 8) | frame_data[byte_offset + 2]
    raw_24bit = (byte0 << 16) | (byte1 << 8) | byte2
    
    # Sign extension: Convert 24-bit signed to 32-bit signed
    # Check if negative (bit 23 set, which is 0x800000)
    if raw_24bit & 0x800000:
        # Sign extend to 32-bit by setting upper bits
        # This matches C code: (int32_t)(raw_24bit << 8) >> 8
        raw_24bit |= 0xFF000000
        # Convert to signed integer
        import struct
        raw_value = struct.unpack('>i', struct.pack('>I', raw_24bit))[0]
    else:
        # Positive value - use as is
        raw_value = raw_24bit
    
    # Return as float (no gain, no scaling - just raw ADC count)
    return float(raw_value)


def parse_eeg_datagram(udp_data):
    """
    Parse UDP datagram containing EEG frames and battery voltage.
    Handles variable number of frames (1-28) automatically.
    This closely mirrors the C code in vrchat_board.cpp.
    
    Args:
        udp_data: Raw bytes from UDP packet
        
    Returns:
        frames: List of dicts with 'channels' and 'timestamp'
        battery_voltage: Float voltage in volts
    """
    # Constants from defines.h and vrchat_board.cpp
    CHANNELS_PER_BOARD = 16
    BYTES_PER_CHANNEL = 3  # 24-bit samples
    CHANNEL_DATA_SIZE = CHANNELS_PER_BOARD * BYTES_PER_CHANNEL  # 48 bytes
    TIMESTAMP_SIZE = 4  # 32-bit timestamp
    FRAME_SIZE = CHANNEL_DATA_SIZE + TIMESTAMP_SIZE  # 52 bytes
    BATTERY_SIZE = 4  # 32-bit float
    
    # Validate packet size (matches C validation)
    packet_size = len(udp_data)
    if packet_size < FRAME_SIZE + BATTERY_SIZE:
        raise ValueError(f"Packet too small: {packet_size} bytes (minimum: {FRAME_SIZE + BATTERY_SIZE})")
    
    # Calculate number of frames - exactly like C code
    if (packet_size - BATTERY_SIZE) % FRAME_SIZE != 0:
        raise ValueError(f"Invalid packet size: {packet_size} bytes")
    
    num_frames = (packet_size - BATTERY_SIZE) // FRAME_SIZE
    
    frames = []
    
    # Process each frame - matches C loop structure
    for frame_idx in range(num_frames):
        # Calculate offset to current frame
        frame_offset = frame_idx * FRAME_SIZE
        
        # Extract 16 channels (48 bytes)
        channels = []
        for ch in range(CHANNELS_PER_BOARD):
            # Calculate byte offset for this channel
            byte_offset = frame_offset + (ch * BYTES_PER_CHANNEL)
            
            # Extract 3 bytes and convert to signed value
            raw_value = parse_24bit_sample(
                udp_data[byte_offset],
                udp_data[byte_offset + 1],
                udp_data[byte_offset + 2]
            )
            
            channels.append(raw_value)
        
        # Extract hardware timestamp (4 bytes, little-endian)
        # Matches C: memcpy(&dataBuffer[bytesWritten + ADC_PARSED_FRAME], &timeStamp, sizeof(timeStamp))
        timestamp_offset = frame_offset + CHANNEL_DATA_SIZE
        import struct
        hw_timestamp = struct.unpack('<I', udp_data[timestamp_offset:timestamp_offset + 4])[0]
        
        # Timestamp is in 8 microsecond units (from getTimer8us() in C code)
        frames.append({
            'channels': channels,  # Raw ADC counts as floats
            'timestamp': hw_timestamp  # Raw timestamp value (multiply by 8 for microseconds)
        })
    
    # Extract battery voltage (last 4 bytes, little-endian float)
    # Matches C: memcpy(&txBuf[ADC_PACKET_BYTES], &vbatt, Battery_Sense::DATA_SIZE)
    battery_offset = num_frames * FRAME_SIZE
    battery_voltage = struct.unpack('<f', udp_data[battery_offset:battery_offset + 4])[0]
    
    return frames, battery_voltage
```

**Note**: 
- To convert raw ADC counts to voltage: multiply by `4.5 / (2^23) = 0.536 µV/count`
- To convert timestamp to microseconds: multiply by 8
- The parsing exactly matches the C implementation for compatibility

For complete examples including:
- Full UDP receiver with keep-alive
- Real-time plotting GUI
- Data recording and playback
- Filtering and processing

Check the `python/` folder in the repository which contains a complete working application with GUI and all parsing logic.

### Data Conversion Reference

The ADS1299 outputs 24-bit signed values. To convert to physical units:

```
Raw ADC value → Voltage conversion:
- LSB size = 4.5V / (2^23) = 0.536 microvolts per count
- Voltage = raw_value * 0.536 µV (at gain=1)

For other gains, divide by the gain setting:
- Gain 1:  ±4.5V range
- Gain 2:  ±2.25V range  
- Gain 4:  ±1.125V range
- Gain 6:  ±750mV range
- Gain 8:  ±562.5mV range
- Gain 12: ±375mV range
- Gain 24: ±187.5mV range
```

**Important Notes**:
- Channel data arrives in **big-endian** format (verified in source)
- Timestamps and battery voltage are **little-endian**
- Timestamp increments every 8 microseconds
- Battery voltage is standard IEEE 754 32-bit float

## 4. 🎛️ Configuration & Control

### Network Ports & Communication
- **Control Port**: 5000 (UDP) - Commands and configuration
- **Data Port**: 5001 (UDP) - EEG data stream
- **Keep-Alive**: Board requires "floof" message every 5 seconds or stops streaming after ~100s
- **Auto-Discovery**: Board sends beacons to control port when not connected

### Command Reference
Send these commands to the control port as UTF-8 strings:

| Command | Description | Example |
|---------|-------------|---------|
| `sys start_cnt` | Start continuous streaming | Begin data acquisition |
| `sys stop_cnt` | Stop continuous streaming | Halt data acquisition |
| `sys adc_reset` | Reset ADS1299 chips | Full hardware reset |
| `sys esp_reboot` | Reboot ESP32 | Soft restart |
| `sys filters_on` | Enable all filters | Activate DSP |
| `sys filters_off` | Disable all filters | Raw data only |
| `sys filter_dc_on` | Enable DC blocking | Remove DC offset |
| `sys filter_5060_on` | Enable 50/60Hz notch | Remove mains noise |
| `sys digitalgain [1-256]` | Set digital gain | `sys digitalgain 8` |
| `sys networkfreq [50\|60]` | Set mains frequency | `sys networkfreq 60` |
| `sys dccutofffreq [0.5\|1\|2\|4\|8]` | DC filter cutoff | `sys dccutofffreq 1` |

### Reset to Setup Mode
Need to reconfigure WiFi? Toggle power:
1. Turn OFF
2. Turn ON 
3. Turn OFF
4. Turn ON
5. Turn OFF
6. Turn ON

All within 5 seconds. Board will create `EEG-SETUP` hotspot again.

### Serial Configuration (Backup)
Connect at 115200 baud:
```
set ssid YourWiFiName
set pass YourWiFiPassword  
set ip 192.168.1.100
set port_ctrl 5000
set port_data 5001
show
apply
```

**Note**: Password is visible in serial output. Use for debugging only.

## 5. 📈 Specifications

### Hardware
- **Microcontroller**: ESP32-C3 (RISC-V, 160MHz, WiFi 2.4GHz)
- **ADC**: 2× Texas Instruments ADS1299 (24-bit, 8 channels each)
- **Channels**: 16 differential inputs
- **Sampling Rates**: 250, 500, 1000, 2000, 4000 Hz
- **Resolution**: 24-bit (0.536 μV/bit at gain=1)
- **Input Range**: ±4.5V (before gain)
- **Voltage Range by Gain**:
  - Gain 1: ±4.5V
  - Gain 2: ±2.25V
  - Gain 4: ±1.125V
  - Gain 6: ±750mV
  - Gain 8: ±562.5mV
  - Gain 12: ±375mV
  - Gain 24: ±187.5mV
- **Input Impedance**: 10 GΩ
- **Noise**: <1 μVpp (0.01-70 Hz, gain=24)
- **CMRR**: -110 dB

### Performance
- **Power Consumption**: ~400mW (streaming at 250Hz)
- **Battery Life**: 10+ hours with 1100mAh LiPo
- **WiFi Range**: 30m typical indoor
- **Network Latency**: <10ms typical
- **Maximum Data Rate**: ~1.5 Mbps at 4000Hz

## 6. 🛠️ Troubleshooting

### Board Not Detected
1. Check USB cable (must support data, not charge-only)
2. Install CH340 drivers if needed
3. Try different USB port
4. Check Device Manager (Windows) or `ls /dev/tty*` (Linux/Mac)

### Can't Connect to WiFi
1. Ensure 2.4GHz network (5GHz not supported)
2. Check password (case sensitive)
3. Verify router allows new devices
4. Try WPA2 (WPA3 may cause issues)
5. Check serial output for error messages

### No Data Received
1. Verify PC firewall allows UDP port 5001
2. Check PC IP matches board configuration
3. Send `sys start_cnt` command to begin streaming
4. Confirm LED shows streaming pattern (1 blink/5s)
5. Try simple UDP listener to test connectivity

### Noisy or Bad Signals
1. Check electrode connections (should be snug)
2. Verify skin preparation (clean with alcohol)
3. Measure impedance (<5kΩ recommended)
4. Enable filters: `sys filters_on`
5. Check ground and reference electrode placement
6. Move away from AC power sources
7. Ensure battery powered during use

## 7. 🔌 Software Integration

### Python Quick Start
```python
import socket
import struct
import time

# Setup
BOARD_IP = "192.168.1.100"  # Your board's IP (or use auto-discovery)
PC_IP = "0.0.0.0"           # Listen on all interfaces

# Create sockets
data_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
data_sock.bind((PC_IP, 5001))
data_sock.settimeout(1.0)  # 1 second timeout

ctrl_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Start streaming
ctrl_sock.sendto(b"sys start_cnt", (BOARD_IP, 5000))

# Keep-alive thread (required!)
def send_keepalive():
    while True:
        ctrl_sock.sendto(b"floof", (BOARD_IP, 5000))
        time.sleep(5)

import threading
keepalive_thread = threading.Thread(target=send_keepalive, daemon=True)
keepalive_thread.start()

# Parse function (matches C implementation)
def parse_24bit_to_float(b0, b1, b2):
    """Convert 3 bytes (big-endian) to signed float"""
    raw = (b0 << 16) | (b1 << 8) | b2
    if raw & 0x800000:  # Check sign bit
        raw |= 0xFF000000  # Sign extend
        raw = struct.unpack('>i', struct.pack('>I', raw))[0]
    return float(raw)

# Receive data
while True:
    try:
        # Read complete datagram (up to 1500 bytes)
        data, addr = data_sock.recvfrom(1500)
        
        # Calculate frames (packet size - battery) / frame size
        num_frames = (len(data) - 4) // 52
        
        # Extract battery (last 4 bytes)
        battery = struct.unpack('<f', data[-4:])[0]
        
        # Process each frame
        for i in range(num_frames):
            frame_start = i * 52
            
            # Parse first channel as example
            ch0_raw = parse_24bit_to_float(
                data[frame_start], 
                data[frame_start + 1], 
                data[frame_start + 2]
            )
            
            # Get timestamp (little-endian, 8µs units)
            ts = struct.unpack('<I', data[frame_start + 48:frame_start + 52])[0]
            
            # Convert to physical units if needed
            ch0_uV = ch0_raw * 0.536  # At gain=1
            ts_ms = ts * 0.008  # Convert to milliseconds
            
            print(f"Time: {ts_ms:.1f}ms, Ch0: {ch0_uV:.2f}µV, Battery: {battery:.2f}V")
            
    except socket.timeout:
        continue
```

### Compatible Software
- **BrainFlow**: Full support with auto-discovery
  ```python
  # Auto-discovery example
  params = BrainFlowInputParams()
  # params.ip_address = ""  # Leave empty for auto-discovery!
  params.ip_port = 5001
  params.ip_port_aux = 5000
  params.other_info = "discovery_timeout=5000"  # Optional: 5s timeout
  
  board = BoardShim(BoardIds.VRCHAT_BOARD, params)
  board.prepare_session()  # Will find board automatically
  ```
- **OpenViBE**: Use Acquisition Server with custom driver
- **LabStreamingLayer**: Python script included for LSL streaming
- **MATLAB**: UDP receiver examples provided
- **Processing/P5.js**: Real-time visualization examples

## 8. ⚠️ Safety Information

> **WARNING**: This device is for education and research only. Not a medical device. Do not use for diagnosis or treatment.

### Electrical Safety
- Only use battery power when connected to body
- Device provides WiFi isolation from mains power
- Current limited design (<10μA fault current)
- CE/FCC compliance pending

### Best Practices
- Always use proper EEG gel or saline
- Clean electrode sites with 70% alcohol
- Check impedances before recording
- Take breaks during long sessions
- Stop if skin irritation occurs

## 9. 🤝 Community & Support

### Getting Help
- **GitHub Issues**: Bug reports and feature requests
- **Discord**: [Join our community]
- **Email**: support@[yourdomain].com

### Contributing
- Hardware improvements welcome (KiCad files included)
- Firmware contributions via pull request
- Documentation improvements always needed
- Share your projects and use cases!

## 10. 📄 License

- **Hardware**: CERN Open Hardware License v2
- **Firmware**: MIT License
- **Documentation**: CC BY-SA 4.0

---

*Built with ❤️ for the BCI community*