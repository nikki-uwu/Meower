// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2025 Gleb Manokhin (nikki)
// Project: Meower EEG/BCI Board

#ifndef HELPERS_H
#define HELPERS_H

#include <Arduino.h>        // millis(), analogRead(), pinMode(), digitalWrite()
#include <esp_timer.h>      // esp_timer_get_time()
#include <Preferences.h>
#include <defines.h>
#include <stdlib.h>
#include <WiFi.h>           // <-- used by BootCheck::ESP_REST()
#include <spi_lib.h>




// Global variables
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
extern volatile bool     continuousReading;
extern const    uint32_t FRAMES_PER_PACKET_LUT[5];




// Structures
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
struct RegValues
{
    uint8_t master_reg_byte;
    uint8_t slave_reg_byte;
};




// Declarations in .cpp
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
void ads1299_full_reset();
void BCI_preset();
void continuous_mode_start_stop(uint8_t on_off);
void wait_until_ads1299_is_ready();
RegValues read_Register_Daisy(uint8_t reg_addr);




//  getTimer8us - 8 µs time-base
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
//  esp_timer_get_time() returns a 64-bit micro-second counter.
//  We keep the lower 32 bits and right-shift by 3 (= divide by 8)
//  to obtain 8 µs ticks.  Wraps every (2^32 - 1) * 8us = 9.5 hours.
static inline uint32_t getTimer8us() noexcept
{
    return static_cast<uint32_t>(esp_timer_get_time() >> 3U); // shift by 3 to the right gives division by 8 - or 8 us steps
}

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




// Battery_Sense  - cached, non-blocking ADC reader
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
class Battery_Sense
{
    public:
        using value_t = float; // volt units after scaling
        static constexpr std::size_t DATA_SIZE = sizeof(value_t);

        /**
         *  @param pin         - GPIO that carries the divided-down battery voltage
         *  @param scale       - volts / ADC-count  (V = raw * scale).  Calibrate once -> hard-code.
         *  @param sample_ms   - minimum *wall-clock* interval between two physical ADC reads
         *  @param alpha       - IIR low-pass coefficient (0 ... 1).  Smaller -> heavier smoothing.
         *
         *  The constructor does **not** read the ADC - the first call to update() does.
         */
        Battery_Sense(uint8_t   pin        = 4,
                      value_t   scale      = 0.001235f,
                      uint32_t  sample_ms  = 1000UL,
                      float     alpha      = 0.05f)        // ~ 1 Hz bandwidth at 20 Hz update()
            : _pin(pin),
            _scale(scale),
            _sample_ms(sample_ms),
            _alpha(constrain(alpha, 0.0f, 1.0f))
        {
            // MAKE SURE PIN FOR ADC IS ADC1, ADC2 can conflict with Wi-Fi!!!!!!!!!!!!!!!!!!!
            pinMode(_pin, INPUT);

            // Guarantee 12-bit reads even if the main sketch forgets to call it.
            analogReadResolution(12);

            // 0 dB -> full-scale ~ 0.8 V on ESP32-C3.  Perfect for our  ≤0.5 V signal.
            analogSetAttenuation(ADC_0db);
        }

        /**
         *  Call once per loop().  
         *  Does *nothing* unless at least @sample_ms elapsed since the last physical read.
         *  Returned value is low-pass-filtered in software -> 20× less jitter than raw ADC.
         */
        inline void update() noexcept
        {
            const uint32_t now = millis();
            if (now - _last_ms < _sample_ms) return;       // not time yet

            _last_ms  = now;
            // MAKE SURE PIN FOR ADC IS ADC1, ADC2 can conflict with Wi-Fi!!!!!!!!!!!!!!!!!!!
            const uint16_t raw   = analogRead(_pin);       // 0 … 4095 (12-bit ADC1 on C3)
            const value_t volts  = raw * _scale;
            _last_val += _alpha * (volts - _last_val);     // single-pole IIR (cheap!)
        }

        // accessors (all read-only & ~20 ns each)
        inline value_t  getVoltage() const noexcept { return _last_val; }
        inline uint32_t age()        const noexcept { return millis() - _last_ms; }
        inline bool     isFresh(uint32_t maxAgeMs = 2 * 1000UL) const noexcept
        { return age() < maxAgeMs; }

        // optional helpers
        inline uint32_t nextSampleIn() const noexcept
        { return (_sample_ms > age()) ? (_sample_ms - age()) : 0; }

        // runtime tunables
        inline void setFilter(float alpha) noexcept
        { _alpha = constrain(alpha, 0.0f, 1.0f); }

        inline void setPeriod(uint32_t sample_ms) noexcept
        { _sample_ms = sample_ms; }

    private:
        const uint8_t  _pin;
        const value_t  _scale;
        uint32_t       _sample_ms;        // may change at run-time
        float          _alpha;            // LPF coefficient (0 … 1)

        uint32_t _last_ms  {0};
        value_t  _last_val {0.0f};
};




// Blinker  - non-blocking LED flasher
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
class Blinker
{
    public:
        /**
         *  @param pin         - LED GPIO
         *  @param period_ms   - full cycle length
         *  @param activeLow   - true = LED wired to Vcc through resistor (usual on dev-boards)
         */
        Blinker(uint8_t  pin,
                uint32_t period_ms   = 2000,
                bool     activeLow   = true)
            : _pin(pin),
            _period_ms(period_ms),
            _activeLow(activeLow)
        {
            pinMode(_pin, OUTPUT);
            digitalWrite(_pin, _inactiveLevel());          // start OFF
        }

