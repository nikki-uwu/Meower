#include "helpers.h"

void BootCheck::init()
{
    // 1)  OPEN in WRITE-mode -> auto-creates “bootlog” the first time.
    //     If that still fails (flash full / corrupted) we bail out.
    if (!prefs.begin("bootlog", /* readOnly = */ false))
    {
        DBG("[BOOTCHECK] FATAL: cannot open/create bootlog");
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
        DBG("[BOOTCHECK] reset-storm -> BootMode = AccessPoint");
        delay(100);
        ESP.restart();                    // warm reboot - never returns
    }

    prefs.putUInt("time0", millis());   // overwrite placeholder
    prefs.end();                        // CLOSE
}

// BootCheck::update  -- call once per loop()
void BootCheck::update()
{
    static bool done = false;
    if (done || millis() < FAST_WINDOW_MS) return;

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
// - Reset SPI clock to 2 MHz. We will reset chip only at 2 MHz clock, because it works unstable if we forse it to work at 8 right away. So we full reset first with low speed and only then push 4 Mhz or higher
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
    // ALSO, we do not care about proper procidure with messages, since we are pulling RESET and POWER DOWN pins LOW,
    // fully reseting ADCs. so we can just set continuous mode to false
    continuousReading = false; 

    // Stop SPI if it was running and start again at 2 MHz clock. Then we will stop it again and set working speed
    spiTransaction_OFF();               // stop SPI
    spiTransaction_ON(SPI_RESET_CLOCK); // start at 2 MHz

    // Based on datasheet all CS and START (it says all digital signals) should go LOW
    // Page 62, check diagramm
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
    digitalWrite(PIN_START    , LOW ); // this one is already LOW, but lets make it safe

    // Stop continuous data mode (SDATAC)
    // Datasheet - 9.5.3 SPI command definitions, p.40.
    {
        uint8_t SDATAC_mes = 0x11;
        uint8_t rx_mes     = 0; // just empty message, we do need any response here
        xfer('B', 1u, &SDATAC_mes, &rx_mes);
    }

    // We are using internal reference buffer so we have to set it right away becase by default
    // config is 0x60 abd it means turn off internal reference buffer
    // Configuration 3 - Reference and bias
    // bit 7                | 6        | 5        | 4         | 3                | 2                  | 1                      | 0 read only
    // use Power ref buffer | Always 1 | Always 1 | BIAS meas | BIAS ref ext/int | BIAS power Down/UP | BIAS sence lead OFF/ON | LEAD OFF status
    //              76543210
    //              X11YZMKR
    // Config_3 = 0b11100000; 0xE0
    {
        static const uint8_t Master_conf_3[3u] = {0x43, 0x00, 0xE0};
        uint8_t              rx_mes[3u]        = {0}; // just empty message, we do need any response here
        xfer('B', 3u, Master_conf_3, rx_mes);
    }

    // Then we need to setup up clock for slave and update reference signal again, otherwise
    // slave is in different state comparing to master
    // Configuration 1 - Daisy-chain, reference clock, sample rate
    // bit 7        | 6                  | 5                 | 4        | 3        | 2   | 1   | 0
    // use Always 1 | Daisy-chain enable | Clock output mode | always 1 | always 0 | DR2 | DR1 | DR0
    //                   76543210
    //                   1XY10ZZZ
    // Master_conf_1 = 0b10110101; # Daisy ON, Clock OUT ON,  500 SPS - i moved it to 500 Hz to get better frequency response in range [0 - 100 Hz]. The reason is sigma delta adc 
    // Slave_conf_1  = 0b10010101; # Daisy ON, Clock OUT OFF, 500 SPS
    {
        // Master config
        static const uint8_t Master_conf_1[3u] = {0x41, 0x00, 0xB6};
        uint8_t              rx_mes[3u]        = {0}; // just empty message, we do need any response here
        xfer('M', 3u, Master_conf_1, rx_mes);

        // Slave config
        static const uint8_t Slave_conf_1[3u] = {0x41, 0x00, 0x96};
        xfer('S', 3u, Slave_conf_1, rx_mes);

        // Set reference signal to base again, since slave was in what ever state so
        // after this config 3 messages they will be in similar modes again
        static const uint8_t Config_3[3u] = {0x43, 0x00, 0xE0};
        xfer('B', 3u, Config_3, rx_mes);
    }

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
        static const uint8_t Config_2[3u] = {0x42, 0x00, 0xD4};
        uint8_t              rx_mes[3u]   = {0}; // just empty message, we do need any response here
        xfer('B', 3u, Config_2, rx_mes);
    }

    // Set all channels to normal mode (both positive and negative are needed for each channel) with 0 gain
    // Channels settings
    // bit 7                 | 6 5 4 | 3                | 2 1 0
    // use Power down On/Off | GAIN  | SRB2 open/closed | Channel input
    //                  76543210
    // Channel_conf = 0b00000101
    // We have 8 channels in each ADC and we assign default settings to all of them in pairs
    for (uint8_t ind = 0; ind < 8u; ind++)
    {
        static const uint8_t Config_Channels[3u] = { static_cast<uint8_t>(0x45 + ind), 0x00, 0x05 };
        uint8_t              rx_mes[3u]          = {0}; // just empty message, we do need any response here
        xfer('B', 3u, Config_Channels, rx_mes);

        // wait for 1 ms
        delay(1);
    }

    // Reconfigure SPI frequency to working one
    spiTransaction_OFF();                          // stop SPI
    spiTransaction_ON(SPI_NORMAL_OPERATION_CLOCK); // start and normal working frequency (most stable i've seen is 8 MHz)
}


