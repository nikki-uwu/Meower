# ESP32-C3 16-Channel WiFi EEG/BCI Board

## 🧠 Project Overview

A 16-channel biosignal acquisition board built with ESP32-C3 and dual ADS1299 chips. This wireless brain-computer interface captures EEG, ECG, EMG, and other biosignals with research-grade quality. Designed for BCI enthusiasts and researchers who want an easy-to-use board that streams real-time data over WiFi at up to 4000 Hz - just power on, connect, and start recording.

## 2. ⚠️ Safety Information

**WARNING**: This device is for education and research only. Not a medical device. Do not use for diagnosis or treatment. **Use battery power only** - USB introduces significant noise that ruins signal quality.

### Performance & Noise Considerations
Even from a pure performance standpoint, battery operation is essential - not just for safety. Any USB connection introduces significant noise into the measurements. USB ground loops, switching power supplies, and computer interference can severely degrade signal quality. Always disconnect USB after configuration for research-quality recordings.

## 📚 What's in This Guide

| Section | Description |
|---------|-------------|
| **1. 🧠 Project Overview** | What this board is and does |
| **2. ⚠️ Safety Information** | Critical safety and performance guidelines |
| **3. ⚡ Quick Start** | Get data flowing in under 10 minutes |
| **4. 🔧 Building From Source** | Compile and upload custom firmware |
| **5. 📊 Data Format** | Channel mapping and packet structure |
| **6. 🎛️ Configuration** | Commands and settings |
| **7. 🔬 Raw SPI Access** | Direct ADC communication |
| **8. 📈 Specifications** | Technical details and performance |
| **9. 🛠️ Troubleshooting** | Common issues and solutions |

## 3. ⚡ Quick Start

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

## 4. 🔧 Building From Source

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

## 5. 📊 Data Format & Channel Mapping

### Channel Numbering

[Channel mapping diagram - to be added]

**Channel Assignment:**
- Channels 0-7: Master ADS1299 (U1)
- Channels 8-15: Slave ADS1299 (U2)

**Standard 10-20 System Mapping:**
- Ch0 → Fp1, Ch8 → Fp2
- Ch1 → F3, Ch9 → F4
- Ch2 → C3, Ch10 → C4
- Ch3 → P3, Ch11 → P4
- Ch4 → O1, Ch12 → O2
- Ch5 → F7, Ch13 → F8
- Ch6 → T3, Ch14 → T4
- Ch7 → T5, Ch15 → T6

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

The 48-byte ADC data contains 16 channels, each using 3 bytes (24 bits) in big-endian format:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        48 Bytes of ADC Data                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ Ch0    │ Ch1    │ Ch2    │ Ch3    │ ... │ Ch14   │ Ch15   │                 │
│ 3 bytes│ 3 bytes│ 3 bytes│ 3 bytes│     │ 3 bytes│ 3 bytes│                 │
└─────────────────────────────────────────────────────────────────────────────┘
     ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                    One Channel = 3 Bytes (Big-Endian)                       │
├─────────────────────────────────────────────────────────────────────────────┤
│      Byte 0        │     Byte 1        │     Byte 2                         │
│     MSB (b0)       │    Middle (b1)    │    LSB (b2)                        │
│  [7 6 5 4 3 2 1 0]   [7 6 5 4 3 2 1 0]   [7 6 5 4 3 2 1 0]                  │
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

## 6. 🎛️ Configuration & Control

### Network Ports & Communication
- **Control Port**: 5000 (UDP) - Commands and configuration (default, configurable)
- **Data Port**: 5001 (UDP) - EEG data stream (default, configurable)
- **Keep-Alive**: Board requires "floof" message every 5 seconds or stops streaming after ~10s
- **Auto-Discovery**: Board sends beacons on control port when not connected, allowing PC to grab board's IP address

### Command Reference
Send these commands to the control port as UTF-8 strings:

