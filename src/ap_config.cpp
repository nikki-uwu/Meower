// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2025 Gleb Manokhin (nikki)
// Project: Meower

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
    // Check if async scan is complete
    int n = WiFi.scanComplete();
    String options;
    options.reserve(NETWORK_LIST_RESERVE);  // Pre-allocate for ~20 networks
    
    if (n == -1) {
        // Still scanning
        options = "<div style='color:#666;font-style:italic;'>Scanning for networks...</div>";
    } else if (n == 0) {
        // No networks found
        options = "<div style='color:#666;'>No networks found</div>";
    } else if (n > 0) {
        // Networks found - show them
        int shown = 0;
        for (int i = 0; (i < n) && (shown < MAX_NETWORKS_TO_SHOW); i++)
        {
            String ssid = WiFi.SSID(i);
            if (ssid.length() > 0)  // Skip empty SSIDs
            {
                ssid.replace("\"", "\\\""); // escape quotes
                options += "<div onclick='selectSSID(\"" + ssid + "\")' "
                        "style='cursor:pointer;color:blue;text-decoration:underline;'>"
                        + ssid + " (" + String(WiFi.RSSI(i)) + " dBm)</div>\n";
                shown++;
            }
        }
        // Clean up scan results
        WiFi.scanDelete();
        // Start a new scan for next page refresh
        WiFi.scanNetworks(true);  // Async scan for next time
    }

    // Read current ports from NVS to show in form
    // Note: PC IP is auto-discovered via MEOW_MEOW/WOOF_WOOF handshake, not configured here
    uint16_t portCtrl, portData;
    if (prefs.begin("netconf", /*readOnly=*/true))
    {
        portCtrl = prefs.getUShort("port_ctrl", UDP_PORT_CTRL);
        portData = prefs.getUShort("port_data", UDP_PORT_PC_DATA);
        prefs.end();
    }
    else
    {
        portCtrl = UDP_PORT_CTRL;
        portData = UDP_PORT_PC_DATA;
    }

    // Assemble HTML
    String page = R"rawliteral(
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body { font-size:2em; font-family:sans-serif; padding:20px; }
input { font-size:1em; width:100%; padding:10px; margin:10px 0; box-sizing:border-box; }
div.network { cursor:pointer; color:blue; text-decoration:underline; margin:5px 0; }
input[type="submit"] { background:#4CAF50; color:#fff; border:none; padding:15px; width:100%; font-size:1em; cursor:pointer; }
.error { color:red; font-size:0.8em; margin-top:10px; }
</style>
</head>
<body>
<h2>WiFi & UDP Setup</h2>
<form method="POST" action="/save" onsubmit="return validateForm()">
SSID:<br><input id="ssid" name="ssid" required><br>
<div><b>Available networks:</b><br>
)rawliteral";

    page += options;
    page += R"rawliteral(
</div><br>
Password (leave empty for open network):<br><input name="pass" type="password" id="pass"><br>
<div id="passError" class="error"></div>
Ctrl Port (default )rawliteral";
    page += String(UDP_PORT_CTRL);
    page += R"rawliteral():<br><input name="port_ctrl" type="number" min="1024" max="65535" value=")rawliteral";
    page += String(portCtrl);
    page += R"rawliteral("><br>
Data Port (default )rawliteral";
    page += String(UDP_PORT_PC_DATA);
    page += R"rawliteral():<br><input name="port_data" type="number" min="1024" max="65535" value=")rawliteral";
    page += String(portData);
    page += R"rawliteral("><br>
<input type="submit" value="Save and Restart">
</form>
<script>
function selectSSID(name){ document.getElementById("ssid").value=name; }
function validateForm(){
    var pass = document.getElementById("pass").value;
    var err = document.getElementById("passError");
    if(pass.length > 0 && pass.length < 8){
        err.innerHTML = "Password must be at least 8 characters or empty";
        return false;
    }
    err.innerHTML = "";
    return true;
}
</script>
</body>
</html>
)rawliteral";

    server.send(200, "text/html", page);
}

