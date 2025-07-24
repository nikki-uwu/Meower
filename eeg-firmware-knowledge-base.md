# ESP32-C3 EEG Firmware Complete Knowledge Base

This document consolidates ALL technical knowledge, implementation details, and important notes scattered throughout the firmware codebase. Created to prevent getting lost in the massive codebase.

---

## 🔴 Critical Safety & Performance Rules

1. **ALWAYS use battery power during recording** - USB introduces catastrophic noise that destroys µV-level signals
2. **Never exceed 2 MHz SPI during initial configuration** - ADS1299 refuses faster clocks after reset
3. **Keep ADC sense pin on ADC1 only** - ADC2 conflicts with WiFi and will cause crashes
4. **Quad-tap power for recovery** - If board acts dead, 4 power cycles < 5s cumulative triggers captive portal
5. **Send "WOOF_WOOF" every ≤10 seconds** - Board drops to IDLE after 10s without keep-alive

---

## 1. Hardware Architecture & Pin Mapping

### ESP32-C3 Pin Assignments
```
SCLK        : GPIO 10  (Hardware SPI)
MOSI        : GPIO 6   (Hardware SPI)
MISO        : GPIO 2   (Hardware SPI + pulldown to prevent tri-state decay)
DRDY        : GPIO 3   (Interrupt pin, FALLING edge)
START       : GPIO 0   (Controls ADC sampling)
PWDN        : GPIO 8   (Power down control)
RESET       : GPIO 7   (Hardware reset)
CS_MASTER   : GPIO 1   (Master ADS1299)
CS_SLAVE    : GPIO 5   (Slave ADS1299)
CS_UNUSED   : GPIO 21  (Default SPI CS - kept HIGH)
LED         : GPIO 20  (Status indicator, active LOW)
BAT_SENSE   : GPIO 4   (ADC1_CH4 - CRITICAL: Must be ADC1!)
```

### Daisy-Chain Configuration
- **Data flow**: Slave ADC output → Master ADC input → ESP32
- **Clock**: Master provides clock to Slave via dedicated line
- **Sync**: Both ADCs share START signal for perfect alignment
- **Frame structure**: 27 bytes per ADC (3 preamble + 24 channel data)

### Electrical Design Notes
- **Battery voltage divider**: Calibrated scale factor = 0.01235 (current implementation)
- **Pull-down on MISO**: Prevents signal decay when last bit = 1
- **CS timing**: Uses direct register writes (40ns edges) vs digitalWrite (1.2µs)
- **Power**: ~400mW typical, 470mW max @ 4kHz
- **PGA Gain**: Voltage amplification in analog domain before ADC conversion
- **DC Offset Warning**: Check DC voltage between input pins before setting gain - small signals on DC offsets will saturate when amplified

---

## 2. Boot Sequence & Recovery Mechanisms

### BootCheck System (Anti-Brick Protection)
```
Window: 5 seconds cumulative ON time
Detection: 3 reboots with flag="a" (armed) within window
Action: Set BootMode="AccessPoint" → force captive portal
Reset: After 1 second, flag changes "a"→"b" (disarmed)
```

### Captive Portal Emergency Mode
- **SSID**: `EEG-SETUP`
- **Password**: `password`  
- **IP**: `192.168.4.1`
- **Saves to NVS**: ssid, pass, port_ctrl, port_data
- **Auto-triggers**: On missing config or boot storm

### ADS1299 Initialization Sequence
1. Set continuous mode OFF
2. Force SPI to 2 MHz (CRITICAL for stability)
3. All digital signals LOW (CS, START)
4. PWDN/RESET cycle with 150ms delays
5. Send RESET pulse (10µs LOW)
6. SDATAC command (exit continuous mode)
7. Enable internal reference (CONFIG3 = 0xE0)
8. Configure master clock output to slave
9. Wait 50ms for slave clock lock
10. Enable test signal (1Hz square wave)
11. Board initializes at 250 Hz with 5-frame packing (50 packets/sec)
12. SPI remains at 2 MHz until `sys start_cnt` switches to 16 MHz
13. **Default channel settings**:
    - Normal mode: Test signal input, gain = 1x (register value 0x05)
    - BCI mode: Normal electrode input with SRB2, gain = 1x (register value 0x08)

