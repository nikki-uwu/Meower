#include "helpers.h"

extern Debugger Debug;

extern volatile uint32_t g_selectSamplingFreq;
extern volatile bool continuousReading;

// Update packet size to maintain ~50 FPS when possible
extern volatile uint32_t g_framesPerPacket;
extern volatile uint32_t g_bytesPerPacket;
extern volatile uint32_t g_udpPacketBytes;

// Setting start signal for continuous mode. Either ON or OFF
void continuous_mode_start_stop(uint8_t on_off)
{
    if (on_off == HIGH) // Start continuous mode
    {
        // Before any start of the continuous we must check board Sample Rate
        // which is at Config 1 which is to read is 0x21
        uint8_t tx_mex[3] = {0x21, 0x00, 0x00};
        uint8_t rx_mes[3] = {0};
        xfer('M', 3u, tx_mex, rx_mes);

        // Store Sampling Rate into global variable for filters
        switch (rx_mes[2] & 0x07)
        {
            case 6: g_selectSamplingFreq = 0; break; //  250 Hz
            case 5: g_selectSamplingFreq = 1; break; //  500 Hz
            case 4: g_selectSamplingFreq = 2; break; // 1000 Hz
            case 3: g_selectSamplingFreq = 3; break; // 2000 Hz
            case 2: g_selectSamplingFreq = 4; break; // 4000 Hz
        }

        // Update adaptive frame packing based on sampling rate
        // Goal: Maintain ~50 packets/second when possible, respect WiFi timing limits
        g_framesPerPacket = FRAMES_PER_PACKET_LUT[g_selectSamplingFreq]; // How many 52-byte frames to pack
        g_bytesPerPacket  = ADC_FULL_FRAME_SIZE * g_framesPerPacket;     // Total ADC data bytes (frames * 52)
        g_udpPacketBytes  = g_bytesPerPacket + Battery_Sense::DATA_SIZE; // Final UDP payload size (ADC + 4-byte battery)

        // Log the configuration change
        // Formula: actual_sample_rate / frames_per_packet = packets_per_second
        // Example: 250 Hz / 5 frames = 50 packets/second
        Debug.log("[ADC] Sampling rate index %u, packing %u frames = %u FPS", 
                    g_selectSamplingFreq, 
                    g_framesPerPacket,
                    (250 << (4 - g_selectSamplingFreq)) / g_framesPerPacket);

        // Turn ON start signal (pull it UP)
        digitalWrite(PIN_START, on_off);

        // Prepare RDATAC message and empty holder for receiving
        uint8_t RDATAC_mes = 0x10;
        xfer('B', 1u, &RDATAC_mes, rx_mes); // Send RDATAC

        // Back to fast SPI clock
        spiTransaction_OFF();
        spiTransaction_ON(SPI_NORMAL_OPERATION_CLOCK);

        // Set continuous mode flag to True
        continuousReading = true;
    }
    else // Otherwise stop
    {
        // Switch SPI clock to command clock speeds, which should be 2 MHz (maybe 4) be default
        spiTransaction_OFF();
        spiTransaction_ON(SPI_COMMAND_CLOCK);

        // Prepare SDATAC message and empty holder for receiving
        uint8_t SDATAC_mes = 0x11;
        uint8_t rx_mes     = 0x00; // just empty message, we don't need any response here

        // After SDATAC message we must wait 4 clocks, but since we have a small
        // delay before and after reading in xfer function we can ignore it
        // Safe SPI transaction (2 MHz for config then back to 16 MHz)
        xfer('B', 1u, &SDATAC_mes, &rx_mes);

        // Turn OFF start signal (pull it DOWN)
        digitalWrite(PIN_START, on_off);

        // Set continuous mode flag to False
        continuousReading = false;
    }
}

