#include <Arduino.h>
#include <cstring>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <esp_err.h>
#include <net_manager.h>


//  cmdQue is defined in main.cpp.  Bring it into this compilation unit so
//  handleRxPacket() can push inbound datagrams without a linker error.
extern QueueHandle_t cmdQue;



// Wi-Fi event handler - plain C function pointer (no captures)
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
static NetManager* s_netMgr = nullptr;   // set once in NetManager::begin()


constexpr uint8_t Beacon = 0x0A;


// Thread/Task safe time delta.
// Why? Because if we do now = millis(), delta = (now - previous timestamp) and right between this call
// function got interrupt and updated timestamp - we have now which is less than previous timestamp.
// I've got this problem when i was checking beacon from PC and when i got current time just before
// i called if with (now - previous) wifi stack was sending interupt with new beacon from PC. So,
// beacon was there, previous timestemp was updated and when i do if((mow - previous) > limit) inside if
// we have overflowed uint and board stops streaming mode
static inline uint32_t safeTimeDelta(uint32_t now, uint32_t then)
{
    return (now >= then) ? (now - then) : 0;
}




// wifiEventCb() - global Wi-Fi event hook
//
// - Must be a plain C function (no captures) because WiFi.onEvent() on
//   the ESP32 Arduino core expects a raw pointer, not std::function.
// - The Wi-Fi driver task can emit events very early in boot, before
//   NetManager::begin() runs.  In that window the global instance
//   pointer (s_netMgr) is still nullptr, so we guard against it.
// - After NetManager::begin() executes, s_netMgr is set and every
//   subsequent event is forwarded to NetManager::onWifiEvent().
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
static void wifiEventCb(WiFiEvent_t event, WiFiEventInfo_t /*info*/)
{
    // The Wi-Fi driver task can emit events very early in boot, before
    // NetManager::begin() runs.  In that window the global instance
    DBG("wifiEventCb() id=%d", static_cast<int>(event)); 
    if (s_netMgr)
    {
        DBG("wifiEventCb: forward to NetManager"); 
        s_netMgr->onWifiEvent(event);   // forward to class instance
    }
}




// NetManager::onWifiEvent() - runs in Wi-Fi driver task, adjusts reconnect flags
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
void NetManager::onWifiEvent(WiFiEvent_t event)
{
    DBG("onWifiEvent() id=%d  state=%u", static_cast<int>(event),
                                        static_cast<uint8_t>(_state)); 

    if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED)
    {
        // We have to use safe time delta
        uint32_t now       = millis();
        uint32_t timeDelta = safeTimeDelta(now, _lastRxMs);

        DBG("EVENT DISCONNECTED  rxΔ=%lu", timeDelta);
        _state      = LinkState::DISCONNECTED; // stop sending right now
        _peerFound  = false;                   // force beacon handshake
        _lastFailMs = now;
        _reconnPend = true;
        _giveUp     = false;

        esp_err_t rc = esp_wifi_connect();      // async, non-blocking
        if (rc == ESP_ERR_WIFI_STATE)
        {
            // Already reconnecting - leave _reconnPend true
            // and keep the 1-minute wall timer running.
        }
    }
    else if (event == ARDUINO_EVENT_WIFI_STA_GOT_IP)
    {
        DBG("EVENT GOT_IP  reconnect OK"); 
        _reconnPend = false;
        _giveUp     = false;
        _lastFailMs = 0;
    }
}




// Begin
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
// 1. Connect to WiFi as a station.
// 2. Open the existing WiFiUDP socket for TX.
// 3. Start an AsyncUDP listener for RX.  This is event-driven, so the CPU
//    sleeps until a packet arrives - there is no polling overhead.
void NetManager::begin(const char* ssid,
                       const char* pass,
                       const char* ip,
                       uint16_t    localPortCtrl,
                       uint16_t    remotePortData)
{
    // 1. Connect to Wi-Fi
    WiFi.mode(WIFI_MODE_STA); // station-only; turns off the soft-AP
    WiFi.begin(ssid, pass);

    // 2. Remember ports & peer IP
    _localPortCtrl  = localPortCtrl;
    _remotePortData = remotePortData;
    _remoteIP.fromString(ip);

    // 3. Outbound socket
    _udp.begin(0);

    // 4. Inbound socket - zero-poll AsyncUDP
    _asyncRx.listen(localPortCtrl);
    _asyncRx.onPacket([this](AsyncUDPPacket& pkt) { handleRxPacket(pkt); });

    // 5. Link-state callback - event-driven watchdog
    s_netMgr = this;                     // expose this instance
    WiFi.onEvent(wifiEventCb);           // register static handler

    _state    = LinkState::IDLE;
    _lastRxMs = millis();
}




