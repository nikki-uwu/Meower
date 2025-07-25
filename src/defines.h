// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2025 Gleb Manokhin (nikki)
// Project: Meower EEG/BCI Board

#pragma once // stop the multiple-definition storm

// Network Configuration:
// - UDP_PORT_PC_DATA: Port for high-speed EEG data streaming
// - UDP_PORT_CTRL: Port for command/control and autodiscovery beacons
// - PC IP: Automatically discovered via MEOW_MEOW/WOOF_WOOF handshake
#define UDP_PORT_PC_DATA 5001 // EEG/data stream (fast data)
#define UDP_PORT_CTRL    5000 // Command/control

#define SPI_COMMAND_CLOCK 2000000           // Hz, during full reset we ALWAYS do that at 2 MHz, since at 8 or 5 or even 4 MHz sometimes it's unstable
#define SPI_NORMAL_OPERATION_CLOCK 16000000 // Hz, 16 MHz at the moment is the highest stable clock i was able to get

#define PIN_LED       20 // physical pin 30, GPIO20, U0RXD
#define LED_ON_MS     250  // LED HIGH for 250 ms
#define LED_PERIOD_MS 5000 // repeat every 5000 ms

#define PIN_BAT_SENSE   4 // physical pin 18, GPIO4, ADC1_CH4
#define BAT_SCALE       0.001235f // Scaling value to bring ADC values to actual battery voltage
#define BAT_SAMPLING_MS 32 // ms between sampling of battery voltage

// Frame packing configuration - combines multiple ADC frames into single UDP packet
// 
// Why pack frames?
// 1. MTU LIMIT: Ethernet MTU is 1500 bytes. After IP/UDP headers: 1472 bytes usable
//    Maximum frames = (1472 - 4) / 52 = 28.23, so MAX = 28 frames
// 2. WIFI LIMIT: ESP32 needs ~6ms minimum between UDP packets (166 pkt/s max)
//    Without packing at 4000Hz = 4000 pkt/s = IMPOSSIBLE
//    With max packing at 4000Hz = 142 pkt/s = SAFE
// 3. EFFICIENCY: Each packet has 28 bytes overhead. Packing reduces overhead 28x
// 
// Frame structure: [48 Bytes ADC data][4 Bytes timestamp] = 52 bytes per frame
// Packet structure: [Frame1][Frame2]...[FrameN][4 Bytes battery] = N*52+4 bytes total
// 
// Examples:
// -  5 frames:  5*52+4 =  264 bytes (good for 250Hz -> 50 pkt/s)
// - 28 frames: 28*52+4 = 1460 bytes (max MTU safe, for high rates)
#define MAX_FRAMES_PER_PACKET 28  // MTU limit: 28*52+4 = 1460 < 1472
#define TARGET_WIFI_FPS 50        // Target packet rate when possible

// Default frame packing for 250 Hz startup (board initializes at 250 Hz)
// 250 Hz / 5 frames = 50 FPS target
#define DEFAULT_FRAMES_PER_PACKET 5

// Buffer size for incoming command UDP packets (adjust based on your max command length)
#define CMD_BUFFER_SIZE 512 // Bytes

// ms between beacons when you are not connected to anyone
#define WIFI_BEACON_PERIOD 1000

// Time out for board to say PC was lost
#define WIFI_SERVER_TIMEOUT 10000 // ms

// Give-up time for Wi-Fi reconnect watchdog (1 minutes)
#define WIFI_RECONNECT_GIVEUP_MS 60000 // ms

// PC must send WOOF_WOOF for discovery and keepalive (every < 10 s)
#define WIFI_KEEPALIVE_WORD "WOOF_WOOF"
#define WIFI_KEEPALIVE_WORD_LEN 9

// I don't want main loop to run too often, so i set default period of 50 ms
#define MAIN_LOOP_PERIOD_MS 50

// Do you need debug stuff?
#define SERIAL_DEBUG 1
#define SERIAL_BAUD  115200

// BCI MODE?
// IF YES IT WILL SET UP ALL CHANNEL TO BASIC ON EACH RESET
// BCI mode means: SRB2 mode (all positive shorted together)
//                 Bias output is ON
//                 Fs 250 Hz
#define BCI_MODE 1



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

// Size of the frame for 2 ADCs together, 27 bytes per each: 3 bytes constant load + 8 channels * 3 bytes (24 bits per sample)
#define ADC_SAMPLES_FRAME 54 // bytes

// Size of the frame for 2 ADCs together without preambs, 24 bits * 16 = 384 bits or 48 bytes
// we do not need constant load, so we will trim it and this way we can pack more frames together
#define ADC_PARSED_FRAME 48 // bytes

// Size of a counter we add at the end of each ADC frame. It's uint32 so 4 bytes
#define TIMESTAMP_SIZE 4

// One full ADC frame size with timestamp included at the end in BYTES
#define ADC_FULL_FRAME_SIZE (ADC_PARSED_FRAME + TIMESTAMP_SIZE)

// Number of ADC channels we have
#define NUMBER_OF_ADC_CHANNELS 16

// Number of filter presets for different frequencies
#define NUM_OF_FREQ_PRESETS 5

// Number of DC cutoff frequency presets
#define NUM_OF_CUTOFF_DC_PRESETS 5

// 50/60 Hz set
#define NUM_OF_REGIONS_5060 2