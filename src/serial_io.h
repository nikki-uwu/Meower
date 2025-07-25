// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2025 Gleb Manokhin (nikki)
// Project: Meower

#pragma once

#include <Arduino.h>
#include <Preferences.h>
#include <WiFi.h>
#include <defines.h>
#include <helpers.h>




// NetConfig - Class and structure
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
// SerialCli - user commands over the same UART
class SerialCli
{
    public:
        explicit SerialCli(Stream&  serialPort = Serial     ,
                           uint32_t baudRate   = SERIAL_BAUD);

        void begin();  // prints CLI banner, port must already be open
        void update(); // parse incoming chars

        const NetSettings& getConfig() const  // Basically get a reference (pointer) to saved internal config in read-only mode
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
        NetSettings    _cfg;  // NetSettings comes from helpers.h
        char           _rx[128] {};
        size_t         _rxPos {0U};
};