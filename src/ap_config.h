// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2025 Gleb Manokhin (nikki)
// Project: Meower EEG/BCI Board

#pragma once

#include <helpers.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <serial_io.h>

// Call this during setup() or early boot. If config missing, enters AP mode.
void maybeEnterAPMode();