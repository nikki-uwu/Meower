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
extern void continious_mode_start_stop(uint8_t on_off);




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
    ads1299_full_reset();

    // If we use it for BCI it does normal preset right away
    if (BCI_MODE) { BCI_preset(); }
}
static void cmd_START_CONT(char **)
{
    continious_mode_start_stop(HIGH);
    net.startStream();
}
static void cmd_STOP_CONT(char **)
{
    continious_mode_start_stop(LOW);
    Debug.print("CMD stop_cnt - user requested stop");
    net.stopStream();
}
static void cmd_SPI_SR(char **args, const char *orig)
{
    if (!C || !args || !*args)
    {
        send_error("spi rd/sr - missing arguments");
        return;
    }

    char *tok = next_tok(args);                 // target M/S/B
    if (!tok)
    {
        send_error("spi rd/sr - missing target (M|S|B)");
        return;
    }
    char target = *tok;
    if (target!='M' && target!='S' && target!='B')
    {
        char out[96];
        snprintf(out,sizeof(out),
                 "spi rd/sr - bad target '%c', expected M,S,B", target);
        send_error(out);
        return;
    }

    tok = next_tok(args);                       // length
    if (!tok)
    {
        send_error("spi rd/sr - missing length");
        return;
    }
    char *endptr = nullptr;
    uint32_t len = strtoul(tok, &endptr, 0);
    if (*endptr || len==0 || len>256)
    {
        send_error("spi rd/sr - invalid length (1-256)");
        return;
    }

    uint8_t tx[256] = {0}, rx[256] = {0};
    for (uint32_t i = 0; i < len; ++i)
    {
        tok = next_tok(args);
        if (!tok)
        {
            send_error("spi rd/sr - too few data bytes");
            return;
        }
        tx[i] = (uint8_t) strtoul(tok, nullptr, 0);
    }

    // Safe SPI transaction (2 MHz for config then back to 8 MHz)
    spiTransaction_OFF();
    spiTransaction_ON(SPI_COMMAND_CLOCK);
    xfer(target, len, tx, rx);
    spiTransaction_OFF();
    spiTransaction_ON(SPI_NORMAL_OPERATION_CLOCK);

    // Echo the response
    send_reply(rx, len);
}

// Hard reboot - returns only after the MCU restarts
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
    spiTransaction_OFF();
    spiTransaction_ON(SPI_COMMAND_CLOCK);          // 2 MHz for config
    xfer(target, len, tx, rx);                   // full-duplex exchange
    spiTransaction_OFF();
    spiTransaction_ON(SPI_NORMAL_OPERATION_CLOCK); // back to 8 MHz

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





// FAMILY: USR  (prefix "usr")  - placeholder
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
void handle_USR(char **ctx, const char * /*orig*/)
{
    (void)ctx;
    // TODO: implement user-level commands
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

