#include "ap_config.h"


static WebServer server(80);
static Preferences prefs;

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
    prefs.begin("netconf", false);
    prefs.putString("ssid",      server.arg("ssid"));
    prefs.putString("pass",      server.arg("pass"));
    prefs.putString("ip",        server.arg("ip"));
    prefs.putUShort("port_ctrl", server.arg("port_ctrl").toInt());
    prefs.putUShort("port_data", server.arg("port_data").toInt());
    prefs.end();

    server.send(200, "text/plain", "Saved. Rebooting...");
    delay(1000);
    ESP.restart();
}

void maybeEnterAPMode()
{
    prefs.begin("netconf", true);
    String ssid = prefs.getString("ssid", "");
    prefs.end();

    if (ssid.length() > 0) return; // settings already exist

    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID, AP_PASS);

    server.on("/",     handleRoot);
    server.on("/save", handleSave);
    server.begin();

    while (true)
    {
        server.handleClient();
        handleSerialConfig();
        delay(10);
    }
}

