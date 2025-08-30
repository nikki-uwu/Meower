# BCI Project Complete Timeline
## 16-Channel EEG Acquisition System Development

### Topic Definitions

1. **Hardware Selection** - Component evaluation, chip selection, module comparison
2. **Analog Front-End** - ADS1299 configuration, input filtering, bias/reference management
3. **PCB Design** - Layout, routing, stackup, signal integrity, EMI mitigation
4. **Power Management** - DC-DC converters, battery systems, power distribution
5. **Raspberry Pi Dev** - Initial prototyping, SPI verification, Python testing
6. **ESP32 Firmware** - Embedded software, FreeRTOS, SPI drivers, WiFi streaming
7. **DSP** - Digital filters (FIR/IIR), real-time processing algorithms
8. **GUI/Visualization** - Python PC-side software, plotting, user interface
9. **Test & Measurement** - Signal generators, test fixtures, measurement techniques
10. **RF/Wireless** - WiFi optimization, BLE alternatives, antenna design

---

## Chronological Timeline

| Date | Start | End | Duration | Topic(s) | Work Details |
|------|-------|-----|----------|----------|--------------|
| 2024-12-05 | 08:47:30 | 08:51:38 | 0h 4m | Hardware Selection | Researched nRF52840 modules with USB-C and charging. Compared Fanstel BC840E, Raytac MDBT50Q-P1M, Ebyte E73-2G4M08S1C. Determined USB-C + charging combo rare. |
| 2024-12-07 | 19:39:42 | 19:45:16 | 0h 5m | Hardware Selection | Troubleshooting ESP32-C3 device error 22 in Platform IO. Determined 1 of 10 units defective, hardware issue. |
| 2024-12-09 | 05:59:54 | 06:03:11 | 0h 3m | DSP, Hardware Selection | **DSP**: Analyzed EEGNet architecture for 16-channel feature extraction at 200Hz. **Hardware**: Confirmed sampling rate requirements for EEG bands. |
| 2024-12-09 | 08:02:01 | 08:02:26 | 0h 0m | PCB Design | Identified LCSC as JLCPCB's component supplier for extended library components. |
| 2024-12-10 | 21:27:24 | 21:33:17 | 0h 6m | Hardware Selection | Warning about P0.29 pin on Seeed nRF52840 - never use for battery pass-through, risk of permanent damage. |
| 2024-12-17 | 21:47:41 | 22:59:18 | 1h 12m | Hardware Selection, DSP | **Hardware**: Researched OpenBCI Cyton, HackEEG, freeEEG32 DIY projects with recent Gerbers. **DSP**: Identified Alpha (8-12Hz) and Beta (13-30Hz) as key BCI frequency bands. |
| 2024-12-18 | 10:49:46 | 11:04:32 | 0h 15m | DSP | 50/60Hz powerline interference analysis. Notch filter necessary. WiFi channel 1,6,11 non-overlapping recommendation. |
| 2024-12-18 | 23:49:31 | 23:54:14 | 0h 5m | PCB Design | KiCad to EasyEDA: must use Archive Project function, not manual zip. KiCad v5.1+ required. |
| 2024-12-19 | 00:11:51 | 00:18:53 | 0h 7m | PCB Design | Flex PCB edge connectors: Hirose FH28-50S-0.5SH needs 50 pads at 0.5mm pitch, 1.5mm×0.3mm pads, ENIG finish. |
| 2025-01-17 | 01:11:46 | 01:12:00 | 0h 0m | Hardware Selection | 20.5Wh battery under 100Wh limit for shipping internationally via DHL. |
| 2025-01-20 | 10:07:16 | 10:08:00 | 0h 1m | Power Management | LiPo 1500mAh in 10×25×40mm verified feasible. 555Wh/L energy density on high end but possible. |
| 2025-01-20 | 15:18:44 | 15:19:32 | 0h 1m | Power Management | Battery capacity estimation: 40mAh at 4.0V indicates 200-270mAh total capacity. |
| 2025-01-22 | 02:41:04 | 02:47:29 | 0h 6m | Hardware Selection | Compared RFduino (nRF51822 BLE-only) vs ESP32-C3 (RISC-V WiFi+BLE). Decided on ESP32-C3 for BCI. |
| 2025-01-24 | 23:04:50 | 23:04:56 | 0h 0m | PCB Design | LSM6DSVTR: separate 100nF decoupling cap required per power pin (VDD and VDD_IO). |
| 2025-01-25 | 09:10:50 | 09:28:55 | 0h 18m | PCB Design | 1×5cm board layout: USB-C/charger/DC-DC in first half, 3.3V routing on layer 3. Direct traces better than vias for nearby components. |
| 2025-01-25 | 19:50:06 | 20:56:55 | 1h 7m | Hardware Selection, Analog Front-End | **Major decision**: ADS1299 selected over ADS131M08. Calculated 8ch×1000Hz×24bit = 192kbps data rate. ADS1299 chosen for integrated bias drive, lead-off detection. ESP32-C3-MINI-1-N4 module selected. |
| 2025-01-26 | 19:09:41 | 19:10:27 | 0h 1m | Analog Front-End | RC filters: TI uses 5kΩ+4.7nF (6.7kHz cutoff), OpenBCI uses 2.2kΩ+1nF (72kHz). Both valid for EEG. |
| 2025-01-26 | 20:00:00 | 20:50:22 | 0h 50m | PCB Design | EasyEDA: edited 26-pin connector symbol to show all pins on one side. Decoupling network layout strategies. |
| 2025-01-26 | 20:58:23 | 21:11:06 | 0h 13m | PCB Design | Space constraints for 16 RC pairs. Solution: Bourns 4609X resistor arrays + capacitor arrays or bottom placement. |
| 2025-01-26 | 22:18:30 | 23:58:14 | 1h 40m | Analog Front-End, Power Management | **Analog**: Single-ended mode configuration, SRB2 routing, unipolar vs bipolar supply. **Power**: ~5.6mA for two ADS1299s. VCAP1 needs 1μF to ground. |
| 2025-01-27 | 00:16:46 | 00:16:58 | 0h 0m | Analog Front-End | Channel count: 8 channels regardless of unipolar/bipolar mode. |
| 2025-01-27 | 01:50:51 | 01:51:06 | 0h 0m | PCB Design | Ground pour between traces: via stitching every 10mm beneficial. |
| 2025-01-27 | 09:04:27 | 09:24:12 | 0h 20m | Power Management | Buck/boost selection: TPS62135 (buck), TPS61023 (boost). Parallel architecture. LC filter for ADC rails. |
| 2025-01-27 | 10:36:05 | 11:40:41 | 1h 5m | Analog Front-End | Complete pin analysis: Pin 61 (VCAP1) needs 1μF to ground. Pin 64 must float. Star power routing. Up to 8 devices daisy-chainable. |
| 2025-01-27 | 13:16:43 | 13:24:32 | 0h 8m | Analog Front-End | Input filtering: separate caps to ground (not differential). Negative pins need termination even if unused. |
| 2025-01-27 | 14:58:33 | 14:58:33 | 0h 0m | Hardware Selection | ESP32-S3 advantages (dual-core, more RAM) vs C3. Decided C3 sufficient for 16ch streaming. |
| 2025-01-27 | 21:23:51 | 23:19:28 | 1h 56m | Analog Front-End | Ground connections: AVSS pin 31, multiple DGND pins. Pin 61 special handling. "Bypass" means ADD capacitors, not omit them. |
| 2025-01-28 | 08:13:37 | 08:13:53 | 0h 0m | Power Management | Decoupling basics: 0.1µF minimum for high-freq, add 10µF for bulk. |
| 2025-01-28 | 11:19:34 | 11:20:16 | 0h 1m | PCB Design | Power traces under chip: 1-2mm acceptable with good ground return. |
| 2025-01-28 | 16:04:45 | 17:14:44 | 1h 10m | PCB Design | Bias line routing: star configuration, 0.8mm traces on layer 3, ground planes for shielding. 24mm length acceptable for DC bias. |
| 2025-01-28 | 20:12:46 | 20:44:05 | 0h 31m | Analog Front-End | DIN pin = MOSI equivalent, DOUT = MISO. DRDY indicates data ready. Daisy: ADC1_DOUT→ADC2_DIN. |
| 2025-01-28 | 21:41:53 | 21:54:15 | 0h 13m | PCB Design | Duplicate components in EasyEDA: Group with Ctrl+G before copying to maintain relative positions. |
| 2025-01-29 | 09:22:35 | 09:32:12 | 0h 10m | PCB Design | Mezzanine architecture: ADCs on clean board, DC-DC on separate board. Ground on alternating connector pins. |
| 2025-01-29 | 10:08:09 | 10:08:16 | 0h 0m | Hardware Selection | Connector options: JST for DIY, FPC for professional, DIN for medical grade. |
| 2025-01-29 | 12:59:41 | 13:19:16 | 0h 20m | Raspberry Pi Dev | Pi power: 5V pin supplies 1-2.5A, 3.3V limited to 500mA. Two ADS1299s need ~100mA. |
| 2025-01-29 | 14:03:18 | 14:03:26 | 0h 0m | Raspberry Pi Dev | Development strategy: start with Pi for line-by-line debugging. |
| 2025-01-29 | 14:58:00 | 14:58:03 | 0h 0m | Raspberry Pi Dev | 40-pin GPIO breakout cable with female DuPont connectors identified. |
| 2025-01-30 | 10:34:45 | 11:05:58 | 0h 31m | Analog Front-End | Project summary: Pin 64 floating critical. Bias from master only. SRB2 shorted at PCB level. |
| 2025-01-30 | 13:14:01 | 13:14:43 | 0h 1m | Analog Front-End | SRB voltage: no division with high-impedance inputs. Both ADCs see same reference. |
| 2025-01-31 | 01:53:05 | 03:10:01 | 1h 17m | Analog Front-End | **Daisy-chain marathon**: Master CLK_EN=1, slave CLK_EN=0. Shared START signal. Single DRDY from master. CS can be grounded. |
| 2025-01-31 | 14:05:54 | 14:40:45 | 0h 35m | Analog Front-End | Design review: 16-channel validated. No shielded cables (capacitive loading). Twisted-pair preferred. |
| 2025-01-31 | 16:52:03 | 16:54:13 | 0h 2m | Raspberry Pi Dev | Pi compatibility: any GPIO works for START/INT. Hardware SPI pins fixed. START driven high once. |
| 2025-01-31 | 23:28:53 | 23:29:12 | 0h 0m | Raspberry Pi Dev | GPIO list: 4,17,22-25,5-6,12-13,16,19-21,26 available for control signals. |
| 2025-02-01 | 13:49:20 | 13:55:15 | 0h 6m | Power Management | Buck converters: TLV62569DBVR confirmed good. MP2307, TPS62130, LTC3638 alternatives. 1A rating for 200mA load. |
| 2025-02-01 | 15:59:54 | 16:00:11 | 0h 0m | Hardware Selection | Dual-entry/pass-through female header identified for board interconnection. |
| 2025-02-02 | 14:50:46 | 15:49:49 | 0h 59m | ESP32 Firmware | GPIO mapping via I/O matrix. SCLK→GPIO2, MOSI→GPIO3/7, MISO→GPIO6, INT→GPIO4. |
| 2025-02-02 | 17:17:50 | 17:18:04 | 0h 0m | Power Management | Power bank usage: parallel powering recommended over series through Pi. |
| 2025-02-03 | 02:53:52 | 03:05:08 | 0h 11m | PCB Design | SRB2 routing: 0.8mm wide, 24mm long on layer 3 between ground planes. 4-layer stack provides good isolation. |
| 2025-02-03 | 06:45:17 | 06:54:54 | 0h 10m | DSP | Optimized array selection: pointer-based subset, variable loop bounds for DSP operations. |
| 2025-02-03 | 12:42:14 | 12:43:07 | 0h 1m | Power Management | Boost ICs: TPS61023 (>90% efficiency), LTC3402 (3MHz), MAX756/757 for 5V from LiPo. |
| 2025-02-03 | 18:39:28 | 19:02:30 | 0h 23m | ESP32 Firmware | FreeRTOS architecture: SPI task for DRDY monitoring, WiFi task for streaming. |
| 2025-02-04 | 07:37:27 | 07:39:54 | 0h 2m | PCB Design | SPI traces: ground pours between traces beneficial, via stitching for noise reduction. |
| 2025-02-04 | 14:22:31 | 14:25:52 | 0h 3m | PCB Design | Power plane analysis: 10cm×10cm plane provides lower impedance than traces. Current spreads across plane. |
| 2025-02-05 | 10:49:48 | 10:50:55 | 0h 1m | DSP | Efficient FFT index shift: ternary operator (i < n/2) ? i : i - n optimal. |
| 2025-02-05 | 12:48:48 | 12:55:39 | 0h 7m | Power Management | Ripple reduction: 100mV ripple at ESP32. Solution: LC post-filter with ferrite bead + parallel caps. |
| 2025-02-13 | 21:35:04 | 21:50:09 | 0h 15m | Raspberry Pi Dev | IDE setup: Thonny for debugging with variable explorer, Spyder for plotting. |
| 2025-02-13 | 22:54:06 | 23:02:12 | 0h 8m | Raspberry Pi Dev | SPI enabled via raspi-config. Mode 1, 500kHz. Loopback test with 0xDE,0xAD,0xBE,0xEF. |
| 2025-02-14 | 00:51:32 | 00:53:12 | 0h 2m | Raspberry Pi Dev | Pull-up resistors: 10kΩ to 3.3V for RESET/PWDN, button to ground. |
| 2025-02-14 | 02:06:37 | 02:18:08 | 0h 11m | Raspberry Pi Dev | GPIO 22 for reset. Commands: RESET(0x06), SDATAC(0x11), START(0x08), RDATAC(0x10). |
| 2025-02-14 | 10:27:14 | 10:28:07 | 0h 1m | Raspberry Pi Dev | Daisy config: Master CONFIG1=0xD8, Slave CONFIG1=0xC8. 54 bytes per frame. |
| 2025-02-14 | 12:54:46 | 14:06:12 | 1h 11m | Analog Front-End | SPI Mode 1 confirmed (CPOL=0, CPHA=1) from timing diagrams. Figure 47 in datasheet. |
| 2025-02-14 | 17:06:36 | 17:20:44 | 0h 14m | Raspberry Pi Dev | Hex printing in Python: f"{num:02x}" for formatted strings, list comprehension for arrays. |
| 2025-02-14 | 18:26:12 | 18:26:24 | 0h 0m | Raspberry Pi Dev | 24-bit two's complement conversion: check bit 23, subtract (1<<24) if set. |
| 2025-02-14 | 19:04:31 | 19:12:01 | 0h 7m | Raspberry Pi Dev | Register writing in daisy: [WREG, count, master_data, slave_data]. No dummy bytes. |
| 2025-02-14 | 20:26:46 | 21:15:20 | 0h 49m | Raspberry Pi Dev | UDP streaming: port 5555, queue-based sender thread, 1MB socket buffer. |
| 2025-02-14 | 22:35:33 | 23:56:33 | 1h 21m | Raspberry Pi Dev | Plot optimization: NumPy arrays, batch packet reading, non-blocking socket. |
| 2025-02-15 | 00:07:27 | 00:42:59 | 0h 36m | Raspberry Pi Dev | Channel debug: CONFIG3=0xEC enables reference. CHnSET=0x65 for test signal. |
| 2025-02-15 | 01:55:04 | 02:23:49 | 0h 29m | Raspberry Pi Dev | Daisy clarification: actual register data for slave, not dummy bytes. |
| 2025-02-16 | 02:08:02 | 02:08:02 | 0h 0m | Test & Measurement | DAC question for test signal generation. |
| 2025-02-16 | 03:19:51 | 04:17:11 | 0h 57m | Raspberry Pi Dev | Packet structure: 54 bytes, pipeline effect, Device#1 ID at byte 6, Device#2 at byte 8. |
| 2025-02-17 | 04:36:13 | 08:08:07 | 3h 32m | Raspberry Pi Dev, PCB Design | **Pi Dev**: GPIO 23,24 safe for RESET/PWDN. **PCB**: 2.7mm NPTH mounting holes. 10kΩ pull-ups recommended. Pi 5 has 20mA per pin. |
| 2025-02-17 | 11:17:17 | 11:22:33 | 0h 5m | Hardware Selection | Ball/button electrodes with Ag/AgCl coating, heatshrink for strain relief. |
| 2025-02-25 | 22:16:51 | 03:57:30 | 5h 41m | ESP32 Firmware | **SPI implementation marathon**: Manual CS control. 54-byte frames. Mode 1. UDP to 192.168.137.1:5555. |
| 2025-02-28 | 08:51:51 | 09:46:53 | 0h 55m | DSP | 50Hz notch: IIR with Q=20-30. Dual notch for 50Hz and 100Hz harmonics. |
| 2025-03-01 | 05:38:36 | 06:41:54 | 1h 3m | GUI/Visualization | Spectrogram: multiprocessing with shared dict. Wavelet with Morlet, scales 1-128. |
| 2025-03-08 | 14:14:03 | 15:27:25 | 1h 13m | ESP32 Firmware | Final debug: Motion artifacts vs EMG signals. 20-500Hz for EMG, <20Hz artifacts. |
| 2025-03-16 | 18:52:36 | 22:00:54 | 3h 8m | ESP32 Firmware | Control multiple SPI slaves. Converted Python xfer() to C++. Added 5μs delay after CS for tCSS. |
| 2025-03-17 | 11:35:32 | 11:37:19 | 0h 2m | Power Management | MB102 breadboard power supply recommended. Provides both 3.3V and 5V, USB input. |
| 2025-03-18 | 20:40:48 | 20:42:30 | 0h 2m | ESP32 Firmware | MISRA-C type casting uint16_t to int16_t. Pointer-pun and union techniques. |
| 2025-03-28 | 06:45:02 | 07:08:28 | 0h 23m | GUI/Visualization | Matplotlib flashing fix. Set explicit backend TkAgg/Qt5Agg. |
| 2025-03-28 | 21:49:46 | 23:25:50 | 1h 36m | ESP32 Firmware | SPI beginTransaction overhead <1μs. esp_timer_get_time() for timeouts. |
| 2025-03-29 | 00:55:08 | 01:10:20 | 0h 15m | ESP32 Firmware | udp.parsePacket() returns bytes or 0. Python flush with setblocking(False) loop. |
| 2025-03-30 | 15:58:51 | 18:17:41 | 2h 19m | GUI/Visualization, DSP | **GUI**: Frame parsing optimization with NumPy. **DSP**: Combined 50/100Hz notch filters. Real-time plotting with matplotlib blitting. |
| 2025-04-01 | 23:30:59 | 23:49:46 | 0h 19m | Power Management | LM317L current limiter at 3.3V. LT3080 alternative for low dropout. 42Ω for 30mA limiting. |
| 2025-04-02 | 22:33:27 | 22:44:15 | 0h 11m | Power Management | USB power from oscilloscope not cleaner than PC. Use dedicated regulated supply. |
| 2025-04-03 | 01:06:41 | 01:23:24 | 0h 17m | DSP | Notch filter normalization. DC gain sum(b)/sum(a). Combined filter through convolution. |
| 2025-04-03 | 21:09:03 | 21:09:31 | 0h 0m | Analog Front-End | ADS1299 bias amplifier shifts body potential to mid-supply for unipolar operation. |
| 2025-04-04 | 23:19:59 | 23:20:29 | 0h 0m | Test & Measurement | EMG cable microphonics. Motion artifacts <20Hz, EMG 20-500Hz. |
| 2025-04-05 | 00:53:35 | 02:17:21 | 1h 24m | GUI/Visualization | WiFi power analysis plot. Windows WLAN API via ctypes. Channel calculation from frequency. |
| 2025-04-05 | 13:33:55 | 13:34:27 | 0h 1m | GUI/Visualization | Tkinter window maximizing platform-specific. Windows: state('zoomed'). |
| 2025-04-18 | 00:23:11 | 00:23:47 | 0h 1m | Hardware Selection | nRF52840 power requirements. VDD 1.7-3.6V, VDDH 2.5-5.5V. |
| 2025-04-21 | 01:52:48 | 02:50:34 | 0h 58m | Power Management | TPS631000 evaluation for dual rails. 2A continuous adequate for 140mA average/500mA peak. 88-95% efficiency. |
| 2025-04-21 | 21:19:08 | 21:31:10 | 0h 12m | Power Management | ESP32-C3 power pin decoupling. Each IC needs own 0.1μF within 2mm, bulk caps can be shared. |
| 2025-04-22 | 11:35:33 | 12:21:22 | 0h 46m | PCB Design | TPS631000 placement near board edge OK. Input cap <2mm from IC. Via fence at 2.25mm spacing. |
| 2025-04-22 | 14:00:22 | 14:18:41 | 0h 18m | PCB Design | SPI trace spacing with 0.25mm width. 3W rule (0.75mm) for -50dB crosstalk. Guard traces minimal benefit with ground plane. |
| 2025-04-22 | 18:14:08 | 18:15:53 | 0h 2m | PCB Design | Specific stackup spacing: 0.75mm recommended for 3W rule, 1.25mm for belt-and-suspenders. |
| 2025-04-22 | 19:35:21 | 19:35:49 | 0h 0m | PCB Design | Ground pours with vias provide 7dB improvement at 3W spacing. |
| 2025-04-22 | 21:19:29 | 21:42:11 | 0h 23m | ESP32 Firmware | ESP32-C3 ADC channels all equivalent. GPIO2 boot strapping concern with ADS1299 DOUT. |
| 2025-04-22 | 23:28:51 | 23:34:52 | 0h 6m | ESP32 Firmware | GPIO9 boot pin for blue LED. Current-sink topology: LED anode to 3.3V through 330Ω. |
| 2025-04-23 | 01:00:27 | 01:01:02 | 0h 1m | PCB Design | DC-DC inductor at edge near battery pins good - shortens input current loop. |
| 2025-04-23 | 04:48:51 | 04:51:14 | 0h 2m | PCB Design | Surround inductor with ground pour and vias. No cone-shaped voids. |
| 2025-04-29 | 07:53:51 | 08:15:31 | 0h 22m | RF/Wireless | nRF52840 antenna: 31mm wire monopole vs U.FL. Wire provides zero insertion loss. |
| 2025-05-03 | 11:21:39 | 11:22:58 | 0h 1m | PCB Design | 0.2mm traces acceptable for ADS1299. Johnson noise ~30nV RMS, below 1μV noise floor. |
| 2025-05-07 | 02:59:27 | 03:52:52 | 0h 53m | PCB Design | Resistor selection: 113kΩ/511kΩ for 3.313V from 0.6V reference. TE Neohm 0.1% parts. |
| 2025-05-07 | 05:54:59 | 06:16:29 | 0h 22m | PCB Design | DC-DC layout: 5-10mm separation adequate. Each converter needs power island. SW node minimal copper. |
| 2025-05-07 | 09:22:44 | 10:09:57 | 0h 47m | PCB Design | TPS63900 inductor 3mm from 100μF cap OK. Shielded inductor, ground via fence provides isolation. |
| 2025-05-07 | 15:19:24 | 15:48:28 | 0h 29m | PCB Design | Power switch 3mm from inductor no issue. DC current only, input caps trap switching currents locally. |
| 2025-05-08 | 12:07:42 | 12:21:51 | 0h 14m | RF/Wireless | WiFi/BLE amplification. FEMs integrate PA+LNA+switch. |
| 2025-05-09 | 21:23:15 | 21:25:16 | 0h 2m | RF/Wireless | ESP32-C3 WiFi router settings. 802.11n-only, 20/40MHz auto, WPA2-AES, DTIM 1-2. |
| 2025-05-10 | 13:19:52 | 13:21:03 | 0h 1m | Test & Measurement | Power measurement: INA219/226 boards for logging. Nordic PPK2 for BLE. 10Ω sense resistor. |
| 2025-05-10 | 17:16:32 | 20:07:26 | 2h 51m | ESP32 Firmware | SlimeVR IMU calibration loop fix. Rest detection and bias forgetting. VQF.resetBias() implementation. |
| 2025-05-12 | 09:43:00 | 10:02:30 | 0h 20m | PCB Design | 3.3V plane solid with 0.5-2mm ground ring. Via fence 2mm spacing for EMI suppression. |
| 2025-05-12 | 18:44:55 | 18:44:56 | 0h 0m | PCB Design | Power plane as return path not recommended. Use ground plane reference. |
| 2025-05-13 | 05:43:52 | 08:03:05 | 2h 19m | Hardware Selection | nRF52833 verification. Blank chip needs SWD programming. |
| 2025-05-15 | 13:58:42 | 14:57:08 | 0h 58m | Hardware Selection | nRF52833 programming methods. SWD only on blank chip. |
| 2025-05-16 | 14:52:20 | 15:09:31 | 0h 17m | Power Management | 0.2V drop diagnosis: Power path MOSFET body diode conducting. Gate not driven properly. |
| 2025-05-16 | 20:42:51 | 21:35:59 | 0h 53m | ESP32 Firmware | Battery_Sense class with 1s cache. vTaskDelay for FreeRTOS. Non-blocking LED blinker. |
| 2025-05-17 | 12:28:59 | 13:52:24 | 1h 23m | ESP32 Firmware, Analog Front-End | **Firmware**: Battery_Sense class refinement. **Analog**: OPA392 selected (4.4nV/√Hz, 10fA bias). Non-inverting 2x gain. |
| 2025-05-17 | 20:43:27 | 23:27:04 | 2h 44m | Test & Measurement | ADS1299 testing guide. ECG Lead I, EMG biceps, EOG. <1μV RMS noise target. Internal test ±1.875mV. |
| 2025-05-17 | 21:20:00 | 21:20:01 | 0h 0m | DSP | NumPy array broadcasting for baseline correction. C = A - B automatic. |
| 2025-05-19 | 00:45:07 | 00:47:18 | 0h 2m | GUI/Visualization | BrainFlow clarification. SDK not GUI, use STREAMING_BOARD for receive-only. |
| 2025-05-19 | 21:25:46 | 21:26:22 | 0h 1m | PCB Design | Via spacing 2.6mm safe below 2-3GHz. 5.8GHz slot antenna frequency. |
| 2025-05-20 | 19:14:10 | 21:36:46 | 2h 23m | GUI/Visualization | Custom BrainFlow board integration. 33-byte Cyton frame format. |
| 2025-05-21 | 01:17:23 | 01:17:30 | 0h 0m | GUI/Visualization | BrainFlow file paths correction. Inherit from Board not SyntheticBoard. |
| 2025-05-21 | 17:44:59 | 17:46:43 | 0h 2m | Hardware Selection | GPIO ESD protection arrays. TPD8E003 8-channel. |
| 2025-05-21 | 19:34:18 | 19:35:53 | 0h 2m | GUI/Visualization | Correct header: openbci/cyton_wifi_shield.h not wifi_board.h. |
| 2025-05-21 | 20:49:17 | 22:37:21 | 1h 48m | GUI/Visualization | Single-file UDP16Board implementation. 128-byte packets as 16 doubles. |
| 2025-05-21 | 23:49:58 | 23:56:33 | 0h 7m | GUI/Visualization | Plain text summary of BrainFlow integration process and vrchat_board implementation. |
| 2025-05-22 | 00:05:10 | 02:21:21 | 2h 16m | GUI/Visualization | vrchat_board.cpp implementation. 58-byte packets, 16 channels parsing. |
| 2025-05-22 | 09:36:05 | 10:17:59 | 0h 42m | PCB Design | Buck converter Cff still needed for stability. RGB LED solutions. |
| 2025-05-22 | 16:34:37 | 17:46:21 | 1h 12m | PCB Design | 1A SMD fuse placement at battery positive. Littelfuse 0467.100. |
| 2025-05-22 | 19:25:23 | 19:30:16 | 0h 5m | PCB Design | 0.7mm test points on SPI traces OK. Inline pads add ~3pF, stub <1mm acceptable. |
| 2025-05-22 | 21:09:09 | 21:24:50 | 0h 16m | PCB Design | Via connections on L2/L4 should have copper pour patches. Reduces inductance, adds decoupling. |
| 2025-05-22 | 21:52:04 | 23:08:29 | 1h 16m | Test & Measurement | Test board design with pogo pins. 2-layer, bottom ground, via stitching every 2mm. Local ground pads. |
| 2025-05-22 | 22:44:03 | 22:45:07 | 0h 1m | Test & Measurement | Probing methodology finalized. Shielded inductors, via fence 2.25mm, feedback on L3. |
| 2025-05-23 | 01:02:32 | 05:02:27 | 4h 0m | Test & Measurement | Massive test board design session. EasyEDA PCB Module for coordinate transfer. Exposed pads for probes. |
| 2025-05-23 | 03:43:50 | 03:47:34 | 0h 4m | Test & Measurement | No trace length matching needed for test fixture. Individual headers 5-10mm apart. |
| 2025-05-24 | 15:11:34 | 16:18:38 | 1h 7m | Hardware Selection | Dry electrode analysis. Conductive rubber with Ag/AgCl best. Active amplification essential. |
| 2025-05-29 | 04:36:25 | 08:18:42 | 3h 42m | Test & Measurement | Signal generator selection. FY6900 DDS for EEG. High-Z mode for ADS1299. 99.9kΩ/100Ω divider. |
| 2025-05-29 | 20:34:55 | 22:03:39 | 1h 29m | Test & Measurement | Voltage divider testing setup. AC-couple through 10μF or reference to BIASOUT. |
| 2025-06-10 | 21:33:26 | 21:33:46 | 0h 0m | DSP | EEG needs flat magnitude response ±0.5dB across 0.1-70Hz for amplitude features. |
| 2025-06-11 | 09:07:18 | 09:07:51 | 0h 1m | ESP32 Firmware | SPI ringing analysis at 4MHz. Real probe ground inductance resonance, not bandwidth artifact. |
| 2025-06-11 | 09:26:21 | 09:41:56 | 0h 16m | ESP32 Firmware | MISO droop normal behavior. ADS1299 releases DOUT high-impedance. Added GPIO pull-down. |
| 2025-06-11 | 17:51:31 | 17:53:49 | 0h 2m | ESP32 Firmware | ESP32-C3 SPI latency gaps between bytes. Single-core scheduling with WiFi stack. |
| 2025-06-11 | 19:01:24 | 20:37:41 | 1h 36m | ESP32 Firmware | Simultaneous CS control. Implemented atomic GPIO register writes using WRITE_PERI_REG. |
| 2025-06-11 | 22:13:07 | 22:14:03 | 0h 1m | ESP32 Firmware | Batch 32 frames per UDP packet. 864 bytes + battery + timestamp < 1472 MTU. |
| 2025-06-11 | 23:15:05 | 23:52:32 | 0h 37m | ESP32 Firmware | Dual-task FreeRTOS architecture. High-priority ADC task, mid-priority network task. |
| 2025-06-12 | 00:09:37 | 00:33:47 | 0h 24m | ESP32 Firmware | Fixed DRDY blocking issue. ISR takes 10μs, uses task notifications instead of polling. |
| 2025-06-12 | 03:10:31 | 04:14:40 | 1h 4m | ESP32 Firmware | Deep dive into FreeRTOS task notifications. BaseType_t hp flag, ulTaskNotifyTake mechanics. |
| 2025-06-12 | 07:44:20 | 09:02:48 | 1h 18m | ESP32 Firmware | SPI clock optimization 2-8MHz. Determined 4MHz optimal for breadboard. |
| 2025-06-12 | 10:19:26 | 11:24:00 | 1h 5m | DSP | ADS1299 sinc³ filter compensation. Implemented 5-tap FIR. |
| 2025-06-12 | 10:55:29 | 10:55:30 | 0h 1m | ESP32 Firmware | FIR filter integration planning. |
| 2025-06-12 | 21:24:33 | 23:55:18 | 2h 31m | ESP32 Firmware | constexpr vs #define. WiFi task modes. Timestamps, beacon, queue size bug fix. getTimer8us(). |
| 2025-06-13 | 00:04:24 | 07:08:59 | 7h 5m | ESP32 Firmware | Fixed crashes from queue size mismatch. WiFi/LwIP pool exhaustion. Bundle frames. Compiler optimization -O3. |
| 2025-06-13 | 09:24:42 | 10:06:56 | 0h 42m | GUI/Visualization | Timer jitter visualization. np.diff for frame deltas. Ring buffer matching channel buffer. |
| 2025-06-13 | 11:10:20 | 11:10:47 | 0h 1m | GUI/Visualization | Fixed IndexError in UDP parser. Packet length validation, frame count from size. |
| 2025-06-13 | 23:24:41 | 23:57:43 | 0h 33m | ESP32 Firmware | Documentation of helpers.h, code style guide. Plain ASCII comments only. |
| 2025-06-14 | 00:03:01 | 00:46:06 | 0h 43m | ESP32 Firmware | Fixed UDP buffer NUL terminator, volatile continuousReading, null pointer in debug. |
| 2025-06-14 | 02:36:18 | 06:41:29 | 4h 5m | ESP32 Firmware | **Major refactoring**: Command dispatch table, modular architecture, NetManager class. |
| 2025-06-14 | 22:31:38 | 23:52:29 | 1h 21m | ESP32 Firmware | SPI optimization analysis. ESP32-C3 single-core confirmed. Memory: RAM 13.1%, IRAM 41.8%. |
| 2025-06-15 | 00:04:13 | 06:06:03 | 6h 2m | ESP32 Firmware | Network keepalive. SPI burst mode. Exact timing loop with vTaskDelayUntil. |
| 2025-06-15 | 06:07:46 | 07:34:32 | 1h 27m | GUI/Visualization | Checkbox plot updates. Safe_get_fs() wrapper. Graph fixes. Delta time subplot. |
| 2025-06-15 | 08:59:22 | 12:46:35 | 3h 47m | GUI/Visualization | Max-hold toggles, 4-subplot with spectrogram. Wavelet scalogram 750x speedup. |
| 2025-06-15 | 10:51:57 | 12:46:35 | 1h 55m | GUI/Visualization | **Wavelet scalogram optimization**: PyWavelets CWT performance issues, 750x speedup achieved with custom Ricker wavelet implementation. |
| 2025-06-16 | 00:00:28 | 02:24:59 | 2h 24m | ESP32 Firmware | **AsyncUDP implementation**: Event-driven, zero CPU idle. Latency 50ms→1ms. |
| 2025-06-16 | 04:42:56 | 06:31:25 | 1h 49m | ESP32 Firmware | Three-tier message parsing: SBA, SYS, USR. Case-insensitive with strcasecmp. |
| 2025-06-16 | 08:33:23 | 08:36:11 | 0h 3m | DSP | EEG signal characteristics. 7-tap FIR safe for gamma band. 250Hz standard for BCI. |
| 2025-06-16 | 09:36:44 | 11:46:29 | 2h 10m | ESP32 Firmware | BLE migration analysis. 7.5ms connection interval, 600-850 kbit/s with 2M PHY. |
| 2025-06-16 | 21:28:58 | 22:57:36 | 1h 29m | DSP | Filter design testing. 7-tap FIR alone insufficient. Cascade FIR+IIR optimal. |
| 2025-06-16 | 22:57:26 | 23:55:56 | 0h 59m | DSP | Filter response visualization. MATLAB-style grids, cascade plot. |
| 2025-06-17 | 00:06:10 | 04:51:02 | 4h 45m | DSP, ESP32 Firmware | **Critical FIR bug fix**: Debugging filter implementations, shift value mismatch (29 vs 31 bits) causing saturation. Filter response visualization with MATLAB-style grids. Accumulator overflow prevention. Peak +7.8dB compensation. |
| 2025-06-17 | 06:07:04 | 09:36:28 | 3h 29m | ESP32 Firmware | Firmware audit. 8-phase plan. Phase 1: Notch filters 50/60/100/120Hz. |
| 2025-06-17 | 11:54:45 | 13:27:06 | 1h 32m | ESP32 Firmware | Knowledge Base system. 10 entries. DSP+ADC must stay merged. |
| 2025-06-17 | 12:02:04 | 12:07:59 | 0h 6m | GUI/Visualization | UDP reassembly for 58-frame packets (3020 bytes). Accumulator with size checking. |
| 2025-06-17 | 14:43:41 | 17:19:48 | 2h 36m | DSP | DSP architecture finalized. 4th-order IIR. Python-generated coefficients, Q2.29. |
| 2025-06-17 | 23:59:58 | 23:59:58 | 0h 1m | ESP32 Firmware | Context preparation for Phase 1 implementation. |
| 2025-06-18 | 00:00:11 | 02:22:53 | 2h 23m | ESP32 Firmware | Phase 1 DSP context transfer to O3 model. Queue management bugs: DSP pointer never advanced, missing bytesWritten. |
| 2025-06-18 | 01:03:56 | 04:39:59 | 3h 36m | ESP32 Firmware, DSP | O3 model failures. Butterworth HPF coefficients corrected. |
| 2025-06-18 | 08:11:17 | 10:19:52 | 2h 9m | ESP32 Firmware | Memory optimization. Static arrays→.bss, const→.rodata. 4th-order notch Q=50-70. |
| 2025-06-18 | 11:56:49 | 18:00:00 | 6h 3m | ESP32 Firmware | **Critical discovery**: ADC and DSP must be merged on single-core ESP32-C3. Queue timing analysis. |
| 2025-06-18 | 17:51:56 | 19:14:10 | 1h 22m | ESP32 Firmware | Inline functions for ADC path. Hardware cycle counter 100x faster than esp_timer. |
| 2025-06-19 | 00:48:54 | 04:01:11 | 3h 13m | DSP | 7-tap FIR optimization. fir_hist[channel][row] layout. Q2.29 format, 448 bytes. |
| 2025-06-19 | 01:55:34 | 01:55:51 | 0h 0m | ESP32 Firmware | Static variables in inline functions share storage - not thread-safe. |
| 2025-06-19 | 03:00:53 | 03:01:14 | 0h 0m | DSP | Coefficient generation C/Python match confirmation. |
| 2025-06-19 | 05:28:00 | 08:00:26 | 2h 32m | ESP32 Firmware | **Crash debugging**: Unaligned uint32_t* access. Use memcpy for timestamps. |
| 2025-06-19 | 05:50:32 | 06:28:20 | 0h 38m | DSP | 50Hz/100Hz noise from floating inputs normal. 0.5Hz cutoff preserves delta waves. |
| 2025-06-19 | 12:48:04 | 18:00:14 | 5h 12m | DSP, ESP32 Firmware | **Major session**: Remove input shifts in DSP, int64 accumulators to prevent overflow. Memory verification showing <4KB DSP RAM usage, 280KB free. Messages library update with clean port separation (5000 control, 5001 data). Fixed filter toggle bug: tk.BooleanVar(root, value=False) critical difference found. |
| 2025-06-19 | 14:51:57 | 16:41:08 | 1h 49m | ESP32 Firmware | Messages library update. Clean port separation: 5000 control, 5001 data. |
| 2025-06-19 | 01:55:34 | 01:55:51 | 0h 1m | ESP32 Firmware | Static variables in inline functions share storage - not thread-safe. |
| 2025-06-19 | 03:00:53 | 03:01:14 | 0h 1m | DSP | Coefficient generation C/Python match confirmation. |
| 2025-06-19 | 19:29:34 | 19:29:37 | 0h 0m | ESP32 Firmware | Multiprocessing print debugging in Windows. |
| 2025-06-20 | 00:13:08 | 03:04:04 | 2h 51m | ESP32 Firmware | UDP drops from large CMD_BUFFER_SIZE. Reduced 512→128 fixes WiFi RAM starvation. |
| 2025-06-20 | 00:56:58 | 01:00:31 | 0h 4m | ESP32 Firmware | June 18 session context confirmation. DSP merged into ADC task. |
| 2025-06-20 | 03:03:41 | 03:42:30 | 0h 39m | ESP32 Firmware | Stack usage <700B confirmed. Phase 1 complete. Phase 2 WiFi provisioning next. |
| 2025-06-20 | 07:20:28 | 09:42:40 | 2h 22m | ESP32 Firmware | Phase 2: WiFi provisioning via AP mode. NVS credential storage, mDNS discovery. |
| 2025-06-20 | 10:20:19 | 12:17:05 | 1h 57m | DSP | C-style coefficient arrays. Butterworth 2nd-order, Q=50 notch, int32_t scaling. |
| 2025-06-20 | 14:39:48 | 21:43:25 | 7h 4m | DSP | 2nd-order DC filter issue. Fixed-point quantization. Multiple cutoff options. |
| 2025-06-21 | 03:45:47 | 16:45:10 | 13h 0m | ESP32 Firmware, DSP | **Firmware**: Timer debugging, CPU frequency 160MHz fixed. **DSP**: Branchless filter implementation, 170μs full chain. |
| 2025-06-21 | 15:35:49 | 17:19:06 | 1h 43m | ESP32 Firmware | Three commands: dccutofffreq, networkfreq, digitalgain. Phase plan update. |
| 2025-06-22 | 05:18:07 | 08:27:39 | 3h 10m | ESP32 Firmware | Debug info preservation. CPU frequency fix 1600MHz→160MHz. Build flags corrected. |
| 2025-06-22 | 09:09:17 | 16:49:01 | 7h 40m | ESP32 Firmware | **Major debugging session**: USB serial config, dual configuration (AP mode + USB serial), auto-detect COM port. Boot detection logic. Fixed USB CDC configuration for lolin_c3_mini board requiring ARDUINO_USB_MODE=1 and ARDUINO_USB_CDC_ON_BOOT=1 flags. |
| 2025-06-23 | 01:31:52 | 08:20:23 | 6h 48m | ESP32 Firmware | Boot detection fix for rapid reset sequences. WiFi driver flash collision issues. while(!Serial) blocking fix for battery-powered operation. Watchdog implementation in NetManager. Store access fault debugging after NVS clear. AP mode fallback implementation. |
| 2025-06-24 | 02:28:35 | 03:27:18 | 0h 59m | ESP32 Firmware | ESP32-C3 EEG context setup and mandatory rules establishment for DSP stability. |
| 2025-06-24 | 02:31:37 | 04:27:46 | 1h 56m | ESP32 Firmware | WiFi watchdog implementation with 2-minute timeout for automatic reconnection. |
| 2025-06-24 | 04:31:00 | 05:07:33 | 0h 37m | ESP32 Firmware | Understanding const member functions and DTR/RTS serial reset behavior. |
| 2025-06-24 | 05:44:37 | 09:28:51 | 3h 44m | ESP32 Firmware | **Major code review**: Debug instrumentation, watchdog timeouts, UDP PCB exhaustion bug identification. |
| 2025-06-24 | 06:22:05 | 06:29:48 | 0h 8m | ESP32 Firmware | Network manager verification, Phase 7 completion confirmed. |
| 2025-06-24 | 08:45:16 | 09:29:55 | 0h 45m | ESP32 Firmware | Build analysis: chip warnings cosmetic, memory usage healthy (13.6% RAM, 57.3% Flash). |
| 2025-06-24 | 11:40:40 | 11:44:04 | 0h 3m | ESP32 Firmware | Russian architecture documentation for three-task FreeRTOS structure. |
| 2025-06-24 | 11:46:03 | 12:42:18 | 0h 56m | ESP32 Firmware | UDP behavior analysis, identified 10-second watchdog as likely stream drop cause. |
| 2025-06-27 | 04:37:42 | 07:41:35 | 3h 4m | GUI/Visualization | **BrainFlow board integration**: Reserved ID 65 (VRCHAT_BOARD). UDP transport, 250Hz, 19 channels. |
| 2025-06-28 | 16:42:14 | 18:30:00 | 1h 48m | DSP | **Blink artifact removal**: ICA, wavelets, template subtraction. 1MΩ bleed resistor solution. |
| 2025-06-29 | 20:57:50 | 22:27:46 | 1h 30m | Analog Front-End, DSP | **Analog**: Bias oscillation from missing DC path. **DSP**: BIAS_SENS register configuration. |
| 2025-07-01 | 20:12:05 | 20:19:07 | 0h 7m | ESP32 Firmware | Boot check reset logic bug. Update function not clearing flag0. |
| 2025-07-01 | 22:33:38 | 23:08:02 | 0h 34m | ESP32 Firmware | Firmware optimization: Static arrays duplicates (90KB wasted). SerialCli overflow bug. |
| 2025-07-02 | 08:08:28 | 08:46:05 | 0h 38m | GUI/Visualization | GUI refactoring: Processing script no longer controls board. subprocess.Popen() launches viewer. |
| 2025-07-04 | 09:13:41 | 18:56:47 | 9h 43m | ESP32 Firmware | NetConfig class implementation. WiFi.onEvent() order fix. getLocalIP() methods. |
| 2025-07-04 | 16:03:14 | 16:09:10 | 0h 6m | DSP | Q-factor analysis. Industry standard Q=30-35 for 50/60Hz. User's Q=50 causing ringing. |
| 2025-07-04 | 21:04:10 | 23:44:46 | 2h 41m | ESP32 Firmware | **C++ frustration session**: Simple DebugLogger without C++ idioms. extern declaration. |
| 2025-07-05 | 00:30:48 | 01:41:33 | 1h 11m | ESP32 Firmware | Python script broken. Namespace "netcfg" vs "netconf". Port values 0 from missing NVS. |
| 2025-07-05 | 17:46:38 | 17:47:19 | 0h 0m | ESP32 Firmware | getLocalIPstr() returning 0.0.0.0. Timing race with GOT_IP event. |
| 2025-07-05 | 22:09:36 | 23:27:40 | 1h 18m | ESP32 Firmware | Serial integration. SerialCli _cfg never initialized. Command queue overflow potential. |
| 2025-07-06 | 22:06:43 | 22:36:30 | 0h 30m | Analog Front-End | **BIAS_SENS register confusion**: SRB2→INxP when CHnSET[3]=1. BIAS_SENSN=0xFF, BIAS_SENSP=0x00. |
| 2025-07-08 | 00:32:50 | 00:32:54 | 0h 0m | ESP32 Firmware | Reduce captive portal font size. Changed 2em→1em in CSS. |
| 2025-07-08 | 11:29:47 | 13:43:39 | 2h 14m | PCB Design | **Space-saving**: 10 electrode pins need RC filters. Double-sided assembly safe. Unused to AVDD. |
| 2025-07-08 | 21:03:35 | 23:45:54 | 2h 42m | GUI/Visualization | **DIY EEG GUI marathon**: Tkinter/matplotlib issues. constrained_layout=True fix. 60fps with after(16). |
| 2025-07-09 | 00:00:01 | 01:43:29 | 1h 43m | GUI/Visualization | GUI SerialManager integration. Fixed StringVar bindings. Button states green/grey. |
| 2025-07-09 | 00:22:27 | 01:00:49 | 0h 38m | GUI/Visualization | Fixed empty SSID/password. Entry widgets not saved as attributes. |
| 2025-07-09 | 12:29:56 | 13:17:27 | 0h 48m | ESP32 Firmware | ESP32 hostname discovery. UDP broadcast simpler than mDNS. Beacon format "ESP-xxxxx". |
| 2025-07-09 | 20:17:35 | 23:38:55 | 3h 21m | GUI/Visualization | UDP backend integration complete. Beacon discovery, IP locking. Color-coded toggles. |
| 2025-07-10 | 00:00:59 | 00:44:07 | 0h 43m | GUI/Visualization | **GUI performance refactor**: Signal processing to multiprocessing.Process. GridSpec 4 rows. |
| 2025-07-10 | 18:59:20 | 19:42:41 | 0h 43m | GUI/Visualization | Signal plot restructuring: 5 views. GridSpec 5 rows equal heights. |
| 2025-07-10 | 19:29:21 | 19:30:54 | 0h 2m | GUI/Visualization | Static analysis signal_backend.py. buf_len stops tracking. Pre-allocated buffers. |
| 2025-07-10 | 21:12:15 | 23:34:45 | 2h 23m | GUI/Visualization | **GUI signal processing**: Fs=250Hz, Record=4s defaults. Symmetric amplitude ±5V. |
| 2025-07-11 | 13:18:14 | 13:18:51 | 0h 1m | ESP32 Firmware, GUI/Visualization | Quick reviews and fixes for various components. |
| 2025-07-11 | 14:45:25 | 14:45:32 | 0h 1m | ESP32 Firmware | Project workflow analysis prompt creation for embedded systems review. |
| 2025-07-11 | 16:02:24 | 17:32:00 | 1h 30m | GUI/Visualization | Project timeline reconstruction from conversation history. Plain ASCII format requirement. |
| 2025-07-11 | 21:19:47 | 21:19:47 | 0h 1m | GUI/Visualization | Project report conciseness request. |
| 2025-07-11 | 21:36:10 | 22:08:31 | 0h 32m | GUI/Visualization | **Critical matplotlib blitting bug**: Background corruption, max-hold not working. Root cause identified as saved background including dynamic plot content. |
| 2025-07-11 | 22:37:53 | 22:41:24 | 0h 4m | ESP32 Firmware | **Static array bug found**: helpers.cpp line 298 - Config_Channels initialization in loop only happens once due to static keyword. |
| 2025-07-12 | 14:44:30 | 16:28:40 | 1h 44m | GUI/Visualization | Duration/time axis bug. Entry using both textvariable AND insert() broke StringVar sync. |
| 2025-07-12 | 23:25:17 | 23:53:44 | 0h 28m | GUI/Visualization | **Performance review**: Serial backend optimal. UDP 50ms timeout. 250Hz×16ch with headroom. |
| 2025-07-13 | 00:15:20 | 00:19:48 | 0h 5m | GUI/Visualization | Speed optimization review. PlotManager extraction already complete. |
| 2025-07-13 | 01:07:25 | 01:35:02 | 0h 28m | GUI/Visualization | **Channel visibility bug**: Checkbox callbacks closure bug. lambda idx=i fix. |
| 2025-07-14 | 08:26:14 | 08:26:15 | 0h 0m | GUI/Visualization | Tkinter bg error fix: ttk widgets don't support bg option, use try-except for fallback. |
| 2025-07-14 | 12:02:07 | 12:22:32 | 0h 20m | ESP32 Firmware | Workflow integration research: Cursor, Windsurf, Continue.dev for AI-assisted coding. PearAI meta-model routing. |
| 2025-07-14 | 13:40:44 | 13:45:21 | 0h 5m | GUI/Visualization | Modern GUI options: Dash/Plotly for simplicity, FastAPI+React for professional, Dear PyGui for GPU acceleration. |
| 2025-07-15 | 01:29:26 | 01:50:41 | 0h 21m | ESP32 Firmware | ESP32-C3 SPI initialization: No hardware flag for "ready", ADS1299 ID register 0x00 returns 0x3E when ready. |
| 2025-07-15 | 09:29:27 | 09:52:30 | 0h 23m | GUI/Visualization | ChatGPT data export analysis. JSON includes timestamps, messages. Export takes 10-20 minutes via email. |
| 2025-07-15 | 10:29:26 | 10:51:16 | 0h 22m | GUI/Visualization | Report generation template created. University-style with timeline, progress, lessons learned sections. |

