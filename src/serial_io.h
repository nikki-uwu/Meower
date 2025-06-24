// ---------------------------------------------------------------------------------------------------------------------------------
// serial_io.h
//
// One header that groups:
//
// - DebugLogger - printf-style debug output, on/off switch,
//                 easy redirection to another Stream.
// - SerialCli   - human command-line interface for editing
//                 Wi-Fi / UDP settings.
//
// NOTE: Both classes assume Serial.begin(...) has already been
//       called from setup(). They never open the port themselves.
// ---------------------------------------------------------------------------------------------------------------------------------
#pragma once

#include <Arduino.h>
#include <Preferences.h>
#include <WiFi.h>
#include <defines.h>
#include <helpers.h>




// DebugLogger - runtime diagnostics
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
class DebugLogger
{
public:
    explicit DebugLogger(Stream&           = Serial     ,
                         uint32_t baud     = SERIAL_BAUD,
                         bool startEnabled = true       );

    void begin();   // prints banner, port must already be open
    void enable();  // turn logs on
    void disable(); // turn logs off
    bool isEnabled() const;

    // printf-style; attribute lets GCC catch format errors.
    void log(const char* fmt, ...) __attribute__((format(printf, 2, 3)));

private:
    Stream&  _ser;
    uint32_t _baud;
    bool     _enabled;
};




// NetConfig - Class and structure
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
struct NetConfig
{
    String   ssid;
    String   pass;
    String   ip;
    uint16_t portCtrl = UDP_PORT_CTRL;
    uint16_t portData = UDP_PORT_PC_DATA;
};

// SerialCli - user commands over the same UART
class SerialCli
{
    public:
        explicit SerialCli(Stream&  serialPort = Serial     ,
                           uint32_t baudRate   = SERIAL_BAUD);

        void begin();  // prints CLI banner, port must already be open
        void update(); // parse incoming chars

        const NetConfig& getConfig() const  // Basicaly get a reference (pointer) to saved internal config in read-only mode
        {
            return _cfg;
        }

    private:
        // Line parser helpers
        void _processLine();                   // process one full ASCII line ending with \r\n
        void _cmdHelp();                       // help
        void _cmdShowConfig();                 // show
        void _cmdSetConfig(const char* field,
                           const char* value); // set <field> <value>
        void _cmdApplyConfig();                // apply

        static bool _validPort(uint32_t p)
        {
            return (p > 0U) && (p <= 65535U);
        }
        static bool _validIp(const char* s)
        {
            IPAddress ip;
            return ip.fromString(s);
        }

        Stream&        _ser;  // just to be clear - it's a reference (fancy pointer) to Stream, so we can use _ser as normal way but inside it's a pointer.
        const uint32_t _baud;
        NetConfig      _cfg;
        char           _rx[128] {};
        size_t         _rxPos {0U};
};