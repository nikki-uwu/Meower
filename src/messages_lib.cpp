// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2025 Gleb Manokhin (nikki)
// Project: Meower EEG/BCI Board

#include <messages_lib.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <spi_lib.h>
#include <net_manager.h>
#include <Arduino.h>
#include <Preferences.h>
#include <helpers.h>




// Static context pointer provided by main program
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
static const MsgContext *C = nullptr; // set by msg_init()
extern NetManager net;
extern int32_t udp_read(char *buf, size_t cap);
extern BootCheck bootCheck;
extern Debugger Debug;





// External helpers
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
extern void ads1299_full_reset();
extern void BCI_preset();
extern void continuous_mode_start_stop(uint8_t on_off);




// Globals from main.cpp
extern volatile bool     g_adcEqualizer;       // FIR equalizer (sinc-3)   (true = ON)
extern volatile bool     g_removeDC;           // DC-blocking IIR          (true = ON)
extern volatile bool     g_block5060Hz;        // 50/60 Hz Notch           (true = ON)
extern volatile bool     g_block100120Hz;      // 100/120 Hz Notch         (true = ON)
extern volatile bool     g_filtersEnabled;     // Master filter enable     (true = ON)
extern volatile uint32_t g_selectDCcutoffFreq; // 0 = 0.5, 1 = 1, 2 = 2, 3 = 4, 4 = 8 Hz
extern volatile uint32_t g_selectNetworkFreq;  // 0 = 50Hz, 1 = 60Hz
extern volatile uint32_t g_digitalGain;        // 0 = 1, 1 = 2, 2 = 4, 3 = 8 ... up to 8 = 256

void msg_init(const MsgContext *ctx)
{
    C = ctx;
}

// Small helpers
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
static inline char *next_tok(char **ctx)
{
    return strtok_r(nullptr, " \r\n", ctx);
}

// Helper to update individual channel register bits
// Always uses read_Register_Daisy for reading
static bool update_channel_register(int channel, uint8_t mask, uint8_t new_bits)
{
    if (channel < 0 || channel > 15) return false;
    
    // Determine target ADC and register
    char target = (channel < 8) ? 'M' : 'S';
    uint8_t reg_addr = 0x05 + (channel % 8);
    
    // Read current values from BOTH ADCs
    RegValues current = read_Register_Daisy(reg_addr);
    
    // Pick the value we need
    uint8_t current_val = (channel < 8) ? current.master_reg_byte : current.slave_reg_byte;
    uint8_t new_val = (current_val & ~mask) | (new_bits & mask);
    
    // Write to specific ADC
    uint8_t tx[3] = {static_cast<uint8_t>(0x40 | reg_addr), 0x00, new_val};
    uint8_t rx[3] = {0};
    xfer(target, 3, tx, rx);
    
    // Verify by reading both again
    RegValues verify = read_Register_Daisy(reg_addr);
    uint8_t verified_val = (channel < 8) ? verify.master_reg_byte : verify.slave_reg_byte;
    
    return (verified_val == new_val);
}

// Helper to update all channel registers (CH1SET through CH8SET) on both ADCs
// Uses modify_register_bits internally for each channel register
static bool update_all_channels(uint8_t mask, uint8_t new_bits)
{
    bool all_success = true;
    
    // Loop through all channel registers (0x05=CH1SET to 0x0C=CH8SET)
    for (uint8_t reg = 0x05; reg <= 0x0C; reg++)
    {
        if (!modify_register_bits(reg, mask, new_bits))
        {
            all_success = false;
        }
    }
    
    return all_success;
}

