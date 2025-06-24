 #include "helpers.h"

void BootCheck::init()
{
    /* 1)  OPEN in WRITE-mode  →  auto-creates “bootlog” the first time.
            If that still fails (flash full / corrupted) we bail out.   */
    if (!prefs.begin("bootlog", /* readOnly = */ false))
    {
        DBG("[BOOTCHECK] FATAL: cannot open/create bootlog");
        return;                                   // skip fast-boot logic
    }

    /* ---------- history shift (unchanged) ---------- */
    for (int i = 2; i >= 0; --i)
    {
        String   timeKey = "time" + String(i);
        String   flagKey = "flag" + String(i);
        uint32_t t       = prefs.getUInt (timeKey.c_str(), 0);
        String   f       = prefs.getString(flagKey.c_str(), "");
        prefs.putUInt  (("time" + String(i + 1)).c_str(), t);
        prefs.putString(("flag" + String(i + 1)).c_str(), f);
    }

    /* placeholder for this boot (unchanged) */
    prefs.putUInt  ("time0", FAST_WINDOW_MS + 1);
    prefs.putString("flag0", "a");

    /* fast-reboot test (unchanged) */
    uint32_t t1 = prefs.getUInt("time1", FAST_WINDOW_MS + 1);
    uint32_t t2 = prefs.getUInt("time2", FAST_WINDOW_MS + 1);
    uint32_t t3 = prefs.getUInt("time3", FAST_WINDOW_MS + 1);
    String   f1 = prefs.getString("flag1", "");
    String   f2 = prefs.getString("flag2", "");
    String   f3 = prefs.getString("flag3", "");

    if ((t1 + t2 + t3 < FAST_WINDOW_MS) && f1 == "a" && f2 == "a" && f3 == "a")
    {
        /* ----------------------------------------------------------------
            *  reset-storm detected
            *      →  mark “AccessPoint” for the next boot
            *      →  DO NOT wipe netconf (no flash cache panic)
            * ---------------------------------------------------------------- */
        prefs.putString("BootMode", "AccessPoint");
        prefs.end();                      // close cleanly
        DBG("[BOOTCHECK] reset-storm → BootMode=AccessPoint");
        delay(100);
        ESP.restart();                    // warm reboot - never returns
    }

    prefs.putUInt("time0", millis());   // overwrite placeholder
    prefs.end();                        // CLOSE
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