// Send
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
void NetManager::sendCtrl(const void* data, size_t len)
{
    // Tiny guard - avoid building an empty UDP packet.
    if (len == 0) return;
    _udp.beginPacket(_remoteIP, _localPortCtrl); // use control port
    _udp.write(static_cast<const uint8_t*>(data), len);
    _udp.endPacket();
}
void NetManager::sendData(const void* data, size_t len)
{
    // Tiny guard - avoid building an empty UDP packet.
    if (_state != LinkState::STREAMING || len == 0) return;
    _udp.beginPacket(_remoteIP, _remotePortData); // use data port
    _udp.write(static_cast<const uint8_t*>(data), len);
    _udp.endPacket();
    DBG("sendData: %u B", (unsigned)len);   

    if (_udp.getWriteError())
    {
        DBG("sendData: UDP WRITE-ERR");

        // Clear UDP write-error flag after logging, or the next call will always
        // return the same error until a successful packet:
        _udp.clearWriteError();
    }
}




// NetManager::update()
// - Runs once per loop() iteration.
// - Handles link-watchdog timeout and 1 s discovery beacons while idle.
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
void NetManager::update(void)
{
    const uint32_t   now = millis();
    static LinkState prevState = _state;  

    // 1. STREAMING watchdog - drop to IDLE if we have not heard from the PC
    // for more than _timeoutMs (10 000 ms by default).
    //
    // The TCP/IP task updates _lastRxMs when a packet arrives. If that write/interrupt
    // lands BETWEEN our read of millis() and our later read of _lastRxMs,
    // the subtraction under-flows and produces 0xFFFFFFFF (-1).  We guard
    // against that by forcing the delta to 0 whenever the clock went “backward”.
    {
        uint32_t rxDelta = safeTimeDelta(now, _lastRxMs); // wrap-safe and race-safe if TCP/IP interupts and updates _lastRxMs before if condition

        if ((_state == LinkState::STREAMING) && (rxDelta > _timeoutMs))
        {
            // send a debug message
            DBG("WATCHDOG: no data %lu ms - drop to IDLE", rxDelta);

            // Switch state to idle
            _state = LinkState::IDLE;

            
            _udp.flush();             // abort any half-sent datagram
            xQueueReset(cmdQue);      // clear pending commands
            _peerFound    = false;    // force beacon cycle
            _lastBeaconMs = 0;
        }
    }

    // 2. GLOBAL silence guard - covers IDLE as well
    //    If we have not heard a single byte for _timeoutMs, assume the PC
    //    is gone and restart discovery beacons even when not streaming.
    if (_peerFound && (safeTimeDelta(now, _lastRxMs) > _timeoutMs))
    {
        DBG("SILENCE: peer lost - restart beacon");
        _peerFound    = false;          // forget the peer
        _lastBeaconMs = 0;              // beacon immediately
        xQueueReset(cmdQue);            // clear stale commands
    }

    // 2.1. Wi-Fi reconnect watchdog - fail-safe if >1 min
    if (_reconnPend && (safeTimeDelta(now, _lastFailMs) > WIFI_RECONNECT_GIVEUP_MS))
    {
        DBG("FAILSAFE TIMER: reconnect >1 min");
        failSafe();
    }

    // 3. Discovery beacon - 1 s cadence until a packet is heard again
    if (!_peerFound && (safeTimeDelta(now, _lastBeaconMs) >= WIFI_BEACON_PERIOD))
    {
        DBG("BEACON TX");
        _udp.beginPacket(_remoteIP, _localPortCtrl);
        _udp.write(&Beacon, 1);
        _udp.endPacket();
        _lastBeaconMs = now;
    }

    _dbgActive = (_state == LinkState::STREAMING);

    if (prevState != _state)                                   // <<< ADD BLOCK
    {
        DBG("STATE %u->%u  peer=%d rxΔ=%lu",
            (unsigned)prevState, (unsigned)_state,
            (int)_peerFound, safeTimeDelta(now, _lastRxMs));
        prevState = _state;
    }
    debugGate(now);                      // prints only when _dbgActive
}

