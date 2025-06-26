#pragma once // stop the multiple-definition storm

#define UDP_PORT_PC_DATA 5001 // EEG/data stream (fast data)
#define UDP_PORT_CTRL    5000 // Command/control

#define SPI_RESET_CLOCK 2000000             // Hz, during full reset we are ALWAYS do that at 2 MHz, since at 8 or 5 or even 4 MHz sometimes it's unstable
#define SPI_NORMAL_OPERATION_CLOCK 16000000 // Hz, 8 MHz at the moment is the highest stable clock i was able to get

#define PIN_LED       20 // physical pin 30, GPIO20, U0RXD
#define LED_ON_MS     250  // LED HIGH for 250 ms
#define LED_PERIOD_MS 5000 // repeat every 5000 ms

#define PIN_BAT_SENSE   4 // physical pin 18, GPIO4, ADC1_CH4
#define BAT_SCALE       0.00123482072238899979173968476499f // Scaling value to bring ADC values to actual battery voltage
#define BAT_SAMPLING_MS 32 // ms between smapling of battery voltage

// Size of a counter we add at the end of the each ADC frame. It's uint32 so 4 bytes
// We assume that 
#define TIMESTAMP_SIZE 4

// User can set number of frames combined together to save on power or just to have slower pull rate for wifi
// Every frame still gets counter, so it's just several independent frames stacked together.
// MIN ---  1 (48 bytes for parsed adc data, 4 bytes for timer and at the end of combined frames 4 bytes for battery float)
// MAX --- 28 all frames with timestamps and battery value should be always < 1472 bytes (MTU), 52 * 28 + 4 = 1460
#define FRAMES_PER_PACKET 10

// Buffer size for incoming command UDP packets (adjust based on your max command length)
#define CMD_BUFFER_SIZE 512 // Bytes

// ms between beacons when you are not connected to anyone
#define WIFI_BEACON_PERIOD 1000

// Time out for board to say PC was lost, default was 1 minute
#define WIFI_SERVER_TIMEOUT 10000 // ms

// Give-up time for Wi-Fi reconnect watchdog (2 minutes)
#define WIFI_RECONNECT_GIVEUP_MS 60000 // ms

// PC must send it every < 60 s
#define WIFI_KEEPALIVE_WORD "floof"
#define WIFI_KEEPALIVE_WORD_LEN 5

// I dont want main loop to run to often, so i set default period of 50 ms
#define MAIN_LOOP_PERIOD_MS 50

// Do you need debug stuff?
#define SERIAL_DEBUG 1
#if SERIAL_DEBUG
  class DebugLogger;            // forward-declare
  extern DebugLogger Debug;     // global instance lives in main.cpp
  #define DBG(fmt, ...)  do { Debug.log(fmt, ##__VA_ARGS__); } while (0)
#else
  #define DBG(fmt, ...)  ((void)0)
#endif

#define SERIAL_BAUD  115200



// Everything bellow is basicaly hardware defined or by desing and you do not want to changed it, unless you change
// board design or you want to play with code.
// Why? just to avoid magic number like loop over 16 - is it 16 channels? or samples? or taps? so you at least know what it
// uses meaning wise. And most of the variable which use these defines wil be constant expressions or vectors with given size
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
// PIN DEFINITIONS FOR ESP32-C3 DEVKITM-1
// ALL PINS ARE GPIOXX, i.e XX PART FROM DATASHEET, Table 3.
#define PIN_SCLK      10 // SCLK on ESP32-C3 hardware SPI
#define PIN_MOSI       6 // MOSI on ESP32-C3 hardware SPI
#define PIN_MISO       2 // MISO on ESP32-C3 hardware SPI
#define PIN_CS_UNUSED 21 // Can be any free GPIO; here we pick physical pin 31, which is GPIO21, U0TXD
#define PIN_DRDY       3 // ADS1299 data-ready pin; must be a free GPIO
#define PIN_START      0 // ADS1299 START sampling pin. if it goes high ADC start to sample and if it's low ADC does nothing
#define PIN_PWDN       8 // ADS1299 data-ready pin; must be a free GPIO
#define PIN_RESET      7 // ADS1299 data-ready pin; must be a free GPIO
#define PIN_CS_MASTER  1 // ADS1299 data-ready pin; must be a free GPIO
#define PIN_CS_SLAVE   5 // ADS1299 data-ready pin; must be a free GPIO

// Size of the frame for 2 ADCs together, 27 bytes per each: 3 bytes constant load, 8 bytes(24 bits per sample) * 8 channels
#define ADC_SAMPLES_FRAME 54 // bytes

// Size of the frame for 2 ADCs together without preambs, 24 bits * 16 = 384 bits or 48 bytes
// we do not need contant load, so we will trim it and this way we can pack more frames together
#define ADC_PARSED_FRAME 48 // bytes

// Number of ADC channels we have
#define NUMBER_OF_ADC_CHANNELS 16

// Number of filter presets for different frequencies
#define NUM_OF_FREQ_PRESETS 5

// Number of filter presets for different frequencies
#define NUM_OF_CUTOFF_DC_PRESETS 5

// 50/60 Hz set
#define NUM_OF_REGIONS_5060 2