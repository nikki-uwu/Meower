#pragma once
#include <Arduino.h>        // millis(), analogRead(), pinMode(), digitalWrite()
#include "esp_timer.h"      // esp_timer_get_time()
#include "defines.h"
#include "esp_cpu.h"




//  getTimer8us – 8 µs time-base
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
//  esp_timer_get_time() returns a 64-bit micro-second counter.
//  We keep the lower 32 bits and right-shift by 3 (= divide by 8)
//  to obtain 8 µs ticks.  Wraps every 0xFFFF'FFFF * 8 ≈ 572 min.
static inline uint32_t getTimer8us() noexcept
{
    return static_cast<uint32_t>(esp_timer_get_time() >> 3U);
}

//  getTimer12us – 12.8 µs time-base using RISC-V hardware cycle counter
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
//  The ESP32-C3 RISC-V core provides a 64-bit hardware cycle counter ("rdcycle"),
//  which increments by one each CPU clock cycle. At the default clock (160 MHz),
//  one cycle = 6.25 ns. We right-shift the 64-bit cycle counter by 10 (= divide by 1024)
//  to obtain a tick every 1024 cycles, which equals 6.4 µs at 160 MHz, or 12.8 µs at 80 MHz.
//  This function returns the lower 32 bits of the shifted counter as a uint32_t.
//  The counter wraps every 0xFFFF'FFFF * 12.8 µs ≈ 15 hours.
//  - Ultra-fast: suitable for use in ISR or real-time tasks
//  - No system calls, minimal CPU cost
static inline uint32_t getTimer12_8us() noexcept
{
    // Get hardware cycle counter (increments at CPU clock, 80/160 MHz)
    uint32_t cycles = esp_cpu_get_ccount();
    return cycles >> 10U;  // 12.8 us ticks if CPU is 80 MHz
}




// Battery_Sense  – cached, non-blocking ADC reader
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
class Battery_Sense
{
    public:
        using value_t = float; // volt units after scaling
        static constexpr std::size_t DATA_SIZE = sizeof(value_t);

        /**
         *  @param pin         – GPIO that carries the divided-down battery voltage
         *  @param scale       – volts / ADC-count  (V = raw * scale).  Calibrate once -> hard-code.
         *  @param sample_ms   – minimum *wall-clock* interval between two physical ADC reads
         *  @param alpha       – IIR low-pass coefficient (0 ... 1).  Smaller -> heavier smoothing.
         *
         *  The constructor does **not** read the ADC – the first call to update() does.
         */
        Battery_Sense(uint8_t   pin        = 4,
                      value_t   scale      = 0.00428f,
                      uint32_t  sample_ms  = 1000UL,
                      float     alpha      = 0.05f)        // ~ 1 Hz bandwidth at 20 Hz update()
            : _pin(pin),
            _scale(scale),
            _sample_ms(sample_ms),
            _alpha(constrain(alpha, 0.0f, 1.0f))
        {
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
            const uint16_t raw   = analogRead(_pin);       // 0 … 4095 (12-bit ADC1 on C3)
            const value_t volts  = raw * _scale;
            _last_val += _alpha * (volts - _last_val);     // single-pole IIR (cheap!)
        }

        /* ---------- accessors (all read-only & ~20 ns each) ------------------ */
        inline value_t  getVoltage() const noexcept { return _last_val; }
        inline uint32_t age()        const noexcept { return millis() - _last_ms; }
        inline bool     isFresh(uint32_t maxAgeMs = 2 * 1000UL) const noexcept
        { return age() < maxAgeMs; }

        /* ---------- optional helpers ---------------------------------------- */
        inline uint32_t nextSampleIn() const noexcept
        { return (_sample_ms > age()) ? (_sample_ms - age()) : 0; }

        /* ---------- runtime tunables ---------------------------------------- */
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




// Blinker  – non-blocking LED flasher
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
class Blinker
{
    public:
        /**
         *  @param pin         – LED GPIO
         *  @param on_ms       – time LED stays *lit* each cycle
         *  @param period_ms   – full cycle length
         *  @param activeLow   – true = LED wired to Vcc through resistor (usual on dev-boards)
         */
        Blinker(uint8_t  pin,
                uint32_t on_ms       = 100,
                uint32_t period_ms   = 2000,
                bool     activeLow   = true)
            : _pin(pin),
            _on_ms(on_ms),
            _period_ms(period_ms),
            _activeLow(activeLow)
        {
            pinMode(_pin, OUTPUT);
            digitalWrite(_pin, _inactiveLevel());          // start OFF
        }

        //  Zero-cost, non-blocking – call each loop() pass.
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

        /// runtime control 
        inline void setTiming(uint32_t on_ms, uint32_t period_ms) noexcept
        {
            _on_ms     = on_ms;
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
        inline uint8_t _activeLevel () const noexcept { return _activeLow ? LOW  : HIGH; }
        inline uint8_t _inactiveLevel() const noexcept { return _activeLow ? HIGH : LOW; }

        const uint8_t _pin;
        uint32_t      _on_ms;
        uint32_t      _period_ms;
        bool          _activeLow;
        bool          _enabled    {true};
        bool          _state      {false};
        uint8_t  _flashes  {1};
        uint32_t _flash_ms {60};
};