// Register Read-Modify-Write Helper
// Reads a register from both ADCs, modifies specific bits, writes back
// Returns true if successful, false if verification failed
static bool modify_register_bits(uint8_t reg_addr, uint8_t mask, uint8_t new_bits)
{
    // Read current values
    RegValues current = read_Register_Daisy(reg_addr);

    // Update bits (preserve bits not in mask)
    uint8_t new_master = (current.master_reg_byte & ~mask) | (new_bits & mask);
    uint8_t new_slave  = (current.slave_reg_byte  & ~mask) | (new_bits & mask);

    // Write to Master
    uint8_t tx[3] = {static_cast<uint8_t>(0x40 | reg_addr), 0x00, new_master};
    uint8_t rx[3] = {0};
    xfer('M', 3, tx, rx);
    
    // Write to Slave  
    tx[2] = new_slave;
    xfer('S', 3, tx, rx);

    // Verify
    RegValues verify = read_Register_Daisy(reg_addr);
    bool success = (verify.master_reg_byte == new_master) && 
                   (verify.slave_reg_byte == new_slave);

    return success;
}

static void send_reply(const void* data, size_t len)
{
    net.sendCtrl(data, len);
}

static void send_reply_line(const char* msg)
{
    char buf[256];
    size_t n = snprintf(buf, sizeof(buf), "%s\r\n", msg);
    net.sendCtrl(buf, n);
}

static void send_error(const char *msg)
{
    if (!msg) return;
    send_reply_line(("ERR: " + String(msg)).c_str());
}




// Command helpers reused inside the family handlers
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
static void cmd_ADC_RESET(char **)
{
    Debug.print("CMD adc_reset - user requested ADC reset");

    // Stop streaming
    net.stopStream();

    // Full ADC reset
    ads1299_full_reset();

    // If we use it for BCI it does proper preset right away
    if (BCI_MODE) { BCI_preset(); }
}
static void cmd_START_CONT(char **)
{
    continuous_mode_start_stop(HIGH);
    net.startStream();
}
static void cmd_STOP_CONT(char **)
{
    continuous_mode_start_stop(LOW);
    Debug.print("CMD stop_cnt - user requested stop");
    net.stopStream();
}

// Hard reboot - never returns
static void cmd_ESP_REBOOT(char ** )
{
    send_reply_line("OK: rebooting…");
    delay(50);                      // give UDP time to flush
    bootCheck.ESP_REST("user_esp_reboot");// soft reset via ROM bootloader                
}

// ---------------------------------------------------------------------------------------------------------------------------------
// FAMILY: SPI   -  format
//                 spi  BOTH|MASTER|SLAVE  <len>  <byte0> … <byteN>
// ---------------------------------------------------------------------------------------------------------------------------------
void handle_SPI(char **ctx, const char * /*orig*/)
{
    if (!ctx) return;

    // CRITICAL: Stop continuous mode before any SPI commands
    continuous_mode_start_stop(LOW);

    // --------------------------------------------------------------------
    // 1. TARGET  (BOTH / MASTER / SLAVE)
    // --------------------------------------------------------------------
    char *tok = next_tok(ctx);
    if (!tok)
    {
        send_error("spi - missing target (BOTH|MASTER|SLAVE)");
        return;
    }

    char target = 0;
    if      (!strcasecmp(tok, "BOTH")   || !strcasecmp(tok, "B")) target = 'B';
    else if (!strcasecmp(tok, "MASTER") || !strcasecmp(tok, "M")) target = 'M';
    else if (!strcasecmp(tok, "SLAVE")  || !strcasecmp(tok, "S")) target = 'S';
    else if (!strcasecmp(tok, "TEST")   || !strcasecmp(tok, "T")) target = 'T';
    else
    {
        char out[96];
        snprintf(out, sizeof(out),
                 "spi - bad target '%s', expected BOTH|MASTER|SLAVE|TEST", tok);
        send_error(out);
        return;
    }

    // --------------------------------------------------------------------
    // 2. LENGTH  (1-256)
    // --------------------------------------------------------------------
    tok = next_tok(ctx);
    if (!tok)
    {
        send_error("spi - missing length (1-256)");
        return;
    }
    char *endptr = nullptr;
    uint32_t len = strtoul(tok, &endptr, 0);
    if (*endptr || len == 0 || len > 256)
    {
        send_error("spi - invalid length (1-256)");
        return;
    }

    // --------------------------------------------------------------------
    // 3. BYTES   (exactly <len> numbers follow)
    // --------------------------------------------------------------------
    uint8_t tx[256] = {0}, rx[256] = {0};
    for (uint32_t i = 0; i < len; ++i)
    {
        tok = next_tok(ctx);
        if (!tok)
        {
            send_error("spi - too few data bytes");
            return;
        }
        tx[i] = (uint8_t) strtoul(tok, nullptr, 0);
    }

    // --------------------------------------------------------------------
    // 4. TRANSACTION  (reuse existing SPI helper)
    // --------------------------------------------------------------------
    xfer(target, len, tx, rx);                   // full-duplex exchange

    // --------------------------------------------------------------------
    // 5. REPLY - echo RX data to PC
    // --------------------------------------------------------------------
    send_reply(rx, len);
}

