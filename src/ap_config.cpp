#include "ap_config.h"


static WebServer server(80);
static Preferences prefs;
extern BootCheck bootCheck;

static const char* AP_SSID = "EEG-SETUP";
static const char* AP_PASS = "password";

static const char* htmlForm = R"rawliteral(
<!DOCTYPE html>
<html>
  <body>
    <h2>WiFi & UDP Setup</h2>
    <form method="POST" action="/save">
      SSID:<br><input name="ssid"><br>
      Password:<br><input name="pass" type="password"><br>
      PC IP:<br><input name="ip"><br>
      Ctrl Port:<br><input name="port_ctrl" type="number" value="5000"><br>
      Data Port:<br><input name="port_data" type="number" value="5001"><br>
      <br><input type="submit" value="Save and Restart">
    </form>
  </body>
</html>
)rawliteral";

void handleRoot()
{
    int n = WiFi.scanNetworks();
    String options = "";

    for (int i = 0; i < n; i++)
    {
        String ssid = WiFi.SSID(i);
        ssid.replace("\"", "\\\""); // escape quotes
        options += "<div onclick='selectSSID(\"" + ssid + "\")' "
                   "style='cursor:pointer;color:blue;text-decoration:underline;'>"
                   + ssid + "</div>\n";
    }

    String page = String(R"rawliteral(
    <!DOCTYPE html>
    <html>
    <head>
        <style>
        body {
            font-size: 2em;
            font-family: sans-serif;
            padding: 20px;
        }
        input {
            font-size: 1em;
            width: 100%;
            padding: 10px;
            margin: 10px 0;
        }
        div.network {
            cursor: pointer;
            color: blue;
            text-decoration: underline;
            margin: 5px 0;
        }
        input[type="submit"] {
            background-color: #4CAF50;
            color: white;
            border: none;
            padding: 15px;
            width: 100%;
            font-size: 1em;
        }
        </style>
    </head>
    <body>
        <h2>WiFi & UDP Setup</h2>
        <form method="POST" action="/save">
        SSID:<br><input id="ssid" name="ssid"><br>
        <div><b>Tap to select a network:</b><br>)rawliteral") + options + R"rawliteral(</div><br>
        Password:<br><input name="pass" type="password"><br>
        PC IP:<br><input name="ip"><br>
        Ctrl Port:<br><input name="port_ctrl" type="number" value="5000"><br>
        Data Port:<br><input name="port_data" type="number" value="5001"><br>
        <input type="submit" value="Save and Restart">
        </form>

        <script>
        function selectSSID(name) {
            document.getElementById("ssid").value = name;
        }
        </script>
    </body>
    </html>
    )rawliteral";

    server.send(200, "text/html", page);
}


void handleSave()
{
    // Disable Wi-Fi before committing to flash - prevents cache collision
    WiFi.mode(WIFI_MODE_NULL);
    delay(100);

    // ---------- store network credentials ----------  (unchanged)
    prefs.begin("netconf", false);
    prefs.putString ("ssid",      server.arg("ssid"));
    prefs.putString ("pass",      server.arg("pass"));
    prefs.putString ("ip",        server.arg("ip"));
    prefs.putUShort("port_ctrl",  server.arg("port_ctrl").toInt());
    prefs.putUShort("port_data",  server.arg("port_data").toInt());
    prefs.end();

    /* ---------- BootMode = NormalMode ---------- */
    Preferences bm;
    if (bm.begin("bootlog", false))                // WRITE-mode (creates if missing)
    {
        bm.putString("BootMode", "NormalMode");  // ********** NEW LINE **********
    }
    else
        Serial.println("[AP] WARN: bootlog namespace not available");

    server.send(200, "text/plain", "Saved - rebooting…");
    delay(100);
    bootCheck.ESP_REST("ap_cfg_saved");
}


// ──────────────────────────────────────────────────────────────────────────────
//  maybeEnterAPMode()
//      • Called ONCE, near the top of setup().
//      • Runs the captive portal unless BootMode == "NormalMode".
//      • Ignores the presence or absence of an SSID - the flag is the ONLY
//        authority for the operating mode.
// ──────────────────────────────────────────────────────────────────────────────
// ──────────────────────────────────────────────────────────────────────────────
//  maybeEnterAPMode()   -  DEBUG-INSTRUMENTED VERSION
//
//  ─ Flow ─
//     1.  Reads BootMode from NVS  →  prints the exact value / error
//     2.  Continues to STA only when BootMode == "NormalMode"
//     3.  Otherwise launches the captive portal and BLOCKS forever.
//
//  Every decisive step emits a Serial message so you can see precisely
//  where the firmware stalls or reboots.
// ──────────────────────────────────────────────────────────────────────────────
void maybeEnterAPMode()
{
    Serial.println("DBG: >>> maybeEnterAPMode()");

    /* 1 ──────────────────────────────────────────────────────────────────── */
    Serial.println("DBG: opening prefs ‘bootlog’ (write-mode, auto-create)");
    Preferences bm;
    if (!bm.begin("bootlog", /*readOnly=*/false))
    {
        Serial.println("ERR: NVS open failed - forcing AccessPoint");
    }
    String mode = bm.getString("BootMode", "<missing>");
    Serial.print  ("DBG: BootMode read = ‘");
    Serial.print  (mode);
    Serial.println("’");
    bm.end();

    /* 2 ──────────────────────────────────────────────────────────────────── */
    if (mode == "NormalMode")
    {
        Serial.println("DBG: NormalMode - skip portal, continue with STA");
        return;                                           // ← exit function
    }

    /* 3 ──────────────────────────────────────────────────────────────────── */
    Serial.println("DBG: Launching Access-Point portal");

    WiFi.disconnect(true, true);
    delay(100);

    Serial.println("DBG: WiFi.mode(AP)");
    WiFi.mode(WIFI_MODE_AP);
    delay(100);

    bool ap_ok = WiFi.softAP(AP_SSID, AP_PASS, 1);
    if (ap_ok)
        Serial.printf("DBG: softAP OK  - SSID: %s\n", AP_SSID);
    else
        Serial.println ("ERR: softAP FAILED");

    IPAddress ip = WiFi.softAPIP();
    Serial.print("DBG: AP IP address = ");
    Serial.println(ip);

    Serial.println("DBG: starting WebServer routes");
    server.on("/",     HTTP_GET , handleRoot);
    server.on("/save", HTTP_POST, handleSave);
    server.begin();
    Serial.println("DBG: Captive portal ready at http://192.168.4.1/");

    static Blinker led(PIN_LED, 100, 1000);   // slow heartbeat

    Serial.println("DBG: entering infinite portal loop");
    while (true)
    {
        server.handleClient();
        handleSerialConfig();
        led.update();

        /* extra heartbeat */
        static uint32_t last = 0;
        if (millis() - last > 5000)
        {
            Serial.printf("DBG: portal alive - free heap %u B\n", esp_get_free_heap_size());
            last = millis();
        }
        delay(2);
    }
}