| Command | Description | Example |
|---------|-------------|---------|
| `sys start_cnt` | Start continuous streaming | Begin data acquisition |
| `sys stop_cnt` | Stop continuous streaming | Halt data acquisition |
| `sys adc_reset` | Full ADS1299 hardware reset + sync | Resets both ADCs to synced state |
| `sys esp_reboot` | Full hardware reboot (ESP32 + ADCs) | Complete system restart |
| `sys erase_flash` | Erase WiFi credentials | Force setup mode on next boot |
| **Filter Master Controls** | | |
| `sys filters_on` | Enable ALL filters | Master filter switch ON |
| `sys filters_off` | Disable ALL filters | Master filter switch OFF |
| **Individual Filter Controls** | | |
| `sys filter_equalizer_on` | Enable FIR equalizer | Compensate ADC frequency response |
| `sys filter_equalizer_off` | Disable FIR equalizer | Raw ADC response |
| `sys filter_dc_on` | Enable DC blocking filter | Remove DC offset |
| `sys filter_dc_off` | Disable DC blocking filter | Keep DC component |
| `sys filter_5060_on` | Enable 50/60Hz notch | Remove mains interference |
| `sys filter_5060_off` | Disable 50/60Hz notch | No mains filtering |
| `sys filter_100120_on` | Enable 100/120Hz notch | Remove mains harmonics |
| `sys filter_100120_off` | Disable 100/120Hz notch | No harmonic filtering |
| **Filter Settings** | | |
| `sys networkfreq [50\|60]` | Set mains frequency | `sys networkfreq 60` (US/Americas) |
| `sys dccutofffreq [0.5\|1\|2\|4\|8]` | DC filter cutoff (Hz) | `sys dccutofffreq 0.5` |
| `sys digitalgain [1-256]` | Set digital gain (power of 2) | `sys digitalgain 8` |
| **Advanced/Debug Commands** | | |
| `spi M\|S\|B <len> <bytes...>` | Direct SPI communication | `spi M 3 0x20 0x00 0x00` |

**Notes**: 
- `adc_reset`: Performs full ADS1299 initialization and syncs master/slave timing
- `esp_reboot`: Complete system restart including all hardware
- Filters must be enabled with both master switch (`filters_on`) AND individual filter switches
- SPI commands: M=Master ADC, S=Slave ADC, B=Both ADCs

### Reset to Setup Mode
Need to reconfigure WiFi? Power cycle 4 times - on the 4th power-on, board enters setup mode:

1. Turn ON briefly
2. Turn OFF
3. Turn ON briefly  
4. Turn OFF
5. Turn ON briefly
6. Turn OFF
7. Turn ON → Board creates `EEG-SETUP` hotspot

**Important timing details**:
- Board counts cumulative ON time (must be <5 seconds total)
- OFF time doesn't matter - take as long as you need
- Example: ON for 1s → OFF for 30s → ON for 1s → OFF for 2 minutes → ON for 1s → OFF → ON = Reset!
- The board recognizes reset reason - other resets (USB, button, watchdog) won't trigger setup mode

## 8. 📈 Specifications

### Hardware
- **Microcontroller**: ESP32-C3 (RISC-V, 160MHz, WiFi 2.4GHz)
- **ADC**: 2× Texas Instruments ADS1299 (24-bit, 8 channels each)
- **ADC Configuration**: Daisy-chain mode - slave ADC data output connects to master ADC data input, ESP32 only reads from master
- **Clock Synchronization**: Slave ADC uses master's clock output and reference for perfect sync
- **Channels**: 16 differential inputs
- **Sampling Rates**: 250, 500, 1000, 2000, 4000 Hz
- **Resolution**: 24-bit (0.536 μV/bit at gain=1)
- **Input Range**: ±4.5V (before digital gain)
- **Digital Gain**: 1, 2, 4, 8, 16, 32, 64, 128, 256 (reduces max input before saturation)

### Performance
- **Power Consumption**: ~400mW (typical during streaming)
- **Battery Life**: 10+ hours with 1100mAh LiPo
- **WiFi Range**: 30m typical indoor
- **Network Latency**: <10ms typical

## 9. 🛠️ Troubleshooting

### Board Not Detected
1. Check USB cable (must support data, not charge-only)
2. Try different USB port
3. Check Device Manager (Windows) or `ls /dev/tty*` (Linux/Mac)
4. ESP32-C3 has built-in USB - no drivers needed!

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

---

*Built with ❤️ for the BCI community*