// ---------------------------------------------------------------------------------------------------------------------------------
// FAMILY: SYS  (prefix "sys") - case-insensitive
// Commands:   adc_reset   start_cnt   stop_cnt   esp_reboot   erase_flash
//             FILTER_EQUALIZER_ON   | FILTER_EQUALIZER_OFF
//             FILTER_DC_ON          | FILTER_DC_OFF
//             FILTER_5060_ON        | FILTER_5060_OFF
//             FILTER_100120_ON      | FILTER_100120_OFF
//             FILTERS_ON            | FILTERS_OFF
//             dccutoffFreq <xx>     | networkfreq <xx>  | digitalgain <xx>
// ---------------------------------------------------------------------------------------------------------------------------------
void handle_SYS(char **ctx, const char * /*orig*/)
{
    char *cmd = next_tok(ctx);
    if (!cmd)
    {
        send_error("sys - missing command (see docs)");
        return;
    }

    // Reset and streaming commands
    if (!strcasecmp(cmd, "adc_reset"))       { cmd_ADC_RESET(ctx);   return; }
    if (!strcasecmp(cmd, "start_cnt"))       { cmd_START_CONT(ctx);  return; }
    if (!strcasecmp(cmd, "stop_cnt"))        { cmd_STOP_CONT(ctx);   return; }
    if (!strcasecmp(cmd, "esp_reboot"))      { cmd_ESP_REBOOT(ctx);  return; }

    // FIR equalizer runtime toggle
    if (!strcasecmp(cmd, "filter_equalizer_on"))
    {
        g_adcEqualizer = true;
        send_reply_line("OK: filter_equalizer_on");
        return;
    }
    if (!strcasecmp(cmd, "filter_equalizer_off"))
    {
        g_adcEqualizer = false;
        send_reply_line("OK: filter_equalizer_off");
        return;
    }
    // DC-blocking IIR runtime toggle
    if (!strcasecmp(cmd, "filter_dc_on"))
    {
        g_removeDC = true;
        send_reply_line("OK: filter_dc_on");
        return;
    }
    if (!strcasecmp(cmd, "filter_dc_off"))
    {
        g_removeDC = false;
        send_reply_line("OK: filter_dc_off");
        return;
    }
    // 50/60 Hz notch filter runtime toggle
    if (!strcasecmp(cmd, "filter_5060_on"))
    {
        g_block5060Hz = true;
        send_reply_line("OK: filter_5060_on");
        return;
    }
    if (!strcasecmp(cmd, "filter_5060_off"))
    {
        g_block5060Hz = false;
        send_reply_line("OK: filter_5060_off");
        return;
    }
    // 100/120 Hz notch filter runtime toggle
    if (!strcasecmp(cmd, "filter_100120_on"))
    {
        g_block100120Hz = true;
        send_reply_line("OK: filter_100120_on");
        return;
    }
    if (!strcasecmp(cmd, "filter_100120_off"))
    {
        g_block100120Hz = false;
        send_reply_line("OK: filter_100120_off");
        return;
    }
    // Global filter enable/disable
    if (!strcasecmp(cmd, "filters_on"))
    {
        g_filtersEnabled = true;
        send_reply_line("OK: filters_on");
        return;
    }
    if (!strcasecmp(cmd, "filters_off"))
    {
        g_filtersEnabled = false;
        send_reply_line("OK: filters_off");
        return;
    }
    

    // DC Cutoff Frequency (sys dccutofffreq XX)
    // Acceptable: 0.5, 1, 2, 4, 8  (maps to 0, 1, 2, 3, 4)
    // --------------------------------------------------------------------
    // --------------------------------------------------------------------
    if (!strcasecmp(cmd, "dccutofffreq"))
    {
        char *tok = next_tok(ctx);
        if (!tok)
        {
            send_error("dccutofffreq - missing value (0.5,1,2,4,8)");
            return;
        }
        float val = atof(tok);
        int ival = -1;
        if      (val == 0.5f) ival = 0;
        else if (val == 1.0f) ival = 1;
        else if (val == 2.0f) ival = 2;
        else if (val == 4.0f) ival = 3;
        else if (val == 8.0f) ival = 4;
        if (ival < 0)
        {
            send_error("dccutofffreq - value must be 0.5, 1, 2, 4, or 8");
            return;
        }
        g_selectDCcutoffFreq = ival;
        char msg[64];
        snprintf(msg, sizeof(msg), "OK: dccutofffreq set to %.1f", val);
        send_reply_line(msg);
        return;
    }

    // --------------------------------------------------------------------
    // Network Freq (sys networkfreq XX)
    // Acceptable: 50 or 60  (maps to 0 and 1)
    // --------------------------------------------------------------------
    if (!strcasecmp(cmd, "networkfreq"))
    {
        char *tok = next_tok(ctx);
        if (!tok)
        {
            send_error("networkfreq - missing value (50 or 60)");
            return;
        }
        int val = atoi(tok);
        if (val == 50)
        {
            g_selectNetworkFreq = 0;
            send_reply_line("OK: networkfreq set to 50");
            return;
        }
        if (val == 60)
        {
            g_selectNetworkFreq = 1;
            send_reply_line("OK: networkfreq set to 60");
            return;
        }
        send_error("networkfreq - value must be 50 or 60");
        return;
    }

    // --------------------------------------------------------------------
    // Digital Gain (sys digitalgain XX)
    // Acceptable: 1, 2, 4, 8, ... up to 256 (must be power of two)
    // Maps to 0=1, 1=2, 2=4, ... 8=256 (log2)
    // --------------------------------------------------------------------
    if (!strcasecmp(cmd, "digitalgain"))
    {
        char *tok = next_tok(ctx);
        if (!tok)
        {
            send_error("digitalgain - missing value (1,2,...,256)");
            return;
        }
        int val = atoi(tok);
        int ival = -1;
        if (val == 1) ival = 0;
        else if (val ==   2) ival = 1;
        else if (val ==   4) ival = 2;
        else if (val ==   8) ival = 3;
        else if (val ==  16) ival = 4;
        else if (val ==  32) ival = 5;
        else if (val ==  64) ival = 6;
        else if (val == 128) ival = 7;
        else if (val == 256) ival = 8;
        if (ival < 0)
        {
            send_error("digitalgain - must be 1,2,4,...256 (power of two)");
            return;
        }
        g_digitalGain = ival;
        char msg[64];
        snprintf(msg, sizeof(msg), "OK: digitalgain set to %d", val);
        send_reply_line(msg);
        return;
    }

    // --------------------------------------------------------------------
    // Erase Flash Preferences (sys erase_flash)
    // --------------------------------------------------------------------
    if (!strcasecmp(cmd, "erase_flash"))
    {
        Preferences prefs;
        prefs.begin("netconf", false); // open writable
        prefs.clear();                 // delete all keys in this namespace
        prefs.end();

        prefs.begin("bootlog", false);
        prefs.clear();
        prefs.end();

        send_reply_line("OK: flash config erased - rebooting...");
        delay(100);

        bootCheck.ESP_REST("user_erase_flash");
        return;
    }

    // Unknown command: error
    // --------------------------------------------------------------------
    // --------------------------------------------------------------------
    char out[256];
    snprintf(out, sizeof(out),
        "sys - got '%s', expected (adc_reset|start_cnt|stop_cnt|esp_reboot|erase_flash|filter_equalizer_on|filter_equalizer_off|filter_dc_on|filter_dc_off|filter_5060_on|filter_5060_off|filter_100120_on|filter_100120_off|filters_on|filters_off|dccutofffreq|networkfreq|digitalgain)", cmd);
    send_error(out);
}





