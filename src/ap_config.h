#pragma once

#include <helpers.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Preferences.h>
#include <serial_io.h>

// Call this during setup() or early boot. If config missing, enters AP mode.
void maybeEnterAPMode();