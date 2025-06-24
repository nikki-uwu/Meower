#ifndef NET_MANAGER_H
#define NET_MANAGER_H

// Includes
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_wifi.h>           // deep power-save
#include <AsyncUDP.h>      // Arduino wrapper – NO extra libs to install
#include "defines.h"            // SSID, PASSWORD, UDP_IP, UDP_PORT_PC, UDP_PORT_C3
#include "helpers.h"




// Class
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
class NetManager
{
public:
    // Call once from setup().  Blocks until STA is up and has an IP.
    void begin(const char* ssid,
               const char* pass,
               const char* ip,
               uint16_t    localPortCtrl,
               uint16_t    remotePortData);

    // Non-blocking send.
    void sendCtrl(const void* data, size_t len);
    void sendData(const void* data, size_t len);

    // Call every loop() iteration; handles 1 s beacon when no peer yet.
    void update(void);

    // True after at least one valid packet arrived from the PC.
    bool peerFound(void) const { return _peerFound; }

    // Pull IP adress from the memory
    void setTargetIP(const String& ipStr);

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

    uint16_t getControlPort() const { return _localPortCtrl; }
    uint16_t getDataPort()    const { return _remotePortData; }


    void onWifiEvent(WiFiEvent_t event);   // called by global callback

    void debugPrint(void);      // prints all runtime flags when NET_DEBUG

    inline void debugGate(uint32_t now);

private:
    WiFiUDP   _udp;
    IPAddress _remoteIP;       // filled in begin() with fromString()
    uint16_t  _localPortCtrl;  // port we listen for commands on (was _localPort)
    uint16_t  _remotePortData; // port we send fast data to

    uint32_t  _lastBeaconMs = 0;    // last discovery beacon
    uint32_t  _lastRxMs     = 0;    // last *valid* packet or keep-alive
    bool      _peerFound    = false;

    LinkState _state     { LinkState::DISCONNECTED };
    uint32_t  _timeoutMs { WIFI_SERVER_TIMEOUT };      // 10 s of silence from server => stop streaming

    volatile uint32_t  _lastFailMs  = 0;     // first millis() when Wi-Fi dropped
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