// Drive LED - one call per loop()
void NetManager::driveLed(Blinker &led) noexcept
{
    static LedMode last = LedMode::DISC;
    LedMode now;

    // LOST overrides normal modes
    now = _giveUp ? LedMode::LOST : ledMode();

    if (now == last) return;          // re-configure only on change
    last = now;

    switch (now)
    {
        case LedMode::DISC: led.burst(3, LED_ON_MS, 5000); break; // 3 × 0.25 s
        case LedMode::IDLE: led.burst(2, LED_ON_MS, 5000); break; // 2 × 0.25 s
        case LedMode::STRM: led.burst(1, LED_ON_MS, 5000); break; // 1 × 0.25 s
        case LedMode::LOST: led.burst(5, LED_ON_MS, 5000); break; // 5 × 0.25 s
    }
}




// NetManager::handleRxPacket()
// Called by AsyncUDP when a datagram arrives. Runs in the TCP/IP task
// (lower priority than ADC), so it must finish quickly and never block.
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
void NetManager::handleRxPacket(AsyncUDPPacket& packet)
{
    DBG("RX pkt len=%u", (unsigned)packet.length());
    // 0. Ignore our own 1-byte discovery beacon (0x0A)
    if (packet.length() == 1 && *((uint8_t*)packet.data()) == 0x0A)
    {
        DBG("RX ignore: beacon echo"); 
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
        DBG("RX oversize: %u B dropped", (unsigned)packet.length());
        return;
    }

    // 3. Copy payload into static buffer and queue it for the parser.
    static char rxBuf[CMD_BUFFER_SIZE];
    size_t n = packet.length();
    memcpy(rxBuf, packet.data(), n);
    rxBuf[n] = '\0';                    // NUL-terminate for strtok_r

    // Try to enqueue; if the queue is full we drop this packet.
    xQueueSend(cmdQue, rxBuf, 0);
    DBG("RX cmd queued");

    // 4. Any *valid* packet keeps the watchdog alive.
    _lastRxMs  = millis();
    _peerFound = true;
}

void NetManager::failSafe(void)
{
    DBG("FAILSAFE: giving up, radio off");
    stopStream();                        // drop to DISCONNECTED
    WiFi.disconnect(true, true);         // radio off, erase PMK
    _udp.flush();

    _giveUp     = true;                  // LED shows LOST state
    _reconnPend = false;
    _peerFound  = false;
    _state      = LinkState::DISCONNECTED;
    _lastBeaconMs = 0;

    xQueueReset(cmdQue);                 // clear command queue
}

void NetManager::setTargetIP(const String& ipStr)
{
    _remoteIP.fromString(ipStr);
}

void NetManager::debugPrint(void)
{
#if SERIAL_DEBUG
    static uint32_t seq = 0;

    DBG("=== NetManager === %lu", seq++);

    DBG(" state        : %u" , static_cast<uint8_t>(_state));
    DBG(" peerFound    : %d" , _peerFound);
    DBG(" reconnPend   : %d" , _reconnPend);
    DBG(" giveUp       : %d" , _giveUp);
    DBG(" lastFailMs   : %lu", _lastFailMs);
    DBG(" lastRxMs     : %lu", _lastRxMs);
    DBG(" lastBeaconMs : %lu", _lastBeaconMs);
    DBG(" rxΔ          : %lu", safeTimeDelta(millis(), _lastRxMs));

    DBG(" ===");
#endif
}

inline void NetManager::debugGate(uint32_t now)
{
#if SERIAL_DEBUG
    if (_dbgActive)
    {
        static uint32_t dbgT = 0;
        if (now - dbgT > 50)            // 20 Hz print cadence
        {
            debugPrint();
            dbgT = now;
        }
    }
#endif
}