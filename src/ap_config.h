// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2025 Gleb Manokhin (nikki)
// Project: Meower

#pragma once

#include <defines.h>
#include <helpers.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <serial_io.h>

// AP Mode Configuration
constexpr uint32_t AP_START_TIMEOUT_MS  = 5000;    // 5 seconds to start AP or restart
constexpr uint32_t AP_IDLE_TIMEOUT_MS   = 600000;   // 10 minutes idle timeout
constexpr uint8_t  MAX_NETWORKS_TO_SHOW = 20;     // Maximum networks to display
constexpr size_t   NETWORK_LIST_RESERVE = 2400;   // Reserve memory for ~20 networks

// Note: WiFi TX power enums and defaults are defined in defines.h

// Call this during setup() or early boot. If config missing, enters AP mode.
void maybeEnterAPMode();