void BootCheck::init()
{
    // 1)  OPEN in WRITE-mode -> auto-creates “bootlog” the first time.
    //     If that still fails (flash full / corrupted) we bail out.
    if (!prefs.begin("bootlog", /* readOnly = */ false))
    {
        Debug.print("[BOOTCHECK] FATAL: cannot open/create bootlog");
        return;                                   // skip fast-boot logic
    }

    // shift the last three records: 2->3, 1->2, 0->1
    for (int i = 2; i >= 0; --i)
    {
        prefs.putUInt(("time" + String(i + 1)).c_str(),
                      prefs.getUInt(("time" + String(i)).c_str(), 0));
        prefs.putString(("flag" + String(i + 1)).c_str(),
                        prefs.getString(("flag" + String(i)).c_str(), ""));
    }

    // placeholder for this boot: armed but time not known yet
    prefs.putUInt("time0", FAST_WINDOW_MS + 1);   // >window means "slow"
    prefs.putString("flag0", "a");                // a = armed

    // fast-reboot test
    uint32_t t1 = prefs.getUInt("time1", FAST_WINDOW_MS + 1);
    uint32_t t2 = prefs.getUInt("time2", FAST_WINDOW_MS + 1);
    uint32_t t3 = prefs.getUInt("time3", FAST_WINDOW_MS + 1);
    String   f1 = prefs.getString("flag1", "");
    String   f2 = prefs.getString("flag2", "");
    String   f3 = prefs.getString("flag3", "");

    if (((t1 + t2 + t3) < FAST_WINDOW_MS) &&
        (f1 == "a") && (f2 == "a") && (f3 == "a"))
    {
        /* ----------------------------------------------------------------
            *  reset-storm detected
            *      -  mark “AccessPoint” for the next boot
            *      -  DO NOT wipe netconf (no flash cache panic)
            * ---------------------------------------------------------------- */
        prefs.putString("BootMode", "AccessPoint");
        prefs.end();                      // close cleanly
        Debug.print("[BOOTCHECK] reset-storm -> BootMode = AccessPoint");
        delay(100);
        ESP.restart();                    // warm reboot - never returns
    }

    prefs.putUInt("time0", millis());   // overwrite placeholder
    prefs.end();                        // CLOSE
}

// BootCheck::update  -- call once per loop()
void BootCheck::update()
{
    bool done = false;
    if (done || millis() < 1000) return;

    if (prefs.begin("bootlog", false))
    {
        if (prefs.getString("flag0", "a") == "a")
            prefs.putString("flag0", "b"); // disarm this boot
        prefs.end();
    }
    done = true;
}