// ------------------------------------------------------------------
// handleSave() - validate, store settings and reboot
// ------------------------------------------------------------------
void handleSave()
{
    // Get form values
    String ssid = server.arg("ssid");
    String pass = server.arg("pass");
    String portCtrlStr = server.arg("port_ctrl");
    String portDataStr = server.arg("port_data");
    
    // Validate SSID
    if (ssid.isEmpty()) {
        server.send(400, "text/plain", "Error: SSID cannot be empty");
        return;
    }
    
    if (ssid.length() > 32) {
        server.send(400, "text/plain", "Error: SSID too long (max 32 characters)");
        return;
    }
    
    // Validate password (either empty or >= 8 chars)
    if (pass.length() > 0 && pass.length() < 8) {
        server.send(400, "text/plain", "Error: Password must be at least 8 characters or empty");
        return;
    }
    
    if (pass.length() > 64) {
        server.send(400, "text/plain", "Error: Password too long (max 64 characters)");
        return;
    }
    
    // Validate and parse ports
    uint16_t pc = portCtrlStr.toInt();
    uint16_t pd = portDataStr.toInt();
    
    // Validate port ranges
    if (pc < 1024 || pc > 65535) {
        pc = UDP_PORT_CTRL;  // Fall back to default
        Debug.log("[AP] Invalid ctrl port %s, using default %u", portCtrlStr.c_str(), pc);
    }
    
    if (pd < 1024 || pd > 65535) {
        pd = UDP_PORT_PC_DATA;  // Fall back to default
        Debug.log("[AP] Invalid data port %s, using default %u", portDataStr.c_str(), pd);
    }
    
    // Check ports aren't the same
    if (pc == pd) {
        server.send(400, "text/plain", "Error: Control and data ports must be different");
        return;
    }
    
    // All validation passed - save configuration
    WiFi.mode(WIFI_MODE_NULL);  // Radio off for safe NVS
    delay(100);
    
    prefs.begin("netconf", false);
    prefs.putString("ssid", ssid);
    prefs.putString("pass", pass);
    prefs.putUShort("port_ctrl", pc);
    prefs.putUShort("port_data", pd);
    prefs.end();
    
    Debug.log("[AP] Config saved - SSID: %s, Ports: %u/%u", ssid.c_str(), pc, pd);
    
    // Set boot mode to normal
    Preferences bm;
    if (bm.begin("bootlog", false))
    {
        bm.putString("BootMode", "NormalMode");
        bm.end();
    }
    else
        Debug.print("[AP] WARN: bootlog namespace not available");
    
    server.send(200, "text/plain", "Configuration saved! Rebooting...");
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
    bm.begin("bootlog", false);  // R/W auto-create
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
    
    // Step 1: Fully shutdown WiFi to ensure clean state
    WiFi.disconnect(true, true);
    WiFi.mode(WIFI_MODE_NULL);  // Complete radio shutdown
    delay(50);
    
    // Step 2: Initialize WiFi in AP mode at MINIMUM power to prevent over-saturation
    WiFi.mode(WIFI_MODE_AP);  // This triggers esp_wifi_init()
    
    // IMMEDIATELY set to minimum power - no delay between mode() and setTxPower()!
    WiFi.setTxPower((wifi_power_t)WIFI_POWER_2dBm);  // Start at absolute minimum (2 dBm)
    Debug.log("DBG: AP starting at minimum TX Power (2 dBm) to prevent over-saturation");
    delay(50);

    // Step 3: Create the AP while still at minimum power
    uint32_t apStartAttempt = millis();
    bool ok = WiFi.softAP(AP_SSID, AP_PASS, 1);
    
    if (!ok)    
    {
        Debug.print("ERR: softAP FAILED - restarting in 5 seconds");
        delay(AP_START_TIMEOUT_MS);
        bootCheck.ESP_REST("ap_start_failed");
    }
    
    Debug.log("DBG: softAP created successfully at 2 dBm - SSID: %s", AP_SSID);
    
    // Step 4: Start async WiFi scan for network list
    WiFi.scanNetworks(true);  // true = async, non-blocking
    Debug.print("DBG: Started background network scan");
    
    // Step 5: Configure the web server while still at minimum power
    IPAddress ip = WiFi.softAPIP();
    Debug.log("DBG: AP IP address = %s", ip.toString().c_str());

    server.on("/",     HTTP_GET , handleRoot);
    server.on("/save", HTTP_POST, handleSave);
    server.begin();
    
    // Step 6: Everything is configured - NOW increase to operational power
    Debug.log("DBG: AP fully configured, increasing TX Power to %d", AP_MODE_TX_POWER);
    WiFi.setTxPower((wifi_power_t)AP_MODE_TX_POWER);  // Now set to 11 dBm
    delay(50);
    
    wifi_power_t currentPower = WiFi.getTxPower();
    Debug.log("DBG: TX Power confirmed at: %d", currentPower);
    
    Debug.print("DBG: Captive portal ready at http://192.168.4.1/");
    
    // Initialize LED for heartbeat
    static Blinker led(PIN_LED, 100, 1000);  // slow heartbeat
    
    // Track AP start time for idle timeout
    uint32_t apStartTime = millis();
    uint32_t lastStatusTime = millis();

    // Main AP loop with timeout
    while (true)
    {
        server.handleClient();
        CLI.update();
        led.update();
        
        // Check for idle timeout (10 minutes)
        if (millis() - apStartTime > AP_IDLE_TIMEOUT_MS)
        {
            Debug.print("[AP] Idle timeout (10 min) - restarting");
            bootCheck.ESP_REST("ap_idle_timeout");
        }
        
        // Periodic status message
        if (millis() - lastStatusTime > 5000)
        {
            Debug.log("DBG: AP alive - heap %u B, TX %d, uptime %lu s", 
                      esp_get_free_heap_size(), 
                      AP_MODE_TX_POWER,
                      (millis() - apStartTime) / 1000);
            lastStatusTime = millis();
        }
        
        yield();  // Better than delay(2) for WiFi stack
    }
}