### Readiness Check
```c
// Loop until ADS1299 responds with correct ID
while (true) {
    xfer('M', 3, {0x20, 0x00, 0x00}, rx);  // Read register 0x00
    if (rx[2] == 0x3E) break;               // Expected device ID
    delay(10);
}
```

---

## 3. Network Architecture & Lifecycle

### State Machine
```
DISCONNECTED → (WiFi connect) → IDLE → (start_cnt) → STREAMING
     ↑              ↑                        ↓
     └──────────────┴──── (timeout/stop) ───┘
```

### Discovery & Keep-Alive Protocol
- **Beacon**: "MEOW_MEOW" (9 bytes) every 1 second when no peer found
- **Discovery/Keep-alive**: "WOOF_WOOF" (9 bytes) serves dual purpose
- **Watchdog refresh**: Any valid packet refreshes watchdog (WOOF_WOOF, commands) except MEOW_MEOW echoes

### Timeout Hierarchy
1. **10s streaming watchdog**: No data → drop STREAMING to IDLE
2. **10s global silence**: No packets at all → restart beacons
3. **60s reconnect limit**: WiFi keeps failing → radio OFF, LED=LOST

### LED Status Codes (250ms on, 5s cycle)
- **Rapid flash**: Network setup mode (AP active)
- **3 blinks**: Cannot connect to WiFi (DISCONNECTED)
- **2 blinks**: Connected but IDLE
- **1 blink**: STREAMING data
- **5 blinks**: Connection LOST (failsafe triggered)

### AsyncUDP Implementation
- **TX**: Traditional WiFiUDP for sending
- **RX**: Event-driven AsyncUDP (zero polling overhead)
- **Queue**: 8-slot command queue, 512 bytes each
- **Beacon filter**: Ignores own MEOW_MEOW beacons

---

## 4. Data Path Architecture

### Frame Structure (52 bytes)
```
[48 bytes ADC data][4 bytes timestamp]
    ↓                    ↓
16 ch × 3 bytes      Little-endian
Big-endian 24-bit    8µs timer units
```

### Packet Structure (max 1472 bytes)
```
[Frame 1][Frame 2]...[Frame N][Battery Voltage]
52 bytes  52 bytes    max 28   4 bytes float32 LE
```

### Task Architecture
1. **DRDY ISR** (IRAM): ~5µs to notify ADC task
2. **ADC/DSP Task** (Priority MAX-1, Core 0):
   - Triggered by task notification (not semaphore - 45% faster)
   - Reads 54 bytes via SPI DMA
   - Strips preambles (saves 6 bytes)
   - Unpacks 24→32 bit with +8 bit headroom
   - Runs DSP pipeline (FIR + IIRs)
   - Packs back to 24-bit
   - Queues complete packet

3. **UDP Task** (Priority MAX-2, Core 0):
   - Blocks on 5-slot queue
   - Appends battery voltage
   - Sends via WiFi

### Queue Design
- **5 slots** = 280ms buffer @ 500Hz
- **ADC never blocks**: Skips enqueue if full
- **FIFO order** guaranteed by FreeRTOS

### Adaptive Packet Sizing

The firmware dynamically adjusts frames per packet to target 50 packets/second over WiFi:

**Hardware Constraints**:
1. **MTU Limit**: 1472 bytes usable → max 28 frames (28*52+4=1460 bytes)
2. **WiFi Timing**: ESP32 needs ~6ms between packets → max ~166 packets/sec
   - This is a hardware/driver limitation of the ESP32 WiFi stack
   - Pushing faster causes packet drops and instability

**Implementation**:
- Lookup table in `FRAMES_PER_PACKET_LUT[5]` maps sampling rate to frame count
- Updated when sampling rate changes in `continuous_mode_start_stop()`
- Variables updated:
  - `g_framesPerPacket`: How many frames to pack
  - `g_bytesPerPacket`: ADC data size threshold  
  - `g_udpPacketBytes`: Total UDP payload size (includes battery)