// FAMILY: USR  (prefix "usr") - User-level commands
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
void handle_USR(char **ctx, const char * /*orig*/)
{
    // CRITICAL: Stop continuous mode before any USR commands
    continuous_mode_start_stop(LOW);

    char *cmd = next_tok(ctx);
    if (!cmd)
    {
        send_error("usr - missing command (see docs)");
        return;
    }

    // --------------------------------------------------------------------
    // Set Sampling Frequency (usr set_sampling_freq XXXX)
    // Acceptable: 250, 500, 1000, 2000, 4000 Hz
    // Maps to CONFIG1 bits [2:0]: 110, 101, 100, 011, 010
    // Reference: ADS1299 datasheet, page 46 "CONFIG1: Configuration Register 1"
    // Bits [2:0] are DR2:DR1:DR0 (Data Rate bits)
    // --------------------------------------------------------------------
    if (!strcasecmp(cmd, "set_sampling_freq"))
    {
        char *tok = next_tok(ctx);
        if (!tok)
        {
            send_error("set_sampling_freq - missing value (250,500,1000,2000,4000)");
            return;
        }
        
        int freq = atoi(tok);
        uint8_t dr_bits = 0xFF; // Invalid marker
        
        // Map frequency to DR bits (CONFIG1 register bits [2:0])
        // From ADS1299 datasheet page 46, Table 11:
        // DR2:DR1:DR0 | fMOD | fDATA 
        // 110 (0x06)  | fCLK/4  | 250 Hz
        // 101 (0x05)  | fCLK/8  | 500 Hz
        // 100 (0x04)  | fCLK/16 | 1000 Hz
        // 011 (0x03)  | fCLK/32 | 2000 Hz
        // 010 (0x02)  | fCLK/64 | 4000 Hz
        switch (freq)
        {
            case  250: dr_bits = 0x06; break; // 110
            case  500: dr_bits = 0x05; break; // 101
            case 1000: dr_bits = 0x04; break; // 100
            case 2000: dr_bits = 0x03; break; // 011
            case 4000: dr_bits = 0x02; break; // 010
            default:
                char err_msg[128];
                snprintf(err_msg, sizeof(err_msg), 
                    "set_sampling_freq - got '%d', allowed only 250,500,1000,2000,4000", freq);
                send_error(err_msg);
                return;
        }

        Debug.log("CMD set_sampling_freq - setting to %d Hz", freq);

        // Use helper to update CONFIG1 register bits [2:0]
        bool success = modify_register_bits(0x01, 0x07, dr_bits);

        if (success)
        {
            // Send success message
            char msg[64];
            snprintf(msg, sizeof(msg), "OK: sampling_freq set to %d Hz", freq);
            send_reply_line(msg);
        }
        else
        {
            send_error("set_sampling_freq - failed to update CONFIG1 register");
        }
        return;
    }

    // --------------------------------------------------------------------
    // Set Channel PGA Gain (usr gain <channel|ALL> <gain>)
    // Acceptable gains: 1, 2, 4, 6, 8, 12, 24
    // Maps to CHnSET register bits [6:4]: 000 to 110
    // Reference: ADS1299 datasheet, page 47 "CHnSET: Channel n Settings Registers"
    // --------------------------------------------------------------------
    if (!strcasecmp(cmd, "gain"))
    {
        // Get channel argument
        char *ch_tok = next_tok(ctx);
        if (!ch_tok)
        {
            send_error("gain - missing channel number (0-15 or ALL)");
            return;
        }

        // Get gain argument
        char *gain_tok = next_tok(ctx);
        if (!gain_tok)
        {
            send_error("gain - missing gain value (1,2,4,6,8,12,24)");
            return;
        }

        // Parse gain value and map to register bits
        int gain_val = atoi(gain_tok);
        uint8_t gain_bits = 0xFF; // Invalid marker
        
        switch (gain_val)
        {
            case  1: gain_bits = 0x00; break; // 000
            case  2: gain_bits = 0x10; break; // 001 << 4
            case  4: gain_bits = 0x20; break; // 010 << 4
            case  6: gain_bits = 0x30; break; // 011 << 4
            case  8: gain_bits = 0x40; break; // 100 << 4
            case 12: gain_bits = 0x50; break; // 101 << 4
            case 24: gain_bits = 0x60; break; // 110 << 4
            default:
                send_error("gain - invalid gain value (must be 1,2,4,6,8,12,24)");
                return;
        }

        // Handle "ALL" or specific channel
        if (!strcasecmp(ch_tok, "ALL"))
        {
            Debug.log("CMD gain - setting ALL channels to gain %d", gain_val);
            
            if (update_all_channels(0x70, gain_bits))
            {
                char msg[64];
                snprintf(msg, sizeof(msg), "OK: all channels set to gain %d", gain_val);
                send_reply_line(msg);
            }
            else
            {
                send_error("gain - failed to update some channels");
            }
        }
        else
        {
            // Parse specific channel number
            char *endptr;
            long ch_num = strtol(ch_tok, &endptr, 10);
            
            if (*endptr != '\0' || ch_num < 0 || ch_num > 15)
            {
                send_error("gain - invalid channel (must be 0-15 or ALL)");
                return;
            }

            Debug.log("CMD gain - setting channel %ld to gain %d", ch_num, gain_val);
            
            // Use helper for single channel
            if (update_channel_register(ch_num, 0x70, gain_bits))
            {
                char msg[64];
                snprintf(msg, sizeof(msg), "OK: channel %ld set to gain %d", ch_num, gain_val);
                send_reply_line(msg);
            }
            else
            {
                send_error("gain - failed to update channel register");
            }
        }
        return;
    }

    // --------------------------------------------------------------------
    // Channel Power Down Control (usr ch_power_down <channel|ALL> <ON|OFF>)
    // ON = power on (normal operation), OFF = power down
    // Controls CHnSET register bit [7]
    // --------------------------------------------------------------------
    if (!strcasecmp(cmd, "ch_power_down"))
    {
        // Get channel argument
        char *ch_tok = next_tok(ctx);
        if (!ch_tok)
        {
            send_error("ch_power_down - missing channel number (0-15 or ALL)");
            return;
        }

        // Get ON/OFF argument
        char *state_tok = next_tok(ctx);
        if (!state_tok)
        {
            send_error("ch_power_down - missing state (ON or OFF)");
            return;
        }

        // Parse state - ON means power on (bit=0), OFF means power down (bit=1)
        uint8_t power_bit;
        if (!strcasecmp(state_tok, "ON"))
        {
            power_bit = 0x00;  // Clear bit 7 = power on
        }
        else if (!strcasecmp(state_tok, "OFF"))
        {
            power_bit = 0x80;  // Set bit 7 = power down
        }
        else
        {
            send_error("ch_power_down - state must be ON or OFF");
            return;
        }

        // Handle "ALL" or specific channel
        if (!strcasecmp(ch_tok, "ALL"))
        {
            Debug.log("CMD ch_power_down - setting ALL channels to %s", state_tok);
            
            if (update_all_channels(0x80, power_bit))
            {
                char msg[64];
                snprintf(msg, sizeof(msg), "OK: all channels powered %s", state_tok);
                send_reply_line(msg);
            }
            else
            {
                send_error("ch_power_down - failed to update some channels");
            }
        }
        else
        {
            // Parse specific channel number
            char *endptr;
            long ch_num = strtol(ch_tok, &endptr, 10);
            
            if (*endptr != '\0' || ch_num < 0 || ch_num > 15)
            {
                send_error("ch_power_down - invalid channel (must be 0-15 or ALL)");
                return;
            }

            Debug.log("CMD ch_power_down - setting channel %ld to %s", ch_num, state_tok);
            
            // Use helper for single channel
            if (update_channel_register(ch_num, 0x80, power_bit))
            {
                char msg[64];
                snprintf(msg, sizeof(msg), "OK: channel %ld powered %s", ch_num, state_tok);
                send_reply_line(msg);
            }
            else
            {
                send_error("ch_power_down - failed to update channel register");
            }
        }
        return;
    }

    // --------------------------------------------------------------------
    // Channel Input Selection (usr ch_input <channel|ALL> <input_type>)
    // Controls CHnSET register bits [2:0]
    // --------------------------------------------------------------------
    if (!strcasecmp(cmd, "ch_input"))
    {
        // Get channel argument
        char *ch_tok = next_tok(ctx);
        if (!ch_tok)
        {
            send_error("ch_input - missing channel number (0-15 or ALL)");
            return;
        }

        // Get input type argument
        char *input_tok = next_tok(ctx);
        if (!input_tok)
        {
            send_error("ch_input - missing input type (NORMAL|SHORTED|BIAS_MEAS|MVDD|TEMP|TEST|BIAS_DRP|BIAS_DRN)");
            return;
        }

        // Parse input type and map to register bits
        uint8_t input_bits = 0xFF; // Invalid marker
        
        if (!strcasecmp(input_tok, "NORMAL"))         input_bits = 0x00; // 000
        else if (!strcasecmp(input_tok, "SHORTED"))   input_bits = 0x01; // 001
        else if (!strcasecmp(input_tok, "BIAS_MEAS")) input_bits = 0x02; // 010
        else if (!strcasecmp(input_tok, "MVDD"))      input_bits = 0x03; // 011
        else if (!strcasecmp(input_tok, "TEMP"))      input_bits = 0x04; // 100
        else if (!strcasecmp(input_tok, "TEST"))      input_bits = 0x05; // 101
        else if (!strcasecmp(input_tok, "BIAS_DRP"))  input_bits = 0x06; // 110
        else if (!strcasecmp(input_tok, "BIAS_DRN"))  input_bits = 0x07; // 111
        else
        {
            send_error("ch_input - invalid input type");
            return;
        }

        // Handle "ALL" or specific channel
        if (!strcasecmp(ch_tok, "ALL"))
        {
            Debug.log("CMD ch_input - setting ALL channels to %s", input_tok);
            
            if (update_all_channels(0x07, input_bits))
            {
                char msg[64];
                snprintf(msg, sizeof(msg), "OK: all channels set to %s input", input_tok);
                send_reply_line(msg);
            }
            else
            {
                send_error("ch_input - failed to update some channels");
            }
        }
        else
        {
            // Parse specific channel number
            char *endptr;
            long ch_num = strtol(ch_tok, &endptr, 10);
            
            if (*endptr != '\0' || ch_num < 0 || ch_num > 15)
            {
                send_error("ch_input - invalid channel (must be 0-15 or ALL)");
                return;
            }

            Debug.log("CMD ch_input - setting channel %ld to %s", ch_num, input_tok);
            
            // Use helper for single channel
            if (update_channel_register(ch_num, 0x07, input_bits))
            {
                char msg[64];
                snprintf(msg, sizeof(msg), "OK: channel %ld set to %s input", ch_num, input_tok);
                send_reply_line(msg);
            }
            else
            {
                send_error("ch_input - failed to update channel register");
            }
        }
        return;
    }

    // --------------------------------------------------------------------
    // SRB2 Connection Control (usr ch_srb2 <channel|ALL> <ON|OFF>)
    // ON = closed (connected to SRB2), OFF = open
    // Controls CHnSET register bit [3]
    // --------------------------------------------------------------------
    if (!strcasecmp(cmd, "ch_srb2"))
    {
        // Get channel argument
        char *ch_tok = next_tok(ctx);
        if (!ch_tok)
        {
            send_error("ch_srb2 - missing channel number (0-15 or ALL)");
            return;
        }

        // Get ON/OFF argument
        char *state_tok = next_tok(ctx);
        if (!state_tok)
        {
            send_error("ch_srb2 - missing state (ON or OFF)");
            return;
        }

        // Parse state - ON means closed (bit=1), OFF means open (bit=0)
        uint8_t srb2_bit;
        if (!strcasecmp(state_tok, "ON"))
        {
            srb2_bit = 0x08;  // Set bit 3 = closed/connected
        }
        else if (!strcasecmp(state_tok, "OFF"))
        {
            srb2_bit = 0x00;  // Clear bit 3 = open/disconnected
        }
        else
        {
            send_error("ch_srb2 - state must be ON or OFF");
            return;
        }

        // Handle "ALL" or specific channel
        if (!strcasecmp(ch_tok, "ALL"))
        {
            Debug.log("CMD ch_srb2 - setting ALL channels to SRB2 %s", state_tok);
            
            if (update_all_channels(0x08, srb2_bit))
            {
                char msg[64];
                snprintf(msg, sizeof(msg), "OK: all channels SRB2 %s", state_tok);
                send_reply_line(msg);
            }
            else
            {
                send_error("ch_srb2 - failed to update some channels");
            }
        }
        else
        {
            // Parse specific channel number
            char *endptr;
            long ch_num = strtol(ch_tok, &endptr, 10);
            
            if (*endptr != '\0' || ch_num < 0 || ch_num > 15)
            {
                send_error("ch_srb2 - invalid channel (must be 0-15 or ALL)");
                return;
            }

            Debug.log("CMD ch_srb2 - setting channel %ld SRB2 to %s", ch_num, state_tok);
            
            // Use helper for single channel
            if (update_channel_register(ch_num, 0x08, srb2_bit))
            {
                char msg[64];
                snprintf(msg, sizeof(msg), "OK: channel %ld SRB2 %s", ch_num, state_tok);
                send_reply_line(msg);
            }
            else
            {
                send_error("ch_srb2 - failed to update channel register");
            }
        }
        return;
    }
}




