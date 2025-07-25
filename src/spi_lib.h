// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2025 Gleb Manokhin (nikki)
// Project: Meower EEG/BCI Board

#ifndef SPI_LIB_H
#define SPI_LIB_H

#include <stdint.h>
#include <SPI.h>
#include "defines.h"     // pin numbers come from here




// Public API
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
// Call once from setup() **after** spi.begin().
void spi_init(SPIClass * shared);

// Fast wrappers for begin/endTransaction @2 MHz, MODE1.
void spiTransaction_ON (uint32_t);
void spiTransaction_OFF(void);

// Critical DMA burst with simultaneous CS handling.
// target: 'M' master, 'S' slave, 'B' both, 'T' test (no CS).
void IRAM_ATTR xfer(char            target,
                    uint8_t         length,
                    const uint8_t * txData,
                    uint8_t *       rxData);

#endif // SPI_LIB_H