**Packing Strategy**:
| Rate | Frames | Result |
|------|--------|--------|
| 250 Hz | 5 | 50 packets/sec |
| 500 Hz | 10 | 50 packets/sec |
| 1000 Hz | 20 | 50 packets/sec |
| 2000 Hz | 28 | 71 packets/sec (MTU limit) |
| 4000 Hz | 28 | 143 packets/sec (MTU limit) |

**Why This Matters**:
- 250 Hz unpacked = 250 pkt/s → WiFi overload
- 250 Hz with 5-frame packing = 50 pkt/s → smooth operation
- 4000 Hz would need 4000 pkt/s unpacked → impossible
- 4000 Hz with 28-frame packing = 143 pkt/s → just under limit

---

## 5. Digital Signal Processing Pipeline

### Overview
All filters run at 160MHz with fixed-point math. Global enable + individual enables.

### Filter Chain (Sequential, In-Place)
```
Input → [FIR Equalizer] → [DC Blocker] → [Notch 50/60] → [Notch 100/120] → Output
         ↓                 ↓              ↓                ↓
      Optional          Optional       Optional         Optional
```

### 1. FIR Equalizer (7-tap)
- **Purpose**: Compensates ADS1299 sinc³ decimation rolloff
- **Response**: Flat ±0dB from DC to 0.8×Nyquist
- **Shift**: 30 bits output scaling
- **Bypass**: True pass-through coefficients

### 2. DC Blocker (2nd order Butterworth IIR)
- **Cutoffs**: 0.5, 1, 2, 4, 8 Hz (runtime selectable)
- **Coefficient sets**: 25 (5 sample rates × 5 cutoffs)
- **Note**: 0.5Hz cutoff @ 4kHz sampling can become unstable (resonator behavior)

### 3. Notch Filters (4th order, cascaded biquads)
- **50/60 Hz**: Q≈35, -40dB rejection
- **100/120 Hz**: Same specs for harmonics
- **Coefficient sets**: 10 each (5 rates × 2 regions)

### Filter Math Details
- **Data type**: int32_t[16] throughout
- **Rounding**: Away from zero to prevent DC bias
- **Headroom**: All stages stay within ±31 bits
- **Reset**: Toggle off→on clears IIR states in <1ms

### Important IIR Filter Behavior
**Problem**: Large spikes can cause ringing (phantom oscillations)
**Solution**: `sys filters_off` → `sys filters_on` instantly resets states

---

## 6. SPI Communication Layer

### Clock Management (CENTRALIZED)

**Critical Change**: SPI clock management is now **centralized** in `continuous_mode_start_stop()`. This is the **ONLY** function that should change SPI clock speeds.

**Clock States**:
```c
Configuration: 2 MHz (when continuousReading == false)
Streaming:     16 MHz (when continuousReading == true)
Mode:          SPI_MODE1 (CPOL=0, CPHA=1)
```

**Why Different Speeds?**:
- **2 MHz for configuration**: ADS1299 register operations become unstable above 4 MHz. Using 2 MHz guarantees reliable register reads/writes.
- **16 MHz for streaming**: Maximum stable speed for continuous data transfer, providing best throughput for real-time EEG data.

**Functions That Previously Changed Clocks** (now removed):
- `ads1299_full_reset()` - relies on continuous_mode_start_stop()
- `BCI_preset()` - relies on continuous_mode_start_stop()
- `wait_until_ads1299_is_ready()` - relies on continuous_mode_start_stop()
- `read_Register_Daisy()` - uses current clock setting
- `handle_SPI()` - uses current clock setting
- `modify_register_bits()` - uses current clock setting

**Clock Invariant**:
- When `continuousReading == false` → SPI clock is 2 MHz
- When `continuousReading == true` → SPI clock is 16 MHz
- All functions can assume the correct clock is already set

### Chip Select Control
- **Method**: Direct register writes via WRITE_PERI_REG
- **Timing**: 40ns edges (vs 1.2µs for digitalWrite)
- **Sync**: Both CS lines toggle simultaneously
- **Delays**: 2µs after CS LOW, 2µs before CS HIGH