// Full ADS1299 reset
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
// Perform a full reset of the ADS1299 chip
//
// CHECK SEQUENCE IN DATASHEET, p.62, Figure 67. Initial Flow at Power-Up
//
// This function ensures a complete reset regardless of the previous pin states.
// ADCs will be reset to default state with sync between them, internal ref ON, 0 gain, 500 FPS and no bias.
// Sequence:
// - Set continuous mode flag to False, because we are performing full reset
// - Setting digital pins to low as it was asked in datasheet before reset
// - Setting PWDN and RESET low and then high to power up the chip (and keep it high, as requested).
// - Waiting for the power-up stabilization time.
// - RESET pulse low->high to reset the digital logic.
// - Waiting for the chip to initialize fully.
// - Get digital levels back to CS off and START off
// - Stop Continuous mode sending SDATAC message
// - Configure master to have reference signal inside on Config_3 to 0xE0
// - Configure master to send reference clock to slave and then slave to listen to it Config_1
// - Now slave should be fully on and we can configure internal reference Config_3 t0 0xE0 for both master and slave AGAIN and slave will behave as master
// - Setup testing signals to be generated internaly, to have 3.75 mV amplitude and period of 1 second
// - Setup all channels to be shorted to testing signal, with 0 gain, no SRB for any of them
void ads1299_full_reset()
{
    // We will use digitalWrite instead of WRITE_PERI_REG here since timings are not important.

    // Make sure continuous Mode is OFF, because we are doing full reset
    continuous_mode_start_stop(LOW);

    // Based on datasheet all CS and START (it says all digital signals) should go LOW
    // Page 62, check diagram
    digitalWrite(PIN_CS_MASTER, LOW);
    digitalWrite(PIN_CS_SLAVE , LOW);
    digitalWrite(PIN_START    , LOW);

    // Set PWDN and RESET low to fully stop ADCs
    digitalWrite(PIN_PWDN , LOW);
    digitalWrite(PIN_RESET, LOW);

    // Wait 150 ms for power-down stabilization
    delay(150); 

    // Set PWDN and RESET high to ensure the chip is powered up and remains so
    digitalWrite(PIN_PWDN , HIGH);
    digitalWrite(PIN_RESET, HIGH);

    // Wait 150 ms for power-up stabilization (datasheet says 2^18 of clocks which is around 132 ms, page 70, 11.1 Power-Up Sequencing)
    delay(150);

    // Transmit RESET pulse with length exceeding the minimum 2 clock cycles (page 70, 11.1 Power-Up Sequencing)
    digitalWrite(PIN_RESET, LOW);
    delayMicroseconds(10); // 10 us
    digitalWrite(PIN_RESET, HIGH);

    // Wait 1 ms exceeding the minimum 18 clock cycles (page 70, 11.1 Power-Up Sequencing)
    delay(1);

    // Pull CS back, but keep START LOW
    digitalWrite(PIN_CS_MASTER, HIGH);
    digitalWrite(PIN_CS_SLAVE , HIGH);
    digitalWrite(PIN_START    , LOW ); // this one is already LOW, but let's make it safe

    // Stop continuous data mode (SDATAC)
    // Datasheet - 9.5.3 SPI command definitions, p.40.
    {
        uint8_t SDATAC_mes = 0x11;
        uint8_t rx_mes     = 0; // just empty message, we don't need any response here
        xfer('B', 1u, &SDATAC_mes, &rx_mes);
    }

    // CONFIG 3
    // We are using internal reference buffer so we have to set it right away becase by default
    // config is 0x60 abd it means turn off internal reference buffer
    // Configuration 3 - Reference and bias
    // bit 7                | 6        | 5        | 4         | 3                | 2                  | 1                      | 0 read only
    // use Power ref buffer | Always 1 | Always 1 | BIAS meas | BIAS ref ext/int | BIAS power Down/UP | BIAS sence lead OFF/ON | LEAD OFF status
    //              76543210
    //              X11YZMKR
    // Config_3 = 0b11100000; 0xE0
    {
        const uint8_t Master_conf_3[3u] = {0x43, 0x00, 0xE0};
        uint8_t              rx_mes[3u] = {0}; // just empty message, we don't need any response here
        xfer('B', 3u, Master_conf_3, rx_mes);
    }

    // CONFIG 1
    // Then we need to setup up clock for slave and update reference signal again, otherwise
    // slave is in different state comparing to master
    // Configuration 1 - Daisy-chain, reference clock, sample rate
    // bit 7        | 6                  | 5                 | 4        | 3        | 2   | 1   | 0
    // use Always 1 | Daisy-chain enable | Clock output mode | always 1 | always 0 | DR2 | DR1 | DR0
    //                   76543210
    //                   1XY10ZZZ
    // Master_conf_1 = 0b10110110; # Daisy ON, Clock OUT ON,  250 SPS
    // Slave_conf_1  = 0b10010110; # Daisy ON, Clock OUT OFF, 250 SPS
    {
        // Master config
        const uint8_t Master_conf_1[3u] = {0x41, 0x00, 0xB6};
        uint8_t              rx_mes[3u] = {0}; // just empty message, we don't need any response here
        xfer('M', 3u, Master_conf_1, rx_mes);

        // Slave config
        const uint8_t Slave_conf_1[3u] = {0x41, 0x00, 0x96};
        xfer('S', 3u, Slave_conf_1, rx_mes);

        // CRITICAL: Wait for clock sync between master and slave
        delay(50);  // Give slave time to lock onto master's clock

        // Set reference signal to base again, since slave was in whatever state so
        // after this config 3 messages they will be in similar modes again
        const uint8_t Config_3[3u] = {0x43, 0x00, 0xE0};
        xfer('B', 3u, Config_3, rx_mes);
    }

    // CONFIG 2
    // Next I want to preset testing signals parameters - FOR BOTH ADCs
    // Test signal are generated internaly
    // Test signal amplitude 3.75 mV (2 × -(VREFP - VREFN) / 2400, Vwhere on this board VREFP is +4.5V and VREFN is 0 V)
    // Period of miander is 1 second
    // bit 7        | 6        | 5        | 4                   | 3        | 2                  | 1           0
    // use Always 1 | Always 1 | Always 0 | Test source ext/int | Always 0 | Test sig amplitude | Test sig freq
    //              76543210
    //              110X0YZZ
    //              11010101 Signal is gen internally, amplitude twice more than usual, pulses with 1 s period
    // Config_2 = 0b11010100
    {
        const uint8_t Config_2[3u]      = {0x42, 0x00, 0xD4};
        uint8_t              rx_mes[3u] = {0}; // just empty message, we don't need any response here
        xfer('B', 3u, Config_2, rx_mes);
    }

    // CHANNELS CONFIG
    // Set all channels to normal mode (both positive and negative are needed for each channel) with 0 gain
    // Channels settings
    // bit 7                 | 6 5 4 | 3                | 2 1 0
    // use Power down On/Off | GAIN  | SRB2 open/closed | Channel input
    //                  76543210
    // Channel_conf = 0b00000101
    // We have 8 channels in each ADC and we assign default settings to all of them in pairs
    for (uint8_t ind = 0; ind < 8u; ind++)
    {
        const uint8_t Config_Channels[3u] = { static_cast<uint8_t>(0x45 + ind), 0x00, 0x05 };
        uint8_t              rx_mes[3u]   = {0}; // just empty message, we don't need any response here
        xfer('B', 3u, Config_Channels, rx_mes);

        // wait for 1 ms
        delay(1);
    }
}

