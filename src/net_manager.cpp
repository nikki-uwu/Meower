// Includes
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
#include <Arduino.h>
#include <cstring>
#include "net_manager.h"
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>


//  cmdQue is defined in main.cpp.  Bring it into this compilation unit so
//  handleRxPacket() can push inbound datagrams without a linker error.
extern QueueHandle_t cmdQue;




// Begin
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
// 1. Connect to WiFi as a station.
// 2. Open the existing WiFiUDP socket for TX.
// 3. Start an AsyncUDP listener for RX.  This is event-driven, so the CPU
//    sleeps until a packet arrives – there is no polling overhead.
// ---------------------------------------------------------------------------------------------------------------------------------
void NetManager::begin(const char* ssid,
                       const char* pass,
                       const char* ip,
                       uint16_t    localPortCtrl,
                       uint16_t    remotePortData)
{
    // 1. Connect to Wi-Fi
    WiFi.mode(WIFI_MODE_STA);
    WiFi.begin(ssid, pass);
    while (WiFi.status() != WL_CONNECTED)
        delay(250);

    // 2. Remember ports & peer IP so send() can use them later
    _localPortCtrl = localPortCtrl;
    _remotePortData = remotePortData;
    _remoteIP.fromString(ip);            // constant from defines.h

    // 3. Outbound socket
    _udp.begin(0);

    // 4. Inbound socket – zero-poll AsyncUDP
    _asyncRx.listen(localPortCtrl);
    _asyncRx.onPacket([this](AsyncUDPPacket& pkt) { handleRxPacket(pkt); });

    _state      = LinkState::IDLE;
    _lastRxMs   = millis();
}

// Send
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
void NetManager::sendCtrl(const void* data, size_t len)
{
    // Tiny guard – avoid building an empty UDP packet.
    if (len == 0) return;
    _udp.beginPacket(_remoteIP, _localPortCtrl); // use control port
    _udp.write(static_cast<const uint8_t*>(data), len);
    _udp.endPacket();
}
void NetManager::sendData(const void* data, size_t len)
{
    // Tiny guard – avoid building an empty UDP packet.
    if (_state != LinkState::STREAMING || len == 0) return;
    _udp.beginPacket(_remoteIP, _remotePortData); // use data port
    _udp.write(static_cast<const uint8_t*>(data), len);
    _udp.endPacket();
}

// NetManager::update()
// ---------------------------------------------------------------------------------------------------------------------------------
// - Runs once per loop() iteration.
// - Handles link-watchdog timeout and 1 s discovery beacons while idle.
// ---------------------------------------------------------------------------------------------------------------------------------
void NetManager::update(void)
{
    const uint32_t now = millis();

    // --------------------------------------------------------------------
    // 1. STREAMING watchdog – drop to IDLE if no packets for 30 s
    // --------------------------------------------------------------------
    if (_state == LinkState::STREAMING && (now - _lastRxMs) > _timeoutMs)
    {
        _state = LinkState::IDLE;
        _udp.flush();                   // abort any half-sent datagram
        xQueueReset(cmdQue);            // wipe pending commands

        _peerFound    = false;          // force beacon cycle
        _lastBeaconMs = 0;              // send first beacon right away
    }

    // --------------------------------------------------------------------
    // 2. GLOBAL silence guard – covers IDLE as well
    //    If we have not heard a single byte for _timeoutMs, assume the PC
    //    is gone and restart discovery beacons even when not streaming.
    // --------------------------------------------------------------------
    if (_peerFound && (now - _lastRxMs) > _timeoutMs)
    {
        _peerFound    = false;          // forget the peer
        _lastBeaconMs = 0;              // beacon immediately
        xQueueReset(cmdQue);            // clear stale commands
    }

    // --------------------------------------------------------------------
    // 3. Discovery beacon – 1 s cadence until a packet is heard again
    // --------------------------------------------------------------------
    if (!_peerFound && (now - _lastBeaconMs) >= WIFI_BEACON_PERIOD)
    {
        const uint8_t beacon = 0x0A;
        _udp.beginPacket(_remoteIP, _localPortCtrl);
        _udp.write(&beacon, 1);
        _udp.endPacket();
        _lastBeaconMs = now;
    }
}

// Drive LED – one call per loop()
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
void NetManager::driveLed(Blinker &led) noexcept
{
    // Reconfigure the burst pattern only when the mode changes
    static LedMode last = LedMode::DISC;
    const LedMode now   = ledMode();
    if (now == last) return;
    last = now;

    switch (now)
    {
        case LedMode::DISC:  led.burst(3, 100, 5000); break;   // 3 × 100 ms every 5 s
        case LedMode::IDLE:  led.burst(2, 100, 5000); break;   // 2 × 100 ms every 5 s
        case LedMode::STRM:  led.burst(1, 100, 5000); break;   // 1 × 100 ms every 5 s
    }
}

// NetManager::handleRxPacket()
// Called by AsyncUDP when a datagram arrives. Runs in the TCP/IP task
// (lower priority than ADC), so it must finish quickly and never block.
void NetManager::handleRxPacket(AsyncUDPPacket& packet)
{
    // 0. Ignore our own 1-byte discovery beacon (0x0A)
    if (packet.length() == 1 && *((uint8_t*)packet.data()) == 0x0A)
    {
        return; // never queue a beacon
    }

    // 1. 5-byte keep-alive “floof” -> refresh watchdog & mark peer present
    if (packet.length() == WIFI_KEEPALIVE_WORD_LEN &&
        memcmp(packet.data(), WIFI_KEEPALIVE_WORD, WIFI_KEEPALIVE_WORD_LEN) == 0)
    {
        _lastRxMs  = millis();
        _peerFound = true;
        if (_state == LinkState::DISCONNECTED)
            _state = LinkState::IDLE;
        return;                         // keep-alive never enters cmdQue
    }

    // 2. Over-sized packet?  Drop immediately (protection against floods).
    if (packet.length() > CMD_BUFFER_SIZE - 1)
    {
        return;
    }

    // 3. Copy payload into static buffer and queue it for the parser.
    static char rxBuf[CMD_BUFFER_SIZE];
    size_t n = packet.length();
    memcpy(rxBuf, packet.data(), n);
    rxBuf[n] = '\0';                    // NUL-terminate for strtok_r

    // Try to enqueue; if the queue is full we drop this packet.
    xQueueSend(cmdQue, rxBuf, 0);

    // 4. Any *valid* packet keeps the watchdog alive.
    _lastRxMs  = millis();
    _peerFound = true;
}

void NetManager::setTargetIP(const String& ipStr)
{
    _remoteIP.fromString(ipStr);
}