### Critical Transfer Function
```c
void xfer(target, length, txData, rxData) {
    portENTER_CRITICAL();      // Block ALL interrupts
    cs_both_high();            // Ensure clean state
    
    switch(target) {
        'M': cs_master_low();  // Master only
        'S': cs_slave_low();   // Slave only  
        'B': cs_both_low();    // Both ADCs
        'T': break;            // Test mode (no CS)
    }
    
    esp_rom_delay_us(2);       // ≥4 SPI clocks
    transferBytes();           // DMA burst
    esp_rom_delay_us(2);       // ≥4 SPI clocks
    cs_both_high();            // Deselect
    portEXIT_CRITICAL();
}
```

### Daisy-Chain Register Reading
Reading registers from both ADCs simultaneously is implemented via `read_Register_Daisy()`:
- Uses target 'B' (both chips selected)
- Sends 30-byte transaction
- Master register value at byte 3
- Slave register value at byte 30

### Daisy-Chain Register Read Protocol

In daisy-chain mode, reading registers requires special handling because both ADCs are connected in series. The slave's data output feeds into the master's data input, and the ESP32 only reads from the master.

**Why 30 bytes?**
When reading a single register in daisy-chain mode:
- Each ADC outputs 27 bytes total (3 header bytes + 24 channel data bytes)
- For register reads, only the 3rd byte of each ADC's response contains the actual register value
- Master's register value appears at byte position 3 (0-indexed: rx[2])
- Slave's register value appears at byte position 30 (0-indexed: rx[29])
- We only need to clock out 30 bytes to retrieve both register values

**Protocol Requirements**:
1. **Must select both chips simultaneously** - Using target 'B' is mandatory. If only one chip is selected, the daisy chain breaks and data becomes corrupted
2. **Must use configuration clock** (2 MHz) - ADS1299 requires slower clock for register operations
3. **Cannot read different registers** from each ADC in one transaction - both receive the same command
4. **Response order is fixed** - Slave data always arrives first, then Master data
5. **Timing is critical** - The 2µs delays after CS changes ensure proper setup/hold times

---

## 7. Command Protocol

### Format
- **Transport**: UDP port 5000 (default)
- **Encoding**: UTF-8 strings
- **Termination**: Not required (packet boundary)

### Command Safety
**Command Behavior During Continuous Mode**:
- **SYS commands**: Execute without interrupting data flow. Filters, digital gain, network settings, and other parameters update in real-time while streaming continues.
- **SPI and USR commands**: Automatically call `continuous_mode_start_stop(LOW)` before executing. This ensures:
  - Proper SPI clock (2 MHz) for configuration
  - ADCs exit RDATAC mode
  - No data corruption during register access
- **Clock Speed Rationale**: Register operations above 4 MHz can be unstable on ADS1299. The firmware uses 2 MHz for all configuration operations to guarantee reliable communication, while data streaming runs at 16 MHz for maximum throughput.

### System Commands (Can be used during continuous mode)
```
sys start_cnt         Start streaming
sys stop_cnt          Stop streaming
sys adc_reset         Full ADC reset + sync (stops continuous mode)
sys esp_reboot        Complete reboot (stops continuous mode)
sys erase_flash       Wipe config → AP mode (stops continuous mode)

sys filters_on/off    Master filter switch (real-time)
sys filter_equalizer_on/off  (real-time)
sys filter_dc_on/off        (real-time)
sys filter_5060_on/off      (real-time)
sys filter_100120_on/off    (real-time)

sys networkfreq 50|60       (real-time)
sys dccutofffreq 0.5|1|2|4|8  (real-time)
sys digitalgain 1|2|4|8|16|32|64|128|256  (real-time)
```

### User Commands (Stop continuous mode before executing)
```
usr set_sampling_freq 250|500|1000|2000|4000
usr gain <channel|ALL> <1|2|4|6|8|12|24>
usr ch_power_down <channel|ALL> <ON|OFF>
usr ch_input <channel|ALL> <input_type>
usr ch_srb2 <channel|ALL> <ON|OFF>
```
- `set_sampling_freq`: Changes ADS1299 sampling rate
  - Automatically stops continuous mode first
  - Updates CONFIG1 register bits [2:0] on both ADCs
  - Validates input before applying
  
