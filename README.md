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
│ Frame 1 │ Frame 2 │ Frame 3 │ ... │ Frame N │ Battery Voltage     │
│ 52 bytes│ 52 bytes│ 52 bytes│     │(max 28) │ 4 bytes (float32)   │
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
    │ Ch1   │ Ch2   │ Ch3   │ Ch4   │ Ch5   │ ... │ Ch15  │ Ch16    │
    │3 bytes│3 bytes│3 bytes│3 bytes│3 bytes│     │3 bytes│3 bytes  │
    │ 24bit │ 24bit │ 24bit │ 24bit │ 24bit │     │ 24bit │ 24bit  │
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

The 48-byte ADC data contains 16 channels, each using 3 bytes (24 bits) in big-endian format:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        48 Bytes of ADC Data                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ Ch0    │ Ch1    │ Ch2    │ Ch3    │ ... │ Ch14   │ Ch15   │               │
│ 3 bytes│ 3 bytes│ 3 bytes│ 3 bytes│     │ 3 bytes│ 3 bytes│               │
└─────────────────────────────────────────────────────────────────────────────┘
     ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                    One Channel = 3 Bytes (Big-Endian)                      │
├─────────────────────────────────────────────────────────────────────────────┤
│     Byte 0      │     Byte 1      │     Byte 2      │                     │
│   MSB (b0)      │   Middle (b1)   │    LSB (b2)     │                     │
│  [7 6 5 4 3 2 1 0] [7 6 5 4 3 2 1 0] [7 6 5 4 3 2 1 0]                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Step 1: Combine 3 bytes into 24-bit value**
```
raw_24bit = (b0 << 16) | (b1 << 8) | b2

Example: b0=0x80, b1=0x00, b2=0x00
         10000000 00000000 00000000  = 0x800000 (bit 23 is set = negative)
         ↑
         Sign bit (bit 23)
```

**Step 2: Sign Extension (24-bit → 32-bit)**
```
Method: Shift left by 8, then arithmetic shift right by 8

Original 24-bit:  ???????? 10000000 00000000 00000000  (? = undefined)
                           ↑ bit 23 (sign)

After << 8:       10000000 00000000 00000000 ????????  (sign now at bit 31)
                  ↑ bit 31 (sign position in int32)

After >> 8:       11111111 10000000 00000000 00000000  (sign extended)
                  ↑ sign bits filled in

Result: -8,388,608 (proper negative int32)
```

**Quick Reference**
```python
# Parse one 24-bit sample (Python)
def parse_24bit_sample(b0, b1, b2):
    # Step 1: Combine bytes (big-endian)
    raw_24bit = (b0 << 16) | (b1 << 8) | b2
    
    # Step 2: Sign extend if negative
    if raw_24bit & 0x800000:  # Check bit 23
        raw_24bit |= 0xFF000000  # Set upper 8 bits
        # Convert unsigned to signed
        import struct
        raw_24bit = struct.unpack('>i', struct.pack('>I', raw_24bit))[0]
    
    return float(raw_24bit)
```

For complete UDP datagram parsing including frame validation and battery extraction, see the `python/` folder which contains full working examples.

### Data Conversion Reference

The ADS1299 outputs 24-bit signed values. To convert to physical units:

```
Raw ADC value → Voltage conversion:
- LSB size = 4.5V / (2^23) = 0.536 microvolts per count
- Voltage = raw_value * 0.536 µV (at hardware gain=1)
```

**Digital Gain Note**: 
This board uses digital gain (bit shifting) which reduces the maximum voltage range before the signal saturates the 24-bit output:

```
Digital Gain Settings and Maximum Input Range:
- Gain 1:  ±4.5V  (full ADC range)
- Gain 2:  ±2.25V (saturates at ±2.25V)
- Gain 4:  ±1.125V (saturates at ±1.125V)
- Gain 8:  ±562.5mV (saturates at ±562.5mV)
- Gain 16: ±281.25mV (saturates at ±281.25mV)

Example: With digital gain=8, a ±600mV signal will clip/overflow
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
- **Input Range**: ±4.5V (before digital gain)
- **Digital Gain**: 1, 2, 4, 8, 16, 32, 64, 128, 256 (reduces max input before saturation)
- **Input Impedance**: 10 GΩ
- **Noise**: <1 μVpp (0.01-70 Hz, typical)
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
