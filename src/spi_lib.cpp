// Includes
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
#include "spi_lib.h"
#include <Arduino.h>
#include <driver/gpio.h>
#include <freertos/FreeRTOS.h>
#include <freertos/portmacro.h>
#include <esp_rom_sys.h>




// File-local resources
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
static SPIClass *   g_spi  = nullptr;                     // shared SPI handle
static portMUX_TYPE spiMux = portMUX_INITIALIZER_UNLOCKED;

// Bit-mask for driving both ADS1299 chip-select lines at once.
//
// - Each CS line occupies one GPIO bit in the ESP32 GPIO_OUT register.
// - Building the mask at compile time lets us toggle both pins
//   simultaneously with a single WRITE_PERI_REG() instead of two
//   back-to-back digitalWrite() calls.
//
// Result: perfectly synchronous edges on the master & slave devices and
// about 2 µs less CS-switching latency.
static constexpr uint32_t CS_MASK_BOTH = (1UL << PIN_CS_MASTER) | (1UL << PIN_CS_SLAVE);

// Delay inserted after CS goes LOW or before it returns HIGH.
// Datasheet requires ≥4 SPI clocks; 2 µs meets that at 2 MHz and still
// satisfies faster rates up to 8 MHz.
static constexpr uint32_t CS_DELAY_US = 2; // us time delay




// Helpers
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
// These two tiny wrappers drive both CS pins at once via the
// “write-one-to-set / write-one-to-clear” registers.
//
// WHY NOT digitalWrite()?
// -----------------------
// - digitalWrite() pokes one pin per call and goes through Arduino
//   overhead (~1.2 µs on ESP32-C3).
// - WRITE_PERI_REG() toggles both pins in <40 ns on the same clock
//   edge, keeping master/slave perfectly aligned.
//
// Synchronous CS edges guarantee that master & slave ADS1299 active
// windows are aligned and I do not waste time toggling one CS and then
// the second, which would add latency and skew.
static inline void cs_both_high()
{
    WRITE_PERI_REG(GPIO_OUT_W1TS_REG, CS_MASK_BOTH);
}
static inline void cs_both_low ()
{
    WRITE_PERI_REG(GPIO_OUT_W1TC_REG, CS_MASK_BOTH);
}




// Init
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
void spi_init(SPIClass * shared)
{
    g_spi = shared; // remember the shared bus object
}




// SPI Transaction wrappers
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
// Two simple wrappers to start / stop SPI transactions.
// The settings are always identical, so hiding them behind a helper
// guarantees every call uses the same frequency & mode.
void spiTransaction_ON(uint32_t spi_frequency)
{
    if (g_spi)
    {
        g_spi->beginTransaction(SPISettings(spi_frequency, MSBFIRST, SPI_MODE1));
    }
}

void spiTransaction_OFF()
{
    if (g_spi)
    {
        g_spi->endTransaction();
    }
}




// SPI TIME CRITICAL write/read, but controlling chips selects so we can talk to devices separately or to all at ones
// DMA burst with CS control
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
// - enter time critical mode
// - set all chip selects to high (deactivate both master and slave)
// - set chip select depending on who you want to talk to
// - wait a bit (≥4 clock delay)
// - send/read all bytes in one DMA-backed burst via transferBytes()
// - wait a bit (≥4 clock delay)
// - set chip select to high for master and slave so they are off
// - exit time critical mode
void IRAM_ATTR xfer(char            target,
                    uint8_t         length,
                    const uint8_t * txData,
                    uint8_t       * rxData)
{
    // Block every interrupt + scheduler
    portENTER_CRITICAL(&spiMux);

    // Deselect both pins before transfer to be sure both are switched off
    cs_both_high(); // WRITE_PERI_REG used here to get simultanious toggle

    // Set chip select pins based on target
    switch (target)
    {
        case 'M': digitalWrite(PIN_CS_MASTER, LOW); break; // Master only
        case 'S': digitalWrite(PIN_CS_SLAVE , LOW); break; // Slave only
        case 'B': cs_both_low();                    break; // Both - WRITE_PERI_REG used here to get simultanious toggle
        case 'T': /* test pulse – no CS change */   break; // Test - can be use in the future to see clock as a time marks on oscilloscope
        default : portEXIT_CRITICAL(&spiMux);      return; // If non of those - stop time critical mode and exit the entire function
    }

    // 2 us time delay before writing / reading
    // In datasheet i think there is something about at least 4 clocks before you pull chip select low (activate) so lets have
    // at least 2 us which will be more than exactat 2 MHz and more than enough for anything which is faster than that
    //          esp_rom_delay_us is a ROM routine used by Espressif themselves (ets_delay_us alias).
    //          It waits by counting APB cycles, auto-scales with CPU clock – no
    //          fixed NOP loops that break when you change freq.
    //          Accuracy: ±1 CPU cycle (<13 ns at 80 MHz).
    //          Runs from IRAM, so no cache-miss hiccup while flash is off during RF.
    esp_rom_delay_us(CS_DELAY_US); // must be ≥ 4 clocks

    // Perform SPI transfer
    // DMA-backed burst (faster & cleaner edges than per-byte loop)
    // Unfortunately SPIClass::transferBytes() in the ESP32/Arduino core is prototyped with a non-const pointer.
    // A const_cast<uint8_t *> removes the const qualifier so the call matches the library’s signature.
    g_spi->transferBytes(const_cast<uint8_t*>(txData), // TX 
                         rxData,                       // RX
                         length);                      // counter of bytes

    // Same reason for delay as before for chip select going up
    esp_rom_delay_us(CS_DELAY_US); // must be ≥ 4 clocks

    // Deselect both pins after transfer
    cs_both_high(); // WRITE_PERI_REG used here to get simultanious toggle

    // interrupts back on
    portEXIT_CRITICAL(&spiMux);
}