// Parse and process / execute commands
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
// Reads one message from udp_read(), which pulls from the cmdQue filled by incoming UDP packets via handleRxPacket
// - If cmdQue is empty, skips immediately (non-blocking).
// - If msg_init() has not been called, skips.
// - If incoming data is broken (null or what ever) or empty, skips.
// 
// If valid, parses the first token (command family: spi, sys, usr)
// and dispatches to the appropriate handler function.
// If command family is unknown, sends an error back over UDP.
//
// Handles exactly one command per call.
void parse_and_execute_command(void)
{
    if (!C) return;  // msg_init() not called

    static char buf[CMD_BUFFER_SIZE];
    char        original[CMD_BUFFER_SIZE];

    // 1. Read from control port
    int32_t n = udp_read(buf, CMD_BUFFER_SIZE);
    if (n <= 0) return;

    // 2. Ensure null-terminated buffers
    buf[n] = '\0';
    strncpy(original, buf, CMD_BUFFER_SIZE - 1);
    original[CMD_BUFFER_SIZE - 1] = '\0';

    // 3. Tokenize verb
    char *ctx = nullptr;
    char *verb = strtok_r(buf, " \r\n", &ctx);
    if (!verb) return;

    // 4. Dispatch to command handler
    if (!strcasecmp(verb, "spi")) { handle_SPI(&ctx, original); return; }
    if (!strcasecmp(verb, "sys")) { handle_SYS(&ctx, original); return; }
    if (!strcasecmp(verb, "usr")) { handle_USR(&ctx, original); return; }

    // 5. Unknown command -> send error
    send_error("got unknown family, expected (spi|sys|usr)");
}