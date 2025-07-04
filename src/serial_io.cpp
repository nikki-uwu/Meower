#include <stdarg.h>
#include <serial_io.h>




// External variables
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
extern BootCheck bootCheck; // defined in helpers.cpp




//  SerialCli implementation
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
SerialCli::SerialCli(Stream&  serialPort,
                     uint32_t baudRate)
: _ser  (serialPort),
  _baud (baudRate)
{}

// Port must already be open (Serial.begin(...) done in setup()).
void SerialCli::begin()
{
    _ser.printf("\n[CLI] ready @%lu baud - type 'help'\n", _baud);
}

void SerialCli::update()
{
    while (_ser.available() > 0)
    {
        char c = _ser.read();

        if (c == '\r')                  // ignore CR
        {
            continue;
        }
        if (c == '\n')                  // LF marks end of line
        {
            _rx[_rxPos] = '\0';
            _processLine();
            _rxPos = 0U;
        }
        else if (_rxPos < (sizeof(_rx) - 1U))
        {
            _rx[_rxPos++] = c;               // normal accumulation
        }
        else
        {
            // input longer than 127 B – discard until newline to resync
            while (_ser.available() && _ser.read() != '\n') {}
        }
    }
}

void SerialCli::_processLine()
{
    if (_rxPos == 0U)
    {
        return;                         // blank
    }

    char* cmd = strtok(_rx, " ");
    if (cmd == nullptr)
    {
        return;
    }

    struct Verb
    {
        const char*                   name;
        void (SerialCli::*handler)();
    };
    const Verb fixed[] =
    {
        {"help",  &SerialCli::_cmdHelp},
        {"show",  &SerialCli::_cmdShowConfig},
        {"apply", &SerialCli::_cmdApplyConfig},
    };

    for (const Verb& v : fixed)
    {
        if (strcasecmp(cmd, v.name) == 0)
        {
            (this->*v.handler)();
            return;
        }
    }

    if (strcasecmp(cmd, "set") == 0)
    {
        const char* key = strtok(nullptr, " ");
        const char* val = strtok(nullptr, "");

        if ((key == nullptr) || (val == nullptr))
        {
            _ser.println("ERR: usage  set <ssid|pass|ip|port_ctrl|port_data> <value>");
            return;
        }

        _cmdSetConfig(key, val);
        return;
    }

    _ser.printf("ERR: unknown command '%s'\n", cmd);
}

// ------------------------------------------------------------------
//  CLI command handlers
// ------------------------------------------------------------------
void SerialCli::_cmdHelp()
{
    _ser.println(
        "Commands:\n"
        "  set ssid <name>\n"
        "  set pass <password>\n"
        "  set ip   <x.x.x.x>\n"
        "  set port_ctrl <1-65535>\n"
        "  set port_data <1-65535>\n"
        "  show                 - print current values\n"
        "  apply                - save to NVS and reboot\n"
        "  help                 - this text\n");
}

void SerialCli::_cmdShowConfig()
{
    _ser.printf("Current (unsaved) config:\n"
                "  ssid       : %s\n"
                "  pass       : %s\n"
                "  ip         : %s\n"
                "  port_ctrl  : %u\n"
                "  port_data  : %u\n",
                _cfg.ssid.c_str(),
                _cfg.password.c_str(),      // password
                _cfg.ip.toString().c_str(), // IPAddress to text
                _cfg.portCtrl,
                _cfg.portData);
}

void SerialCli::_cmdSetConfig(const char* field,
                              const char* value)
{
    if (strcasecmp(field, "ssid") == 0)
    {
        _cfg.ssid = value;
        _ser.println("OK");
        return;
    }
    if (strcasecmp(field, "pass") == 0)
    {
        _cfg.password = value;
        _ser.println("OK");
        return;
    }
    if (strcasecmp(field, "ip") == 0)
    {
        if (_validIp(value))
        {
            _cfg.ip.fromString(value);  // ← text → IPAddress
            _ser.println("OK");
        }
        else
        {
            _ser.println("ERR: bad IP");
        }
        return;
    }
    if (   (strcasecmp(field, "port_ctrl") == 0)
        || (strcasecmp(field, "port_data") == 0))
    {
        uint32_t p = strtoul(value, nullptr, 10);

        if (!_validPort(p))
        {
            _ser.println("ERR: port 1-65535 only");
            return;
        }

        if (strcasecmp(field, "port_ctrl") == 0)
        {
            _cfg.portCtrl = static_cast<uint16_t>(p);
        }
        else
        {
            _cfg.portData = static_cast<uint16_t>(p);
        }

        _ser.println("OK");
        return;
    }

    _ser.printf("ERR: unknown field '%s'\n", field);
}

void SerialCli::_cmdApplyConfig()
{
    // 1. sanity checks
    if (_cfg.ssid.isEmpty())     { _ser.println("ERR: ssid not set"); return; }
    if (_cfg.ip == IPAddress())  { _ser.println("ERR: ip not set");   return; }

    if (_cfg.password.isEmpty())
        _ser.println("WARN: pass is empty");

    _ser.println("Saving to NVS …");

    // 2. write everything through the single NetConfig class
    NetConfig nc;                          // owns the Preferences handle
    nc.setSSID    (_cfg.ssid);
    nc.setPassword(_cfg.password);
    nc.setIP      (IPAddress(_cfg.ip));
    nc.setPortCtrl(_cfg.portCtrl);
    nc.setPortData(_cfg.portData);
    nc.save();                             // ← the only flash write

    // 3. note normal boot and restart
    Preferences bm;
    if (bm.begin("bootlog", false)) {
        bm.putString("BootMode", "NormalMode");
        bm.end();
    }

    _ser.println("OK - rebooting in 100 ms");
    delay(100);
    bootCheck.ESP_REST("serial_apply");
}
