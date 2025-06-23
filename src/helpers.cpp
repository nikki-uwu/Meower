#include <helpers.h>




// Static context pointer provided by main program
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
extern BootCheck bootCheck;

// Reads and handles incoming serial commands to configure network settings.
// Stores values in RAM until the "apply and reboot" command is received,
// which writes them to flash (Preferences) and restarts the board.
void handleSerialConfig()
{
    // Static storage to accumulate parameters across serial commands
    static String ssid, pass, ip;
    static uint16_t port_ctrl = UDP_PORT_CTRL;    // Default
    static uint16_t port_data = UDP_PORT_PC_DATA; // Default

    // Return immediately if no serial data is available
    if (!Serial.available())
    {
        return;
    }

    // Read the full incoming line up to newline character
    String line = Serial.readStringUntil('\n');
    line.trim(); // remove whitespace

    // Ignore empty lines
    if (line.length() == 0)
    {
        Serial.println("[SERIAL] Empty line");
        return;
    }

    // Match known commands and store values
    if (line.startsWith("set ssid "))
    {
        ssid = line.substring(9);
        Serial.println("OK: ssid set");
    }
    else if (line.startsWith("set pass "))
    {
        pass = line.substring(9);
        Serial.println("OK: pass set");
    }
    else if (line.startsWith("set ip "))
    {
        ip = line.substring(7);
        Serial.println("OK: ip set");
    }
    else if (line.startsWith("set port_ctrl "))
    {
        port_ctrl = line.substring(14).toInt();
        Serial.println("OK: port_ctrl set");
    }
    else if (line.startsWith("set port_data "))
    {
        port_data = line.substring(14).toInt();
        Serial.println("OK: port_data set");
    }
    else if (line == "apply and reboot")
    {
        WiFi.mode(WIFI_MODE_NULL);                 // radio off → safe flash
        delay(100);

        /* ---------- netconf ---------- */
        Preferences prefs;
        prefs.begin("netconf", false);             // WRITE-mode
        prefs.putString ("ssid", ssid);
        prefs.putString ("pass", pass);
        prefs.putString ("ip"  , ip);
        prefs.putUShort("port_ctrl",  port_ctrl);
        prefs.putUShort("port_data",  port_data);
        prefs.end();

        /* ---------- BootMode = NormalMode ---------- */
        Preferences bm;
        if (bm.begin("bootlog", false))            // WRITE-mode (creates if missing)
        {
            bm.putString("BootMode", "NormalMode");
            bm.end();
        }
        else
            Serial.println("[SERIAL] WARN: bootlog namespace not available");

        Serial.println("OK: config saved – rebooting");
        delay(100);
        bootCheck.ESP_REST("serial_cfg_saved");    // soft restart
    }
    else
    {
        Serial.println("ERR: Unknown command");
    }
}