// // Static context pointer provided by main program
// // ---------------------------------------------------------------------------------------------------------------------------------
// // ---------------------------------------------------------------------------------------------------------------------------------
// extern BootCheck bootCheck;

// // Reads and handles incoming serial commands to configure network settings.
// // Stores values in RAM until the "apply and reboot" command is received,
// // which writes them to flash (Preferences) and restarts the board.
// void handleSerialConfig()
// {
//     // Static storage to accumulate parameters across serial commands
//     static String ssid, pass, ip;
//     static uint16_t port_ctrl = UDP_PORT_CTRL;    // Default
//     static uint16_t port_data = UDP_PORT_PC_DATA; // Default

//     // Return immediately if no serial data is available
//     if (!Serial.available())
//     {
//         return;
//     }

//     // Read the full incoming line up to newline character
//     String line = Serial.readStringUntil('\n');
//     line.trim(); // remove whitespace

//     // Ignore empty lines
//     if (line.length() == 0)
//     {
//         Serial.println("[SERIAL] Empty line");
//         return;
//     }

//     // Match known commands and store values
//     if (line.startsWith("set ssid "))
//     {
//         ssid = line.substring(9);
//         Serial.println("OK: ssid set");
//     }
//     else if (line.startsWith("set pass "))
//     {
//         pass = line.substring(9);
//         Serial.println("OK: pass set");
//     }
//     else if (line.startsWith("set ip "))
//     {
//         ip = line.substring(7);
//         Serial.println("OK: ip set");
//     }
//     else if (line.startsWith("set port_ctrl "))
//     {
//         port_ctrl = line.substring(14).toInt();
//         Serial.println("OK: port_ctrl set");
//     }
//     else if (line.startsWith("set port_data "))
//     {
//         port_data = line.substring(14).toInt();
//         Serial.println("OK: port_data set");
//     }
//     else if (line == "apply and reboot")
//     {
//         WiFi.mode(WIFI_MODE_NULL);                 // radio off → safe flash
//         delay(100);

//         /* ---------- netconf ---------- */
//         Preferences prefs;
//         prefs.begin("netconf", false);             // WRITE-mode
//         prefs.putString ("ssid", ssid);
//         prefs.putString ("pass", pass);
//         prefs.putString ("ip"  , ip);
//         prefs.putUShort("port_ctrl",  port_ctrl);
//         prefs.putUShort("port_data",  port_data);
//         prefs.end();

//         /* ---------- BootMode = NormalMode ---------- */
//         Preferences bm;
//         if (bm.begin("bootlog", false))            // WRITE-mode (creates if missing)
//         {
//             bm.putString("BootMode", "NormalMode");
//             bm.end();
//         }
//         else
//             Serial.println("[SERIAL] WARN: bootlog namespace not available");

//         Serial.println("OK: config saved - rebooting");
//         delay(100);
//         bootCheck.ESP_REST("serial_cfg_saved");    // soft restart
//     }
//     else
//     {
//         Serial.println("ERR: Unknown command");
//     }
// }