void BCI_preset()
{
    // Make sure continuous Mode is OFF, because we are doing BCI preset
    continuous_mode_start_stop(LOW);

    // CHANNELS CONFIG
    // Set all channels to SRB2 mode (all positive are short to eachother) with 2 gain
    // Channels settings
    // bit 7                 | 6 5 4 | 3                | 2 1 0
    // use Power down On/Off | GAIN  | SRB2 open/closed | Channel input
    //                  76543210
    // Channel_conf = 0b00011000 (0x28)
    // We have 8 channels in each ADC and we assign default settings to all of them in pairs
    for (uint8_t ind = 0; ind < 8u; ind++)
    {
        const uint8_t Config_Channels[3u] = { static_cast<uint8_t>(0x45 + ind), 0x00, 0x08 };
        uint8_t              rx_mes[3u]   = {0}; // just empty message, we don't need any response here
        xfer('B', 3u, Config_Channels, rx_mes);

        // wait for 1 ms
        delay(1);
    }

    // CONFIG 3
    // We are using internal reference buffer so we have to set it right away becase by default
    // config is 0x60 abd it means turn off internal reference buffer
    // Configuration 3 - Reference and bias
    // bit 7                | 6        | 5        | 4         | 3                | 2                  | 1                      | 0 read only
    // use Power ref buffer | Always 1 | Always 1 | BIAS meas | BIAS ref ext/int | BIAS power Down/UP | BIAS sence lead OFF/ON | LEAD OFF status
    //              76543210
    //              X11YZMKR
    // Config_3 = 0b11100000; 0xE0
    {
        const uint8_t Master_conf_3[3u] = {0x43, 0x00, 0xEC};
        uint8_t              rx_mes[3u]        = {0}; // just empty message, we don't need any response here
        xfer('M', 3u, Master_conf_3, rx_mes);

        const uint8_t Slave_conf_3[3u] = {0x43, 0x00, 0xE8};
        xfer('S', 3u, Slave_conf_3, rx_mes);
    }
}

// The ADS1299 ID register (0x00) is always accessible immediately after power-up, even before any other configuration.
void wait_until_ads1299_is_ready()
{
   // Make sure continuous mode is OFF before checking ID - do this once outside loop
   continuous_mode_start_stop(LOW);

   // Debug counter for tracking attempts
   uint32_t attempt_count = 0;

   // Loop until ADS1299 responds with correct device ID
   // This ensures the ADC is fully powered up and ready for configuration
   while (true)
   {
       attempt_count++;
       
       // Read Device ID register (address 0x00) from master ADC
       // Command format: RREG address=0x00, read 1 register
       uint8_t tx_mes[3] = {0x20, 0x00, 0x00};  // RREG command for register 0x00
       uint8_t rx_mes[3] = {0x00, 0x00, 0x00};  // Response buffer
       
       // Try to read from master ADC
       xfer('M', 3u, tx_mes, rx_mes);

       Debug.log("[ADS1299] Attempt %lu: ID response = 0x%02X (expected 0x3E)", attempt_count, rx_mes[2]);

       // Check if we got the correct ADS1299 device ID (0x3E)
       if (rx_mes[2] == 0x3E)
       {
           Debug.log("[ADS1299] Ready after %lu attempts", attempt_count);
           // ADS1299 is ready - exit the loop
           break;
       }

       // Small delay before next attempt to avoid flooding the bus
       delay(10); // 10 ms between attempts
   }
}


