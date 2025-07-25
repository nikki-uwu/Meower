// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2025 Gleb Manokhin (nikki)
// Project: Meower EEG/BCI Board

#ifndef NET_MANAGER_H
#define NET_MANAGER_H

// Includes
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_wifi.h>           // deep power-save
#include <AsyncUDP.h>      // Arduino wrapper - NO extra libs to install
#include "defines.h"            // SSID, UDP_IP, UDP_PORT_PC, UDP_PORT_C3
#include "helpers.h"




// Class
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
// NetManager - Handles all network communication with automatic peer discovery
// 
// Discovery Protocol:
// 1. ESP32 broadcasts "MEOW_MEOW" on UDP:5000 every second when no peer found
// 2. PC responds with "WOOF_WOOF" packet
// 3. ESP32 extracts PC's IP from the packet source
// 4. Connection established - no manual IP configuration needed
//
// The system also handles:
// - Keep-alive packets ("woof woof" every <10s from PC)
// - Automatic reconnection on WiFi drops
// - State management (DISCONNECTED -> IDLE -> STREAMING)
class NetManager
{
public:
    // Call once from setup().
    void begin(const char* ssid,
               const char* pass,
               uint16_t    localPortCtrl,
               uint16_t    remotePortData);

    // Non-blocking send.
    void sendCtrl(const void* data, size_t len);
    void sendData(const void* data, size_t len);

    // Call every loop() iteration; handles 1 s beacon when no peer yet.
    void update(void);

    // True after at least one valid packet arrived from the PC.
    bool peerFound(void) const { return _peerFound; }

    // Give direct socket pointer to code that still needs it (message_lib).
    WiFiUDP* udp() { return &_udp; }

    enum class LinkState : uint8_t { DISCONNECTED, IDLE, STREAMING };

    // called from message handlers
    inline void startStream() { _state = LinkState::STREAMING;  }
    inline void stopStream () { _state = _peerFound ? LinkState::IDLE
                                                    : LinkState::DISCONNECTED; }

    // sender and LED use this
    inline bool wantStream() const noexcept
    { return _state == LinkState::STREAMING; }

    enum class LedMode : uint8_t { DISC, IDLE, STRM, LOST }; // fail-safe blink
    inline LedMode ledMode() const noexcept
    {
        switch (_state)
        {
            case LinkState::DISCONNECTED: return LedMode::DISC;
            case LinkState::IDLE        : return LedMode::IDLE;
            default                     : return LedMode::STRM;
        }
    }

    // Drive a Blinker instance according to the current link state
    void driveLed(Blinker &led) noexcept;

    uint16_t  getControlPort() const { return _localPortCtrl;  }
    uint16_t  getDataPort()    const { return _remotePortData; }
    IPAddress getLocalIP()     const { return _localIP;        }

    void onWifiEvent(WiFiEvent_t event);   // called by global callback

    void debugPrint(void);      // prints all runtime flags when SERIAL_DEBUG

    inline void debugGate(uint32_t now);

private:
    WiFiUDP   _udp;
    IPAddress _remoteIP;             // auto-discovered via WOOF_WOOF beacon
    IPAddress _localIP{INADDR_NONE}; // our own STA IP
    uint16_t  _localPortCtrl;        // port we listen for commands on (was _localPort)
    uint16_t  _remotePortData;       // port we send fast data to

    uint32_t _lastBeaconMs = 0;    // last discovery beacon
    uint32_t _lastRxMs     = 0;    // last *valid* packet or keep-alive

    uint32_t  _timeoutMs { WIFI_SERVER_TIMEOUT };      // 10 s of silence from server => stop streaming

    volatile LinkState _state       { LinkState::DISCONNECTED };
    volatile uint32_t  _lastFailMs  = 0;     // first millis() when Wi-Fi dropped
    volatile bool      _peerFound   = false;
    volatile bool      _reconnPend  = false; // reconnect attempt in progress
    volatile bool      _giveUp      = false; // set by failSafe()

    void failSafe(void);            // called after timeout

    bool      _dbgActive   = false; // true while link is streaming

    // RAW-LATENCY, ZERO-POLL UDP **RECEIVE** PATH
    // -------------------------------------------------------------------------------------------
    // -------------------------------------------------------------------------------------------
    // We keep WiFiUDP for the TX side (unchanged) and add a second socket that is
    // event-driven.  AsyncUDP sits on top of lwIP inside the Arduino-ESP32 core
    // and fires an onPacket() callback only when a datagram is ready.
    AsyncUDP   _asyncRx;                         // listen-only socket
    void       handleRxPacket(AsyncUDPPacket&);  // member handler (not static)
};

#endif // NET_MANAGER_H
