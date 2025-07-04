#include "ap_config.h"

// ------------------------------------------------------------------
// Globals
// ------------------------------------------------------------------
static WebServer   server(80);      // captive-portal HTTP server
static Preferences prefs;           // netconf NVS handle
extern BootCheck   bootCheck;       // from helpers.cpp
extern SerialCli   CLI;             // UART CLI
extern Debugger    Debug; 

static const char* AP_SSID = "EEG-SETUP";
static const char* AP_PASS = "password";

// ------------------------------------------------------------------
// handleRoot() - dynamic HTML with live port numbers
// ------------------------------------------------------------------
void handleRoot()
{
    // Scan Wi-Fi for convenience list
    int n = WiFi.scanNetworks();
    String options;
    for (int i = 0; i < n; i++)
    {
        String ssid = WiFi.SSID(i);
        ssid.replace("\"", "\\\""); // escape quotes
        options += "<div onclick='selectSSID(\"" + ssid + "\")' "
                   "style='cursor:pointer;color:blue;text-decoration:underline;'>"
                   + ssid + "</div>\n";
    }

    // Read current ports so the form shows real values
    uint16_t portCtrl, portData;
    if (prefs.begin("netconf", /*readOnly=*/true))
    {
        portCtrl = prefs.getUShort("port_ctrl", UDP_PORT_CTRL);
        portData = prefs.getUShort("port_data", UDP_PORT_PC_DATA);
        prefs.end();
    }
    else                                   // namespace missing → defaults
    {
        portCtrl = UDP_PORT_CTRL;
        portData = UDP_PORT_PC_DATA;
    }


    // Assemble HTML
    String page = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
<style>
body { font-size:2em; font-family:sans-serif; padding:20px; }
input { font-size:1em; width:100%; padding:10px; margin:10px 0; }
div.network { cursor:pointer; color:blue; text-decoration:underline; margin:5px 0; }
input[type="submit"] { background:#4CAF50; color:#fff; border:none; padding:15px; width:100%; font-size:1em; }
</style>
</head>
<body>
<h2>WiFi & UDP Setup</h2>
<form method="POST" action="/save">
SSID:<br><input id="ssid" name="ssid"><br>
<div><b>Tap to select a network:</b><br>
)rawliteral";

    page += options;
    page += R"rawliteral(
</div><br>
Password:<br><input name="pass" type="password"><br>
PC IP:<br><input name="ip"><br>
Ctrl Port:<br><input name="port_ctrl" type="number" value=")rawliteral";
    page += String(portCtrl);
    page += R"rawliteral("><br>
Data Port:<br><input name="port_data" type="number" value=")rawliteral";
    page += String(portData);
    page += R"rawliteral("><br>
<input type="submit" value="Save and Restart">
</form>
<script>
function selectSSID(name){ document.getElementById("ssid").value=name; }
</script>
</body>
</html>
)rawliteral";

    server.send(200, "text/html", page);
}

// ------------------------------------------------------------------
// handleSave() - store settings and reboot
// ------------------------------------------------------------------
void handleSave()
{
    WiFi.mode(WIFI_MODE_NULL);               // radio off for safe NVS
    delay(100);

    prefs.begin("netconf", false);
    prefs.putString ("ssid",      server.arg("ssid"));
    prefs.putString ("pass",      server.arg("pass"));
    prefs.putString ("ip",        server.arg("ip"));

    uint16_t pc = server.arg("port_ctrl").toInt();
    uint16_t pd = server.arg("port_data").toInt();
    if (pc == 0) pc = UDP_PORT_CTRL;        // fall back to defaults
    if (pd == 0) pd = UDP_PORT_PC_DATA;
    prefs.putUShort("port_ctrl", pc);
    prefs.putUShort("port_data", pd);
    prefs.end();

    Preferences bm;
    if (bm.begin("bootlog", false))
    {
        bm.putString("BootMode", "NormalMode");
        bm.end();
    }
    else
        Debug.print("[AP] WARN: bootlog namespace not available");

    server.send(200, "text/plain", "Saved - rebooting...");
    delay(100);
    bootCheck.ESP_REST("ap_cfg_saved");
}

// ------------------------------------------------------------------
// maybeEnterAPMode() - run captive portal unless BootMode == NormalMode
// ------------------------------------------------------------------
void maybeEnterAPMode()
{
    Debug.print("DBG: >>> maybeEnterAPMode()");

    Preferences bm;
    bm.begin("bootlog", false);                      // R/W auto-create
    String mode = bm.getString("BootMode", "<missing>");
    bm.end();

    Debug.log("DBG: BootMode = %s", mode.c_str());

    if (mode == "NormalMode")
    {
        Debug.print("DBG: NormalMode - continue with STA");
        return;
    }

    // Launch portal
    Debug.print("DBG: Launching Access Point portal");
    WiFi.disconnect(true, true);
    delay(100);
    WiFi.mode(WIFI_MODE_AP);
    delay(100);

    bool ok = WiFi.softAP(AP_SSID, AP_PASS, 1);
    if (ok) Debug.log("DBG: softAP OK - SSID: %s", AP_SSID);
    else    Debug.print("ERR: softAP FAILED");

    IPAddress ip = WiFi.softAPIP();
    Debug.log("DBG: AP IP address = %s", ip.toString().c_str());

    server.on("/",     HTTP_GET , handleRoot);
    server.on("/save", HTTP_POST, handleSave);
    server.begin();
    Debug.print("DBG: Captive portal ready at http://192.168.4.1/");

    static Blinker led(PIN_LED, 100, 1000); // slow heartbeat

    while (true)
    {
        server.handleClient();
        CLI.update();
        led.update();

        static uint32_t last = 0;
        if (millis() - last > 5000)
        {
            Debug.log("DBG: portal alive - free heap %u B", esp_get_free_heap_size());
            last = millis();
        }
        delay(2);
    }
}