        //  Zero-cost, non-blocking - call each loop() pass.
        inline void update() noexcept
        {
            if (!_enabled) return;

            const uint32_t phase = millis() % _period_ms;
            const uint32_t slot  = phase / (2 * _flash_ms);        // on+off pair
            const bool nowOn     = (slot < _flashes) &&
                                (phase % (2 * _flash_ms) < _flash_ms);

            if (nowOn != _state)
            {
                _state = nowOn;
                digitalWrite(_pin, nowOn ? _activeLevel() : _inactiveLevel());
            }
        }

        // runtime control 
        inline void setTiming(uint32_t period_ms) noexcept
        {
            _period_ms = period_ms;
        }

        inline void enable(bool en) noexcept
        {
            _enabled = en;
            if (!en) digitalWrite(_pin, _inactiveLevel());
        }

        inline bool isOn() const noexcept { return _state; }

        // Configure an N-flash burst inside one period
        inline void burst(uint8_t flashes,
                        uint32_t flash_ms,
                        uint32_t period_ms)
        {
            _flashes   = flashes ? flashes : 1;
            _flash_ms  = flash_ms;
            _period_ms = period_ms;
        }

    private:
        inline uint8_t _activeLevel()   const noexcept { return _activeLow ? LOW  : HIGH; }
        inline uint8_t _inactiveLevel() const noexcept { return _activeLow ? HIGH : LOW;  }

        const uint8_t _pin;
        uint32_t      _period_ms;
        bool          _activeLow;
        bool          _enabled    {true};
        bool          _state      {false};
        uint8_t  _flashes  {1};
        uint32_t _flash_ms {60};
};




// BootCheck - detects three fast boots (<3 s each).
//
// - On every boot we shift the history (slot2 -> 3, 1 -> 2, 0 -> 1) and insert a new
//   placeholder “slow” record in slot 0.  When setup() runs long enough
//   we overwrite the placeholder with the real uptime.
//
// - If the last three boots were “fast” and flagged “a” we only write
//   BootMode = "AccessPoint"
//
// - The first lines of setup() (see main.cpp) look at BootMode. If it is
//   MISSING or equals "AccessPoint" we immediately jump into the AP
//   portal and stay there until the user saves a config. handleSave() or
//   the serial “apply and reboot” command then stores
//       BootMode = "NormalMode"
//   just before rebooting.
//
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
class BootCheck
{
public:
    void init();
    void update();

    void ESP_REST(const char* reason = "user_reboot")
    {
        // Tag the boot with a human-readable flag and perform a clean restart.
        WiFi.mode(WIFI_MODE_NULL);     // stop radio for safe NVS write
        delay(100);

        Preferences p;
        if (p.begin("bootlog", false))
        {
            p.putString("flag0", reason ? reason : "");
            p.end();
        }
        delay(100);
        ESP.restart();                // never returns
    }

private:
    static constexpr uint32_t FAST_WINDOW_MS = 5000; // 5 s
    Preferences prefs;
};


struct NetSettings
{
    String     ssid;
    String     password;
    uint16_t   portCtrl = UDP_PORT_CTRL;
    uint16_t   portData = UDP_PORT_PC_DATA;
};

class NetConfig
{
public:
    NetConfig();               // sets sane defaults
    bool  load();              // NVS -> members
    bool  save() const;        // members -> NVS

    // quick access helpers
    const NetSettings &get() const    { return s_; }
    void set(const NetSettings &n)    { s_          = n; }
    void setSSID(const String &v)     { s_.ssid     = v; }
    void setPassword(const String &v) { s_.password = v; }
    void setPortCtrl(uint16_t v)      { s_.portCtrl = v; }
    void setPortData(uint16_t v)      { s_.portData = v; }

private:
    static constexpr const char *NS = "netconf";
    NetSettings s_;
};



// Debug class
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
class Debugger
{
public:
    // Constructor: remembers which Serial (or any Stream) to use
    Debugger(Stream&  port = Serial,
             uint32_t baud = SERIAL_BAUD,
             bool en       = true)
        : _port(port),
          _baud(baud),
          _enabled(en) {}

    // Call once after Serial.begin(); prints one banner line
    void begin(uint32_t baud = SERIAL_BAUD)
    {
        _baud = baud; // store for reference
        _port.printf("\n[DBG] logger active @%lu baud\n", _baud);
    }

    // Turn messages on and off while running
    void enable()          { _enabled = true;  }
    void disable()         { _enabled = false; }
    bool isEnabled() const { return _enabled;  }

    // Print plain text (const char* or Arduino String) with newline
    template<typename T>
    void print(const T& v)
    {
        if (!_enabled) return;
        _port.println(v);
    }

    // Print formatted text (printf style) with newline
    void log(const char* fmt, ...)
    {
        if (!_enabled) return;
        char buf[128];
        va_list ap;
        va_start(ap, fmt);
        vsnprintf(buf, sizeof(buf), fmt, ap);
        va_end(ap);
        _port.println(buf);
    }

private:
    Stream&  _port;     // reference to the Serial (or other Stream) object
    uint32_t _baud;     // baud rate, only for the banner message
    bool     _enabled;  // false = mute, true = print
};


#endif // HELPERS_H
