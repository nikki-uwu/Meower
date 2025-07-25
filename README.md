# ESP32-C3 16-Channel WiFi EEG/BCI Board
![Ship with markings](images/2025_07_18_board.JPG)
*(for anyone who would think i removed markings - no :3, that's just the angle, laziness, low light and iphone 12 :3)*
## 🧠 Project Overview

A 16-channel biosignal acquisition board built with ESP32-C3 and dual ADS1299 chips. This wireless brain-computer interface captures EEG, ECG, EMG, and other biosignals. Designed for BCI enthusiasts and researchers who want an easy-to-use board that streams real-time data over WiFi (maximum supported ADC sample rate for 16 channels is 4000 Hz) - just power on, connect, and start recording.

**Note**: The board is currently preconfigured for VRChat BCI use. If you have questions (oh silly woofer, why are you here, what are you doing, run :3), just ask - I'll help set up everything. It won't take more than 30 minutes max and you'll get everything you need. Easy configuration switches coming later... maybe, who knows, not me for sure :3

## ⚠️ Safety Information

**WARNING**: This device is for education and research only. Not a medical device. Do not use for diagnosis or treatment. **Use battery power only**

### Performance & Noise Considerations
Even from a pure performance standpoint, battery operation is important - not just for safety. Any USB connection introduces significant noise into the measurements. USB ground loops, switching power supplies, and computer interference can severely degrade signal quality. The cable itself can act as an antenna picking up 50/60 Hz noise if it's long enough. Always disconnect USB after configuration for quality recordings.

## 📚 What's in This Guide

| Section | Subsections | Description |
|---------|-------------|-------------|
| **1. ⚡ Quick Start** | 1.1 What You'll Need<br>1.2 Configure WiFi Settings<br>1.3 LED Status Patterns | Get data flowing in under 10 minutes |
| **2. 🔧 Building From Source** | 2.1 Prerequisites<br>2.2 Build Steps<br>2.3 Troubleshooting Upload Issues | Compile and upload custom firmware |
| **3. 📊 Data Format** | 3.1 Channel Numbering<br>3.2 UDP Packet Structure<br>3.3 Frame Packing - Why Bundle Multiple Samples?<br>3.4 Single Datagram Design - Why Limit to 28 Frames?<br>3.5 Basic Data Parsing<br>3.6 Data Conversion Reference | Channel mapping and packet structure |
| **4. 🎛️ Configuration** | 4.1 Network Ports & Communication<br>4.2 Discovery & Connection Flow<br>4.3 Command Reference<br>4.4 Reset to Setup Mode | Commands and settings |
| **5. 🎬 DSP Filter Details** | 5.1 Filter Chain Architecture<br>5.2 Frequency Response Equalizer<br>5.3 DC Removal Filter<br>5.4 Mains Interference Notch Filters<br>5.5 Filter Coefficient Generation<br>5.6 Important IIR Filter Behavior | Digital signal processing implementation |
| **6. 🔬 Raw SPI Access** | 6.1 Command Format<br>6.2 Register Reading in Daisy-Chain Mode<br>6.3 Common Examples<br>6.4 Daisy-Chain Register Reading<br>6.5 Important Notes | Direct ADC communication |
| **7. 📈 Specifications** | 7.1 Hardware<br>7.2 Performance | Technical details and performance |
| **8. 🛠️ Troubleshooting** | 8.1 Board Not Detected<br>8.2 Can't Connect to WiFi<br>8.3 No Data Received<br>8.4 Noisy or Bad Signals | Common issues and solutions |

## 1. ⚡ Quick Start

### 1.1 What You'll Need
- Meower board (this board)
- USB-C cable (data capable, not charge-only)
- 3.7V LiPo battery (optional, 1100mAh gives 10+ hours)
- Computer with WiFi (Windows/Mac/Linux)
- 2.4GHz WiFi network (or use serial configuration)
- No drivers needed - ESP32-C3 has built-in USB!

### 1.2 Configure WiFi Settings (Choose One Method)

#### Method 1: WiFi Access Point
1. **Power on** the board
2. **Connect to WiFi hotspot**: `EEG-SETUP` (password: `password`)
3. **Open browser**: Navigate to `http://192.168.4.1`
4. **Enter your settings**:
   - WiFi network name (SSID)
   - WiFi password
   - Control port (default: 5000)
   - Data port (default: 5001)
5. **Click "Save and Restart"**

The board will automatically discover your PC through UDP broadcast messages - no IP configuration needed.

#### Method 2: Serial Configuration
1. **Connect via USB** and open serial terminal (115200 baud)
2. **Type commands**:
   ```
   set ssid YourWiFiName
   set pass YourWiFiPassword  
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

### 1.3 LED Status Patterns
After configuration, the LED shows board status:
- **Rapid flashing**: Network setup mode (Access Point active)
- **3 blinks**: Cannot connect to WiFi
- **2 blinks**: Connected to WiFi (not streaming)
- **1 blink every 5 seconds**: Streaming data
- **5 blinks**: Connection lost (failsafe triggered)

## 2. 🔧 Building From Source

### 2.1 Prerequisites
| Software | Version | Download |
|----------|---------|----------|
| Git | Latest | [git-scm.com](https://git-scm.com) |
| VS Code | Latest | [code.visualstudio.com](https://code.visualstudio.com) |
| PlatformIO | Extension | Install within VS Code |

### 2.2 Build Steps
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

### 2.3 Troubleshooting Upload Issues
- **Other USB devices can interfere**: Disconnect USB audio interfaces, cameras, USB hubs, etc.
- **Ensure no other programs are using the COM port**: Close any serial terminals, Arduino IDE, etc.
- **Windows "Restart apps" setting**: Go to Settings → Accounts → Sign-in options → Turn OFF "Use my sign-in info to automatically finish setting up after an update or restart" - this can keep apps running in background
- **Full restart recommended**: Restart PC and don't open any apps before uploading
- **No BOOT button needed**: Just connect USB and power on
- **CH340 drivers**: ESP32-C3 has built-in USB - no drivers needed! (Unlike older ESP32)
- If still having issues, try a different USB cable or port

## 3. 📊 Data Format & Channel Mapping

### 3.1 Channel Numbering

[Channel mapping diagram - to be added]

**Channel Assignment:**
- Channels 0-7: Master ADS1299 (U1)
- Channels 8-15: Slave ADS1299 (U2)

### 3.2 UDP Packet Structure

The board always sends data in a single UDP datagram (no fragmentation). You can safely read with a 1500-byte buffer.

```
┌─────────────────────────────────────────────────────────────────┐
│                    UDP Packet (max 1472 bytes)                  │
├─────────────────────────────────────────────────────────────────┤
│ Frame 1 │ Frame 2 │ Frame 3 │ ... │ Frame N │ Battery Voltage   │
│ 52 bytes│ 52 bytes│ 52 bytes│     │(max 28) │ 4 bytes (float32) │
└─────────────────────────────────────────────────────────────────┘
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
    ┌─────────────────────────────────────────────────────────────┐
    │                     ADC Data (48 bytes)                     │
    ├─────────────────────────────────────────────────────────────┤
    │ Ch0   │ Ch1   │ Ch2   │ Ch3   │ Ch4   │ ... │ Ch14  │ Ch15  │
    │3 bytes│3 bytes│3 bytes│3 bytes│3 bytes│     │3 bytes│3 bytes│
    │ 24bit │ 24bit │ 24bit │ 24bit │ 24bit │     │ 24bit │ 24bit │
    └─────────────────────────────────────────────────────────────┘
```

### 3.3 Frame Packing - Why Bundle Multiple Samples?

The board bundles multiple ADC data frames into each UDP packet for several practical reasons:

1. **Reduces load on network and CPU** - Nobody needs to handle 4000 packets per second. Your computer doesn't need to parse that fast, the network doesn't need that traffic.

2. **ESP32 packet rate limitation** - Testing shows the ESP32 can handle up to ~166 UDP packets per second with this firmware. Beyond that, packets drop.

3. **Saves battery** - Fewer radio transmissions = longer battery life

4. **Stable network behavior** - Consistent 50 packets/second is much easier to handle than thousands

5. **Enables high sampling rates** - 4000 Hz sampling would be impossible without packing (would need 4000 packets/sec!)

**How the board packs frames:**

The board tries to maintain 50 packets per second when possible:

| Sampling Rate | Frames Packed | WiFi Packets/Second |
|--------------|---------------|---------------------|
| 250 Hz | 5 frames | 50 packets/sec |
| 500 Hz | 10 frames | 50 packets/sec |
| 1000 Hz | 20 frames | 50 packets/sec |
| 2000 Hz | 28 frames* | 71 packets/sec |
| 4000 Hz | 28 frames* | 143 packets/sec |

*At 2 kHz and above, the board packs the maximum 28 frames to stay within the single datagram limit

### 3.4 Single Datagram Design - Why Limit to 28 Frames?

We intentionally limit frame packing to keep all data within a single UDP datagram (max 1472 bytes). Here's why:

**1. Network Efficiency** - Every UDP packet has overhead regardless of payload size. Sending 10 bytes costs almost the same network resources as sending 1000 bytes. By packing frames up to the datagram limit, we use network bandwidth efficiently.

**2. Simple Implementation** - Both sides benefit:
   - ESP32: Just one `send()` call with the complete packet
   - PC: Just one `recv()` call to get all the data
   - No complex code to split/reassemble packets

**3. MTU Compliance** - Network routers have a size limit (MTU = 1500 bytes). Staying under this means:
   - No fragmentation (splitting by routers)
   - No reassembly needed
   - Lower chance of packet loss

**Technical Calculation**:
- Maximum usable UDP payload: 1472 bytes (1500 - 28 bytes of headers)
- Each frame: 52 bytes
- Battery voltage: 4 bytes
- Maximum frames: (1472 - 4) / 52 = 28 frames

**Advanced Configuration**: The board automatically adapts frame packing based on sampling rate. The 50 packets/second target is a sweet spot - fast enough for real-time display, slow enough for stable operation. Other parameters can be changed in `defines.h` (ports, timing, etc.) but think 10 times before changing anything! The board starts at 250 Hz with 5-frame packing (50 packets/sec) by default.

### 3.5 Basic Data Parsing

The 48-byte ADC data contains 16 channels, each using 3 bytes (24 bits) in big-endian format:

```
┌─────────────────────────────────────────────────────────────────┐
│                      48 Bytes of ADC Data                       │
├─────────────────────────────────────────────────────────────────┤
│ Ch0     │ Ch1     │ Ch2     │ Ch3     │ ... │ Ch14    │ Ch15    │
│ 3 bytes │ 3 bytes │ 3 bytes │ 3 bytes │     │ 3 bytes │ 3 bytes │
└─────────────────────────────────────────────────────────────────┘
     ↓
┌─────────────────────────────────────────────────────────────────┐
│               One Channel = 3 Bytes (Big-Endian)                │
├─────────────────────────────────────────────────────────────────┤
│       Byte 0        │       Byte 1        │       Byte 2        │
│      MSB (b0)       │     Middle (b1)     │      LSB (b2)       │
│  [7 6 5 4 3 2 1 0]     [7 6 5 4 3 2 1 0]     [7 6 5 4 3 2 1 0]  │
└─────────────────────────────────────────────────────────────────┘
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
    # Combine 3 bytes into 24-bit value
    value = (b0 << 16) | (b1 << 8) | b2
    
    # Sign extend from 24-bit to 32-bit
    if value >= 0x800000:  # If negative (bit 23 set)
        value -= 0x1000000  # Subtract 2^24
    
    return float(value)
```
```c
// C code - sign extension happens automatically with proper types
int32_t parse_24bit_sample(uint8_t b0, uint8_t b1, uint8_t b2)
{
    // Step 1: Combine bytes into 24-bit value in 32-bit container
    int32_t value = (b0 << 16) | (b1 << 8) | b2;
    
    // Step 2: Sign extend from 24-bit to 32-bit using shift method
    value = (value << 8) >> 8;  // Arithmetic shift does sign extension
    
    return value;
}
```

For complete UDP datagram parsing including frame validation and battery extraction, see the `python/` folder which contains full working examples.

### 3.6 Data Conversion Reference

The ADS1299 outputs 24-bit signed values. To convert to physical units:

```
Raw ADC value → Voltage conversion:
- LSB size = 4.5V / (2^23) = 0.536 microvolts per count
- Voltage = raw_value * 0.536 µV / hardware_gain (at digital gain=1)
```

**Hardware Gain vs Digital Gain**:
- **Hardware PGA Gain** (set via `usr gain`): Applied in the ADC's analog front-end before digitization. Amplifies the voltage signal. **Warning**: Increasing PGA gain reduces the input range and can saturate the ADC.
- **Digital Gain** (set via `sys digitalgain`): Applied after ADC conversion by bit-shifting. Used to occupy the full 32-bit scale during DSP processing for better precision, especially important for IIR filters at extreme settings (e.g., 0.5 Hz cutoff at 4000 Hz sampling).

**Important DC Offset Consideration**:
Check for DC voltage between your positive and negative input pins before setting gain. A small AC signal sitting on a large DC offset (e.g., 10 mV signal on 1V DC) will saturate the ADC when amplified. Use a multimeter to verify DC levels are near zero.

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
- PGA gain is a voltage amplification factor (e.g., gain=24 means 24x voltage amplification)

## 4. 🎛️ Configuration & Control

### 4.1 Network Ports & Communication
- **Control Port**: 5000 (UDP) - Commands and configuration (default, configurable)
- **Data Port**: 5001 (UDP) - EEG data stream (default, configurable)
- **Keep-Alive**: PC sends "WOOF_WOOF" every <10 seconds to maintain connection
- **Connection Timeout**: Board stops streaming after ~10 seconds without any packets

### 4.2 Discovery & Connection Flow

1. **Board powers on** → Connects to configured WiFi network
2. **Board broadcasts "MEOW_MEOW"** to 255.255.255.255 on control port every second
3. **PC software listens** on control port and responds with "WOOF_WOOF" to board's IP
4. **Board captures PC's IP** from the WOOF_WOOF packet source (first time only)
5. **Ready to stream** → Send `sys start_cnt` to begin
6. **Maintain connection** → PC sends "WOOF_WOOF" every <10 seconds or board returns to broadcasting

### 4.3 Command Reference
Send these commands to the control port as UTF-8 strings:

**Important Command Behavior**:
- **SYS commands**: Can be executed during continuous mode (real-time changes). Filters, digital gain, and network settings update immediately without interrupting data flow.
- **SPI and USR commands**: Automatically stop continuous mode before executing to ensure data integrity. The board uses different SPI clocks: 16 MHz during streaming for high-speed data transfer, and 2 MHz for configuration to guarantee stable register operations (higher speeds can cause unreliable register access).
- **Continuous mode** resumes only with `sys start_cnt` command.

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
| **User Commands** | | |
| `usr set_sampling_freq [250\|500\|1000\|2000\|4000]` | Set ADC sampling rate (Hz) | `usr set_sampling_freq 1000` |
| `usr gain [channel\|ALL] [1\|2\|4\|6\|8\|12\|24]` | Set hardware PGA gain | `usr gain 5 24` or `usr gain ALL 4` |
| `usr ch_power_down [channel\|ALL] [ON\|OFF]` | Channel power control | `usr ch_power_down 5 OFF` or `usr ch_power_down ALL ON` |
| `usr ch_input [channel\|ALL] [input_type]` | Select channel input source | `usr ch_input 5 SHORTED` or `usr ch_input ALL TEST` |
| `usr ch_srb2 [channel\|ALL] [ON\|OFF]` | SRB2 connection control | `usr ch_srb2 5 ON` or `usr ch_srb2 ALL OFF` |
| **Advanced/Debug Commands** | | |
| `spi M\|S\|B <len> <bytes...>` | Direct SPI communication | `spi M 3 0x20 0x00 0x00` |

**Notes**: 
- `adc_reset`: Performs full ADS1299 initialization and syncs master/slave timing
- `esp_reboot`: Complete system restart including all hardware
- Filters must be enabled with both master switch (`filters_on`) AND individual filter switches
- SPI commands: M=Master ADC, S=Slave ADC, B=Both ADCs
- Board automatically adjusts frame packing when sampling rate changes
- `ch_power_down OFF`: Places channel in high-impedance state. For best noise reduction, also short unused channels
- `ch_input` types:
  - `NORMAL`: Normal electrode input
  - `SHORTED`: Inputs shorted together (for offset/noise measurements)
  - `BIAS_MEAS`: Measure bias signal
  - `MVDD`: Measure supply voltage
  - `TEMP`: Temperature sensor
  - `TEST`: Internal test signal
  - `BIAS_DRP`: Positive electrode is the driver
  - `BIAS_DRN`: Negative electrode is the driver
- `ch_srb2 ON`: Connects channel to SRB2 (reference), OFF disconnects

### 4.4 Reset to Setup Mode
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

## 5. 🎬 DSP Filter Implementation Details

The board processes incoming signals through a digital filter chain consisting of one FIR filter and three IIR filters, all running at 160MHz with fixed-point math for consistent performance:

### 5.1 Filter Chain Architecture
1. **FIR Equalizer (7-tap)** → 2. **DC Blocker (IIR)** → 3. **Notch Filters (IIR)**

### 5.2 Frequency Response Equalizer
- **Purpose**: Compensates for the ADS1299's inherent frequency rolloff from its sinc³ decimation filter
- **Type**: 7-tap FIR filter maintaining flat response (≈0 dB) from DC to 0.8×Nyquist
- **Example**: At 250 Hz sampling, provides flat response from 0-100 Hz
- **Why needed**: Without this, higher EEG frequencies (gamma band) appear artificially attenuated

### 5.3 DC Removal Filter  
- **Type**: 2nd order Butterworth high-pass (IIR, no Q factor)
- **Cutoff options**: 0.5, 1, 2, 4, 8 Hz (selectable via `sys dccutofffreq`)
- **Behavior**: 
  - Removes electrode drift and DC offsets
  - Preserves fast transients (blinks, eye movements) as sharp spikes instead of long DC steps
  - Coefficients recalculated on-the-fly for any sampling rate

### 5.4 Mains Interference Notch Filters
- **Configuration**: Two cascaded biquads per frequency (4th order total)
- **Q Factor**: ~35 (very narrow notch)
- **Attenuation**: -40 dB at target frequencies
- **Options**: 
  - 50 Hz + 100 Hz (Europe/Asia)
  - 60 Hz + 120 Hz (Americas)
- **Purpose**: Real-time recording cleanup; heavier processing can be done offline

### 5.5 Filter Coefficient Generation
All filter coefficients are pre-calculated by a Python script that:
- Generates coefficients for each sampling rate (250-4000 Hz)
- Scales to 32-bit fixed-point for integer math
- Ensures unity gain at passband to prevent clipping
- The generation script is included as comments in math_lib.h

### 5.6 Important IIR Filter Behavior
**Spike Recovery**: IIR filters can ring when hit with large transients (like electrode pops or movement artifacts). If you see:
- Phantom 50/60 Hz oscillations after a spike
- Slowly drifting baseline after movement

**Quick fix**: Toggle the filter off and back on (`sys filters_off` → `sys filters_on`). This takes <1ms and completely resets the filter states, stopping any ringing immediately.

## 6. 🔬 Raw SPI Access

Direct SPI access allows low-level communication with the ADS1299 chips via WiFi UDP commands. Useful for custom configurations or debugging.

### 6.1 Command Format
```
spi [target] [length] [byte0] [byte1] ... [byteN]
```

**Parameters:**
- `target`: Which ADC to communicate with
  - `M` or `MASTER` - Master ADS1299 only
  - `S` or `SLAVE` - Slave ADS1299 only  
  - `B` or `BOTH` - Both ADCs simultaneously
- `length`: Number of bytes to send (1-256)
- `bytes`: Hex values to send (e.g., 0x20, 0x00)

**Response**: Board returns the same number of bytes received from SPI

### 6.2 Register Reading in Daisy-Chain Mode

The dual ADS1299 chips are configured in daisy-chain mode with separate chip selects. This means:
- **Writing registers**: Works normally - you can write to Master, Slave, or Both independently
- **Reading registers**: Requires special handling due to daisy-chain data flow

The simplified 'spi' command returns only data from the Master ADC. However, the firmware includes a fully implemented `read_Register_Daisy()` function that reads from both ADCs simultaneously:
1. Selects both chips (target 'B')
2. Sends a 30-byte transaction
3. Extracts Master value from byte 3
4. Extracts Slave value from byte 30

If you're implementing your own register reads via raw SPI commands, treat it like ADC sample reading in daisy-chain mode where data flows through: Slave → Master → ESP32. See the detailed protocol description below.

### 6.3 Common Examples

**Read Device ID from Master (should return 0x3E for ADS1299):**
```
spi M 3 0x20 0x00 0x00
```
- 0x20 = Read register 0x00 (device ID)
- Response: [garbage, garbage, 0x3E] - third byte contains the ID

**Read Configuration Register 1:**
```
spi M 3 0x21 0x00 0x00
```
- 0x21 = Read register 0x01
- Response shows current sampling rate and daisy chain config

**Write to Configuration Register 3 (enable internal reference):**
```
spi B 3 0x43 0x00 0xE0
```
- 0x43 = Write to register 0x03
- 0xE0 = Enable internal reference buffer
- Works for both ADCs simultaneously

**Read All Channel Settings (Master only):**
```
spi M 3 0x45 0x07 0x00
```
- 0x45 = Read starting at register 0x05 (CH1SET)
- 0x07 = Read 8 registers (all channels)

**Read Specific Channel Setting (e.g., Channel 5 on Master):**
```
spi M 3 0x2A 0x00 0x00
```
- 0x2A = Read register 0x0A (CH6SET - channel 5 is the 6th channel, 0-indexed)

**Check Channel Power/Gain/Input Status:**
```
spi M 3 0x25 0x00 0x00
```
- 0x25 = Read CH1SET (channel 0)
- Response byte 3: 
  - Bit 7 = power state (0=on, 1=off)
  - Bits 6-4 = gain setting
  - Bit 3 = SRB2 connection
  - Bits 2-0 = input selection

### 6.4 Daisy-Chain Register Reading

Due to the daisy-chain configuration, reading registers requires special handling:

**How Daisy-Chain Register Reads Work:**

```
┌─────────────────────────────────────────────────────────────────┐
│                  Daisy-Chain Data Flow                          │
├─────────────────────────────────────────────────────────────────┤
│   Slave ADC  ──data──>  Master ADC  ──data──>  ESP32            │
│                                                                 │
│  Both chips must be selected (CS=LOW) simultaneously            │
└─────────────────────────────────────────────────────────────────┘
```

When reading a register in daisy-chain mode:
1. **Both ADCs must be chip-selected** - Using target 'B' is mandatory
2. **Both ADCs receive the command** and prepare their responses
3. **Data flows sequentially**: Slave response arrives first (27 bytes), then Master (27 bytes)
4. **Register values are at specific positions**:
   - Master's value: Byte 3 of the response
   - Slave's value: Byte 30 of the response

**30-Byte Register Read Transaction:**

```
What we send (30 bytes):
┌────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┐
│ 0  │ 1  │ 2  │ 3  │ 4  │ 5  │ 6  │ 7  │ 8  │ 9  │ 10 │ 11 │ 12 │ 13 │ 14 │ 15 │ 16 │ 17 │ 18 │ 19 │ 20 │ 21 │ 22 │ 23 │ 24 │ 25 │ 26 │ 27 │ 28 │ 29 │
├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
│RREG│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│0x00│
└────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┘
 0x2X                                     (X = register address, e.g., 0x21 for CONFIG1)

What we receive (30 bytes):
┌────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┐
│ 0  │ 1  │ 2  │ 3  │ 4  │ 5  │ 6  │ 7  │ 8  │ 9  │ 10 │ 11 │ 12 │ 13 │ 14 │ 15 │ 16 │ 17 │ 18 │ 19 │ 20 │ 21 │ 22 │ 23 │ 24 │ 25 │ 26 │ 27 │ 28 │ 29 │
├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
│ ?? │ ?? │DATA│ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ 0  │ ?? │ ?? │DATA│
└────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┘
         Master                                                                                                                           Slave
      register value                                                                                                                  register value

What we store:
┌─────────────────┬─────────────────┐
│ Master Value    │ Slave Value     │
├─────────────────┼─────────────────┤
│ rx[2]           │ rx[29]          │
└─────────────────┴─────────────────┘
```

**Example: Reading CONFIG1 register from both ADCs**
```
Command: spi B 30 0x21 0x00 [28 zeros]
Response: 30 bytes where:
  - Byte 3 = Master's CONFIG1 value
  - Byte 30 = Slave's CONFIG1 value
```

**Important**: Currently, the simplified SPI interface only returns Master values. To read both ADCs, the firmware uses an internal `readRegisterDaisy()` function that properly handles the 30-byte transaction.

### 6.5 Important Notes
- Board automatically handles CS (chip select) for the specified target
- All transactions use 2 MHz SPI clock for reliability
- Always send SDATAC (0x11) before configuration changes
- Send RDATAC (0x10) to resume continuous data mode
- Refer to ADS1299 datasheet for complete register map

## 7. 📈 Specifications

### 7.1 Hardware
- **Microcontroller**: ESP32-C3 (RISC-V, 160MHz, WiFi 2.4GHz)
- **ADC**: 2× Texas Instruments ADS1299 (24-bit, 8 channels each)
- **ADC Configuration**: Daisy-chain mode - slave ADC data output connects to master ADC data input, ESP32 only reads from master
- **Clock Synchronization**: Slave ADC uses master's clock output and reference for perfect sync
- **Channels**: 16 differential inputs
- **Sampling Rates**: 250, 500, 1000, 2000, 4000 Hz
- **Resolution**: 24-bit (0.536 μV/bit at gain=1)
- **Input Range**: ±4.5V (at PGA gain=1, reduces with higher gain)
- **Hardware PGA Gain**: 1, 2, 4, 6, 8, 12, 24 (voltage amplification factor)
- **Digital Gain**: 1, 2, 4, 8, 16, 32, 64, 128, 256 (bit shifting for DSP precision)

### 7.2 Performance
- **Power Consumption**: ~400mW @ 250Hz, ~470mW @ 4kHz
- **Battery Life** (1100mAh LiPo):
  - 10+ hours at 250 Hz (~400mW)
  - 8+ hours at 4000 Hz (~470mW)
- **Battery Monitoring**: Voltage sampled every 32ms with IIR filtering (α=0.05) for stable readings
- **WiFi Range**: 30m typical indoor
- **Gain Recommendations**:
  - EEG (10-100µV): Hardware gain 12-24x
  - ECG (0.5-4mV): Hardware gain 2-8x
  - EMG (50µV-30mV): Hardware gain 1-4x
  - Always check for DC offset between pins before amplifying

## 8. 🛠️ Troubleshooting

### 8.1 Board Not Detected
1. Check USB cable (must support data, not charge-only)
2. Try different USB port
3. Check Device Manager (Windows) or `ls /dev/tty*` (Linux/Mac)
4. ESP32-C3 has built-in USB - no drivers needed!

### 8.2 Can't Connect to WiFi
1. Ensure 2.4GHz network (5GHz not supported)
2. Check password (case sensitive)
3. Verify router allows new devices
4. Try WPA2 (WPA3 may cause issues)
5. Check serial output for error messages

### 8.3 No Data Received
1. Verify PC firewall allows UDP ports 5000 and 5001
2. Ensure your software responds to MEOW_MEOW with WOOF_WOOF
3. Send `sys start_cnt` command to begin streaming
4. Confirm LED shows streaming pattern (1 blink/5s)
5. Try simple UDP listener to test connectivity

### 8.4 Noisy or Bad Signals
1. Check electrode connections (should be snug)
2. Verify skin preparation (clean with alcohol)
3. Measure impedance (<5kΩ recommended)
4. Enable filters: `sys filters_on`
5. Check ground and reference electrode placement
6. Move away from AC power sources
7. Ensure battery powered during use
8. **Gain issues**:
   - Signal clipping? Reduce hardware gain
   - Signal too small? Increase hardware gain first, then digital gain
   - Check DC offset between pins with multimeter before setting gain
9. **Unused channels**: Power down AND short unused channels to reduce noise
   - `usr ch_power_down 15 OFF` to power down
   - `usr ch_input 15 SHORTED` to short inputs
10. **Reference setup**: Use SRB2 for common reference
    - `usr ch_srb2 ALL ON` for referenced mode
    - `usr ch_srb2 ALL OFF` for differential mode
    - 
## Contributions

Any contributions submitted for inclusion in this repository will be licensed as follows:

**For firmware and software contributions:**
Dual-licensed under either:
* MIT License ([LICENSE-MIT](LICENSE-MIT))
* Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE))

**For hardware contributions (schematics, PCB layouts, etc.):**
* CERN Open Hardware Licence Version 2 - Strongly Reciprocal ([LICENSE-HARDWARE](LICENSE-HARDWARE))

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion in the work by you, as defined in the Apache-2.0 license, shall be dual licensed (or licensed under CERN-OHL-S-2.0 for hardware) as above, without any additional terms or conditions.

You also certify that the code you have used is compatible with those licenses or is authored by you. If you're doing so on your work time, you certify that your employer is okay with this and that you are authorized to provide the above licenses.

For more details on contributing, see [CONTRIBUTING.md](CONTRIBUTING.md).

---
### Previous Versions :3
![Ship with markings](images/Previous_versions.jpg)