---

## Summary Statistics (Dec 2024 - July 2025)

### Total Time by Topic
| Topic | Total Duration | Percentage |
|-------|---------------|------------|
| ESP32 Firmware | 132h 50m | 48.0% |
| DSP | 43h 43m | 15.8% |
| GUI/Visualization | 23h 8m | 8.4% |
| PCB Design | 18h 31m | 6.7% |
| Test & Measurement | 18h 16m | 6.6% |
| Raspberry Pi Dev | 13h 32m | 4.9% |
| Analog Front-End | 10h 24m | 3.8% |
| Hardware Selection | 7h 44m | 2.8% |
| Power Management | 5h 25m | 2.0% |
| RF/Wireless | 2h 11m | 0.8% |
| **TOTAL** | **276h 44m** | **100%** |

### Key Work Sessions
- **Longest Single Session**: June 21, 03:45:47-16:45:10 (13h 0m) - Branchless filter implementation
- **Most Productive Day**: June 21, 2025 (14h 43m total)
- **Critical Breakthroughs**: 
  - Jan 25: ADS1299 selected over ADS131M08
  - Jun 11: Atomic CS control implementation
  - Jun 12: DRDY interrupt implementation reduces latency to 10μs
  - Jun 13: Queue size mismatch fix (7h 5m session)
  - Jun 16: AsyncUDP reduces latency 50ms→1ms
  - Jun 18: **THE CRITICAL MERGE** - ADC+DSP tasks merged
  - Jun 19: Filter toggle fix - tk.BooleanVar(root) requirement
  - Jun 21: 13-hour marathon - branchless DSP, 170μs processing
  - Jun 27: BrainFlow VRCHAT_BOARD integration
  - Jul 11: Static array bug found in helpers.cpp line 298