- `gain`: Sets hardware PGA gain for channels
  - Channel: 0-15 (0-7 master, 8-15 slave) or ALL
  - Gain values: 1, 2, 4, 6, 8, 12, 24x
  - Updates CHnSET register bits [6:4]
  - Examples: `usr gain 5 24` or `usr gain ALL 4`
  
- `ch_power_down`: Controls channel power state
  - Channel: 0-15 or ALL
  - ON = power on (normal operation)
  - OFF = power down (high impedance)
  - Updates CHnSET register bit [7]
  - Examples: `usr ch_power_down 5 OFF` or `usr ch_power_down ALL ON`
  
- `ch_input`: Selects channel input source
  - Channel: 0-15 or ALL
  - Updates CHnSET register bits [2:0]
  - Input types:
    - NORMAL: Normal electrode input (000)
    - SHORTED: Inputs shorted together (001)
    - BIAS_MEAS: Measure bias signal (010)
    - MVDD: Measure supply voltage (011)
    - TEMP: Temperature sensor (100)
    - TEST: Internal test signal (101)
    - BIAS_DRP: Positive electrode driver (110)
    - BIAS_DRN: Negative electrode driver (111)
  - Examples: `usr ch_input 5 SHORTED` or `usr ch_input ALL TEST`
  
- `ch_srb2`: Controls SRB2 (reference) connection
  - Channel: 0-15 or ALL
  - ON = closed (connected to SRB2)
  - OFF = open (disconnected)
  - Updates CHnSET register bit [3]
  - Examples: `usr ch_srb2 5 ON` or `usr ch_srb2 ALL OFF`

### SPI Commands (Stop continuous mode before executing)
```
spi M|S|B|T <len> <byte0> <byte1> ...
M=Master, S=Slave, B=Both, T=Test
Max 256 bytes per transaction
```

### Helper Functions

**modify_register_bits()**:
- Helper for safe register modification on both ADCs
- Reads current value from both ADCs using read_Register_Daisy()
- Modifies only specified bits using mask
- Writes back to both ADCs
- Verifies the operation succeeded
- Includes debug logging

**update_channel_register()**:
- Helper for channel-specific register updates
- Maps channel number (0-15) to correct ADC and register
- Always uses read_Register_Daisy() for reading
- Handles master/slave selection automatically
- Returns true if update successful
- Used by gain and ch_power_down commands

**Channel Control (CHnSET Registers)**:
- CHnSET registers (0x05-0x0C) control individual channels
- Channels 0-7 on Master ADC, 8-15 on Slave ADC
- Register bit layout:
  - Bit [7]: Power down control (0=normal, 1=power down)
  - Bits [6:4]: PGA gain (000=1x, 001=2x, 010=4x, 011=6x, 100=8x, 101=12x, 110=24x)
  - Bit [3]: SRB2 connection (0=open, 1=closed)
  - Bits [2:0]: Input mux selection
    - 000: Normal electrode input
    - 001: Inputs shorted together
    - 010: Bias measurement
    - 011: Supply measurement (MVDD)
    - 100: Temperature sensor
    - 101: Test signal
    - 110: Bias drive positive (BIAS_DRP)
    - 111: Bias drive negative (BIAS_DRN)
- Default values:
  - Normal mode: 0x05 (test signal, gain 1x, SRB2 open, powered on)
  - BCI mode: 0x08 (normal electrode input, gain 1x, SRB2 closed, powered on)
- Common configurations:
  - Unused channel: Power down + shorted inputs (0x81)
  - Differential mode: Normal input, SRB2 open (0x00 with desired gain)
  - Referenced mode: Normal input, SRB2 closed (0x08 with desired gain)

---

## 8. Performance & Optimization Notes

### CPU & Power
- **CPU locked**: 160MHz (only +30mW vs 80MHz but huge headroom)
- **Power**: 400mW @ 500Hz, 470mW @ 4kHz
- **Battery**: 10+ hours on 1100mAh LiPo

### Critical Timing
- **DRDY ISR**: <15µs max (IRAM placement)
- **CS edges**: 40ns (register writes)
- **Context switch**: ~5µs when ADC task wakes