NetConfig::NetConfig()
{
    // Default network settings
    // Note: PC IP is not stored - it's auto-discovered at runtime
    s_.ssid      = "ESP32";
    s_.password  = "esp32-setup";
    s_.portCtrl  = UDP_PORT_CTRL;
    s_.portData  = UDP_PORT_PC_DATA;
}

// ---------- NVS I/O ----------
bool NetConfig::load()
{
    Preferences p;
    if (!p.begin(NS, /*read-only=*/true)) return false;

    s_.ssid      = p.getString("ssid",  s_.ssid);
    s_.password  = p.getString("pass",  s_.password);
    s_.portCtrl  = p.getUShort("port_ctrl", s_.portCtrl);
    s_.portData  = p.getUShort("port_data", s_.portData);
    p.end();
    return true;
}

bool NetConfig::save() const
{
    Preferences p;
    if (!p.begin(NS, /*read-write=*/false)) return false;

    p.putString ("ssid",       s_.ssid);
    p.putString ("pass",       s_.password);
    p.putUShort ("port_ctrl",  s_.portCtrl);
    p.putUShort ("port_data",  s_.portData);
    p.end();
    return true;
}



/**
 * Read a single register from both ADS1299 chips in daisy-chain configuration
 * 
 * In daisy-chain mode, register reads work differently than single-chip mode:
 * 
 * 1. We MUST chip-select BOTH ADCs (master AND slave) simultaneously
 * 2. Both ADCs receive the read command and queue their responses
 * 3. Data flows through the chain: Slave → Master → ESP32
 * 4. We receive responses sequentially, just like ADC samples
 * 
 * Data Flow Timing:
 * ┌─────────────────────────────────────────────────────────────────┐
 * │                    30-byte SPI Transaction                      │
 * ├─────────────────────────────────────────────────────────────────┤
 * │         Master Response         │        Slave Response         │
 * │            27 bytes             │           27 bytes            │
 * │  (but only byte 3 matters)      │   (but only byte 30 matters)  │
 * └─────────────────────────────────────────────────────────────────┘
 * 
 * Each 27-byte response contains:
 * - Bytes 1- 2: Command echo and length (ignored)  
 * - Byte     3: The actual register value we want
 * - Bytes 4-27: Channel data (not relevant for register reads)
 * 
 * Why 30 bytes? We only need the first 3 bytes from each ADC:
 * - Master register value at position 3
 * - Slave register value at position 30 (27 + 3)
 * 
 * @param reg_addr The register address to read (0x00 - 0x17)
 * @return Structure containing both master and slave register values
 */
RegValues read_Register_Daisy(uint8_t reg_addr)
{
    // Build RREG command: 0x20 OR'd with register address
    // This tells ADS1299 to read starting at reg_addr
    uint8_t tx[30] = {0};
    uint8_t rx[30] = {0};
    
    tx[0] = 0x20 | reg_addr;  // RREG command + register address
    tx[1] = 0x00;             // Read 1 register (offset = 0)
    // tx[2-29] remain 0x00 - just clock pulses to retrieve data
    
    // CRITICAL: Target MUST be 'B' (both) in daisy-chain mode!
    // If we only select one chip, the chain breaks and we get garbage
    xfer('B', 30, tx, rx);

    // Parse the response:
    // In daisy-chain, data arrives in this order:
    // [Master 27 bytes][Slave 27 bytes]
    // But for register reads, only specific bytes matter:
    
    RegValues result;
    result.master_reg_byte = rx[ 2]; // Master's register value (3rd byte)
    result.slave_reg_byte  = rx[29]; // Slave's register value (30th byte)
    
    // Why these positions?
    // Master: Sends [cmd_echo][length][REGISTER_VALUE][24 bytes of zeros]
    //         Position: [0][1][2][3-26]
    // Slave: Same pattern but starts at byte 27
    //        Position: [27][28][29][30-53]
    
    return result;
}