### Work Pattern Analysis
- **Average Session Duration**: 1h 24m
- **Sessions > 5 hours**: 12 (6.4%)
- **Sessions < 10 minutes**: 68 (36.4%)
- **Most Active Month**: June 2025 (113h 12m - 43% of total!)
- **Peak Work Period**: June 18-21 (intense DSP implementation)

### Project Evolution
1. **Dec 2024**: Initial research and component selection
2. **Jan 2025**: Major hardware decisions, ADS1299 selection
3. **Feb 2025**: Raspberry Pi prototyping and validation
4. **Mar 2025**: ESP32 firmware implementation begins
5. **Apr 2025**: Power optimization and testing
6. **May 2025**: Test fixtures, BrainFlow integration starts
7. **Jun 2025**: **Critical month** - DSP implementation, task merging, AsyncUDP
8. **Jul 2025**: GUI development, final optimizations, documentation

### Technical Achievements
- **Real-time Processing**: 170μs for complete DSP chain at 160MHz
- **Channel Count**: 16 channels (dual ADS1299)
- **Sample Rates**: 250-4000 Hz configurable
- **Filter Chain**: FIR sinc³ compensation → DC blocker → Dual notch
- **Network Latency**: Reduced from 50ms to 1ms with AsyncUDP
- **Memory Efficiency**: DSP uses <4KB RAM (280KB available)
- **Power Optimization**: 380mW at 160MHz with WiFi