### Memory & Queues
- **Stack sizes**: ADC task 2048B, UDP task 2048B
- **Queue depth**: 5 slots, each slot size varies by sampling rate
- **Packet size**: Adaptive (264-1460B based on sampling rate)
- **Buffer allocation**: Max size (1460B + 4B battery) to handle all rates
- **Blocking behavior**:
  - ADC/DSP task: NEVER blocks - skips enqueue if queue full
  - Data TX task: Blocks waiting for data (normal producer-consumer)

### WiFi Power Optimization
```c
WiFi.setSleep(true);               // Modem sleeps between DTIM beacons
cfg.sta.listen_interval = 1;       // Wake every beacon interval
esp_wifi_set_ps(WIFI_PS_MAX_MODEM); // Deepest power-save mode
```
- Allows WiFi modem to sleep between packets
- Significantly reduces idle power consumption
- No impact on streaming performance

### Optimization Tricks
- **Task notifications**: 45% faster than semaphores
- **Direct register IO**: 30x faster than digitalWrite
- **DMA transfers**: Cleaner edges than byte loops
- **Fixed-point DSP**: Consistent timing, no float variance
- **Adaptive packing**: Single volatile read adds ~1-2 CPU cycles (12ns @ 160MHz)
- **Digital gain usage**: Helps occupy full 32-bit range for filter precision, not just visualization

---

## 9. Utility Functions & Helpers

### safeTimeDelta()
```c
// Prevents -1 underflow if ISR updates timestamp mid-calculation
return (now >= then) ? (now - then) : 0;
```

### Battery_Sense Class
- **IIR filter**: α=0.05 default (20x jitter reduction)
- **Period**: Configurable, default 32ms
- **Scaling**: Hardware-specific calibration factor (0.01235)

### Blinker Class
- **Zero-cost**: Only writes on state changes
- **Patterns**: Burst mode (N flashes per period)
- **Polarity**: Handles active-high or active-low

---

## 10. Known Issues & Workarounds

### Quirks to Remember
- **WiFi + ADC2** = instant crash (hardware limitation)
- **USB ground loops** = unusable data (physics problem)
- **IIR at 0.5Hz/4kHz** = potential instability (use higher digital gain to help)
- **Python lacks arithmetic shift** = manual sign extension needed
- **DC offset on inputs** = Check with multimeter before amplifying
- **Unused channels** = Power down AND short inputs using `ch_input SHORTED`

### Debug Features
- **SERIAL_DEBUG**: Set to 1 in defines.h for verbose output
- **Test mode 'T'**: Sends SPI clocks without CS for scope

---

## Quick Command Reference Card

```bash
# Start recording
sys start_cnt

# Stop recording  
sys stop_cnt

# Change sampling rate
usr set_sampling_freq 1000

# Set channel gains
usr gain 5 24       # Channel 5 to 24x gain
usr gain ALL 4      # All channels to 4x gain

# Channel power control
usr ch_power_down 5 OFF    # Power down channel 5
usr ch_power_down ALL ON   # Power on all channels

# Channel input selection
usr ch_input 5 SHORTED     # Short channel 5 inputs
usr ch_input ALL NORMAL    # All channels to normal input
usr ch_input 0 TEST        # Channel 0 to test signal

# SRB2 reference control
usr ch_srb2 ALL ON         # Connect all to SRB2 (referenced mode)
usr ch_srb2 5 OFF          # Disconnect channel 5 from SRB2

# Configure unused channels
usr ch_power_down 15 OFF   # Power down
usr ch_input 15 SHORTED    # Short inputs

# Reset everything
sys adc_reset     # Just ADCs
sys esp_reboot    # Full system

# Configure filters
sys filters_on
sys networkfreq 60      # US mains
sys dccutofffreq 0.5    # Slow drift removal
sys digitalgain 8       # 8x amplification

# Debug
spi M 3 0x20 0x00 0x00  # Read ADC ID
spi M 3 0x25 0x00 0x00  # Read CH1SET register (check all settings)

# Complete unused channel setup example
usr ch_power_down 14 OFF   # Power down channel 14
usr ch_input 14 SHORTED    # Short its inputs
usr ch_power_down 15 OFF   # Power down channel 15  
usr ch_input 15 SHORTED    # Short its inputs
```

---

*Happy hacking, silly woofer :3*