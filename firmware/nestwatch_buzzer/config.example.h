// Copy this file to config.h (config.h is git-ignored) and fill in your values.
#pragma once

#define WIFI_SSID      "daycare-wifi"
#define WIFI_PASSWORD  "change-me"

// The computer running the ollo vision service on the daycare network (it must be started with --host 0.0.0.0).
#define SERVER_HOST    "192.168.1.20"
#define SERVER_PORT    8000

// Must match the caregiver's buzzer id on the dashboard's Caregivers page.
#define BUZZER_ID      "buzzer-maria"
