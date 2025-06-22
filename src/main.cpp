#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <SPI.h>
#include <helpers.h>
#include <defines.h>
#include <spi_lib.h>
#include <messages_lib.h>
#include <net_manager.h>
#include <math_lib.h>




// Initialize variables and classes we need for main loop
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
NetManager net;
SPIClass spi(SPI);                 // Use the default SPI instance on the ESP32-C3

// Classes
Battery_Sense BatterySense(PIN_BAT_SENSE, BAT_SCALE, BAT_SAMPLING_MS); // defaults: GPIO-4, scaling 0.00428, 1000 ms (1 s) between battery sampling
Blinker       LEDheartBeat(PIN_LED      , LED_ON_MS, LED_PERIOD_MS  ); // GPIO-20, 100 ms ON, 5000 ms period

// FreeRTOS handles
static TaskHandle_t  adcTaskHandle = nullptr;
static QueueHandle_t adcFrameQue   = nullptr; // ONE processed ADC packet (frames+timestamps); battery added later in transmission task
QueueHandle_t        cmdQue        = nullptr;
static MsgContext    msgCtx;

// continuous reading mode state and maximum time we will wait before reseting mode if anything happened and ADC give no data back
static volatile bool continuousReading = false;

// Timmer counter for main loop, so we can control how often it's executed. Default is 1 time per 50 ms
static uint32_t previousTime = 0; // timer for main loop

// Digital gain. If signal you analyze uses maximum +-0.2V or any other value you better to
// amplify it so it uses the entire dynamic range of 24 bits.
// Gain made as bit shoft operation so we can get 1, 2, 4, 8, 16 and so on times which means 0, 1, 2, 3 bit shift and so on
// GAIN WILL SATURATE AND CORRUPT SIGNAL IF DYNAMIC RANGE AFTER GAIN IS BIGGER THAN sint32
volatile uint32_t g_digitalGain = 0; // Number of bits to shift, i.e. s = s << g_digitalGain

// Select between 50-100Hz (0) and 60-120Hz modes for notch filters. Mostly useful for sample rates upt to 500 Hz,
// but still works upto 4000 Hz
// [50-100 60-120] Hz
// [     0      1] select number
volatile uint32_t g_selectNetworkFreq = 0;

// Select for current working sampling frequency. It's needed for filters to set proper coefficients
// [250 500 1000 2000 4000] Hz
// [  0   1    2    3    4] select number
static volatile uint32_t g_selectSamplingFreq = 0; // Sampling rate selector index

// Select cutOff frequency for DC filter.
// So, just in case, 0.5 Hz second order IIR for DC falls apart even with 32 bit coefficients and 32 bit signal.
// I've tried a lot of things and scaling signal by 8 bits for processing to always have 32 bit occupied and
// adding digital gain to push it even firther if signal itself never uses more then 16 bits for example, but still
// there are limits and 0.5 Hz at 4000 Hz sample rate is not stable and does not work really well - spkies can become permanent like
// resonator, you dont delete DC, you just inver it instead.
// So here you are - several cutoff frequencies you can choose from. Hope at least someone find it useful.
// [0.5 1 2 4 8] Hz
// [  0 1 2 3 4] select number
volatile uint32_t g_selectDCcutoffFreq = 0;

// One full ADC frame size with timestamp included at the end in BYTES
constexpr size_t ADC_FULL_FRAME_SIZE = ADC_PARSED_FRAME + TIMESTAMP_SIZE;

// Example: ADC_PACKET_BYTES = 28 -> 52 × 28 = 1 456 B. Battery (4 Bytes) is
constexpr size_t ADC_PACKET_BYTES = ADC_FULL_FRAME_SIZE * FRAMES_PER_PACKET;

// One complete UDP payload: (ADC_FULL_FRAME_SIZE = 52 B) × 28 frames + 4-byte battery = 1 460 B
constexpr size_t UDP_PACKET_BYTES = (ADC_FULL_FRAME_SIZE * FRAMES_PER_PACKET) + Battery_Sense::DATA_SIZE;

// ADC equalizer master switch. The SYS commands FILTER_EQUALIZER_ON / FILTER_EQUALIZER_OFF toggle it at run time.
volatile bool g_adcEqualizer = true;

// IIR (DC removal) master switch. The SYS commands FILTER_DC_ON / FILTER_DC_OFF toggle it at run time.
volatile bool g_removeDC = true;

// IIR 50/60 Hz notch filter master switch. The SYS commands FILTER_5060_ON / FILTER_5060_OFF toggle it at run time.
volatile bool g_block5060Hz = true;

// IIR 100/120 Hz notch filter master switch. The SYS commands FILTER_100120_ON / FILTER_100120_OFF toggle it at run time.
volatile bool g_block100120Hz = true;

// Global switch for all filters being ON or OFF
volatile bool g_filtersEnabled = true;




// Helpers
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
// Perform a full reset of the ADS1299 chip
//
// CHECK SEQUENCE IN DATASHEET, p.62, Figure 67. Initial Flow at Power-Up
//
// This function ensures a complete reset regardless of the previous pin states.
// ADCs will be reset to default state with sync between them, internal ref ON, 0 gain, 500 FPS and no bias.
// Sequence:
// - Set continuous mode flag to False, because we are performing full reset
// - Reset SPI clock to 2 MHz. We will reset chip only at 2 MHz clock, because it works unstable if we forse it to work at 8 right away. So we full reset first with low speed and only then push 4 Mhz or higher
// - Setting digital pins to low as it was asked in datasheet before reset
// - Setting PWDN and RESET low and then high to power up the chip (and keep it high, as requested).
// - Waiting for the power-up stabilization time.
// - RESET pulse low->high to reset the digital logic.
// - Waiting for the chip to initialize fully.
// - Get digital levels back to CS off and START off
// - Stop Continuous mode sending SDATAC message
// - Configure master to have reference signal inside on Config_3 to 0xE0
// - Configure master to send reference clock to slave and then slave to listen to it Config_1
// - Now slave should be fully on and we can configure internal reference Config_3 t0 0xE0 for both master and slave AGAIN and slave will behave as master
// - Setup testing signals to be generated internaly, to have 3.75 mV amplitude and period of 1 second
// - Setup all channels to be shorted to testing signal, with 0 gain, no SRB for any of them
void ads1299_full_reset()
{
    // We will use digitalWrite instead of WRITE_PERI_REG here since timings are not important.

    // Make sure continuous Mode is OFF, because we are doing full reset
    // ALSO, we do not care about proper procidure with messages, since we are pulling RESET and POWER DOWN pins LOW,
    // fully reseting ADCs. so we can just set continuous mode to false
    continuousReading = false; 

    // Stop SPI if it was running and start again at 2 MHz clock. Then we will stop it again and set working speed
    spiTransaction_OFF();               // stop SPI
    spiTransaction_ON(SPI_RESET_CLOCK); // start at 2 MHz

    // Based on datasheet all CS and START (it says all digital signals) should go LOW
    // Page 62, check diagramm
    digitalWrite(PIN_CS_MASTER, LOW);
    digitalWrite(PIN_CS_SLAVE , LOW);
    digitalWrite(PIN_START    , LOW);

    // Set PWDN and RESET low to fully stop ADCs
    digitalWrite(PIN_PWDN , LOW);
    digitalWrite(PIN_RESET, LOW);

    // Wait 150 ms for power-down stabilization
    delay(150); 

    // Set PWDN and RESET high to ensure the chip is powered up and remains so
    digitalWrite(PIN_PWDN , HIGH);
    digitalWrite(PIN_RESET, HIGH);

    // Wait 150 ms for power-up stabilization (datasheet says 2^18 of clocks which is around 132 ms, page 70, 11.1 Power-Up Sequencing)
    delay(150);

    // Transmit RESET pulse with length exceeding the minimum 2 clock cycles (page 70, 11.1 Power-Up Sequencing)
    digitalWrite(PIN_RESET, LOW);
    delayMicroseconds(10); // 10 us
    digitalWrite(PIN_RESET, HIGH);

    // Wait 1 ms exceeding the minimum 18 clock cycles (page 70, 11.1 Power-Up Sequencing)
    delay(1);

    // Pull CS back, but keep START LOW
    digitalWrite(PIN_CS_MASTER, HIGH);
    digitalWrite(PIN_CS_SLAVE , HIGH);
    digitalWrite(PIN_START    , LOW ); // this one is already LOW, but lets make it safe

    // Stop continuous data mode (SDATAC)
    // Datasheet - 9.5.3 SPI command definitions, p.40.
    {
        uint8_t SDATAC_mes = 0x11;
        uint8_t rx_mes     = 0; // just empty message, we do need any response here
        xfer('B', 1u, &SDATAC_mes, &rx_mes);
    }

    // We are using internal reference buffer so we have to set it right away becase by default
    // config is 0x60 abd it means turn off internal reference buffer
    // Configuration 3 - Reference and bias
    // bit 7                | 6        | 5        | 4         | 3                | 2                  | 1                      | 0 read only
    // use Power ref buffer | Always 1 | Always 1 | BIAS meas | BIAS ref ext/int | BIAS power Down/UP | BIAS sence lead OFF/ON | LEAD OFF status
    //              76543210
    //              X11YZMKR
    // Config_3 = 0b11100000; 0xE0
    {
        uint8_t Master_conf_3[3u] = {0x43, 0x00, 0xE0};
        uint8_t rx_mes[3u]        = {0}; // just empty message, we do need any response here
        xfer('B', 3u, Master_conf_3, rx_mes);
    }

    // Then we need to setup up clock for slave and update reference signal again, otherwise
    // slave is in different state comparing to master
    // Configuration 1 - Daisy-chain, reference clock, sample rate
    // bit 7        | 6                  | 5                 | 4        | 3        | 2   | 1   | 0
    // use Always 1 | Daisy-chain enable | Clock output mode | always 1 | always 0 | DR2 | DR1 | DR0
    //                   76543210
    //                   1XY10ZZZ
    // Master_conf_1 = 0b10110101; # Daisy ON, Clock OUT ON,  500 SPS - i moved it to 500 Hz to get better frequency response in range [0 - 100 Hz]. The reason is sigma delta adc 
    // Slave_conf_1  = 0b10010101; # Daisy ON, Clock OUT OFF, 500 SPS
    {
        // Master config
        uint8_t Master_conf_1[3u] = {0x41, 0x00, 0xB6};
        uint8_t rx_mes[3u]        = {0}; // just empty message, we do need any response here
        xfer('M', 3u, Master_conf_1, rx_mes);

        // Slave config
        uint8_t Slave_conf_1[3u] = {0x41, 0x00, 0x96};
        xfer('S', 3u, Slave_conf_1, rx_mes);

        // Set reference signal to base again, since slave was in what ever state so
        // after this config 3 messages they will be in similar modes again
        uint8_t Config_3[3u] = {0x43, 0x00, 0xE0};
        xfer('B', 3u, Config_3, rx_mes);
    }

    // Next I want to preset testing signals parameters - FOR BOTH ADCs
    // Test signal are generated internaly
    // Test signal amplitude 3.75 mV (2 × –(VREFP – VREFN) / 2400, Vwhere on this board VREFP is +4.5V and VREFN is 0 V)
    // Period of miander is 1 second
    // bit 7        | 6        | 5        | 4                   | 3        | 2                  | 1           0
    // use Always 1 | Always 1 | Always 0 | Test source ext/int | Always 0 | Test sig amplitude | Test sig freq
    //              76543210
    //              110X0YZZ
    //              11010101 Signal is gen internally, amplitude twice more than usual, pulses with 1 s period
    // Config_2 = 0b11010100
    {
        uint8_t Config_2[3u] = {0x42, 0x00, 0xD4};
        uint8_t rx_mes[3u]   = {0}; // just empty message, we do need any response here
        xfer('B', 3u, Config_2, rx_mes);
    }

    // Set all channels to normal mode (both positive and negative are needed for each channel) with 0 gain
    // Channels settings
    // bit 7                 | 6 5 4 | 3                | 2 1 0
    // use Power down On/Off | GAIN  | SRB2 open/closed | Channel input
    //                  76543210
    // Channel_conf = 0b00000101
    // We have 8 channels in each ADC and we assign default settings to all of them in pairs
    for (uint8_t ind = 0; ind < 8u; ind++)
    {
        uint8_t Config_Channels[3u] = { static_cast<uint8_t>(0x45 + ind), 0x00, 0x05 };
        uint8_t rx_mes[3u]          = {0}; // just empty message, we do need any response here
        xfer('B', 3u, Config_Channels, rx_mes);

        // wait for 1 ms
        delay(1);
    }

    // Reconfigure SPI frequency to working one
    spiTransaction_OFF();                          // stop SPI
    spiTransaction_ON(SPI_NORMAL_OPERATION_CLOCK); // start and normal working frequency (most stable i've seen is 8 MHz)
}

// Setting start signal for contious mode. Ether ON or OFF
void continious_mode_start_stop(uint8_t on_off)
{
    if (on_off == HIGH) // Start continuous mode
    {
        // Safe SPI transaction (2 MHz for config then back to 8 MHz)
        spiTransaction_OFF();
        spiTransaction_ON(SPI_RESET_CLOCK);

        // Before any start of the continious we must check board Sample Rate
        // which is at Config 1 which is to read is 0x21
        uint8_t tx_mex[3] = {0x21, 0x00, 0x00};
        uint8_t rx_mes[3] = {0};
        xfer('M', 3u, tx_mex, rx_mes);

        // Store Sampling Rate into global variable for filters
        switch (rx_mes[2] & 0x07)
        {
            case 6: g_selectSamplingFreq = 0; break; //  250 Hz
            case 5: g_selectSamplingFreq = 1; break; //  500 Hz
            case 4: g_selectSamplingFreq = 2; break; // 1000 Hz
            case 3: g_selectSamplingFreq = 3; break; // 2000 Hz
            case 2: g_selectSamplingFreq = 4; break; // 4000 Hz
        }

        // Turn ON start signal (pull it UP)
        digitalWrite(PIN_START, on_off);

        // Prepare RDATAC message and empty holder for receiving
        uint8_t RDATAC_mes = 0x10;
        xfer('B', 1u, &RDATAC_mes, rx_mes); // Send RDATAC

        // Back to fast clock
        spiTransaction_OFF();
        spiTransaction_ON(SPI_NORMAL_OPERATION_CLOCK);

        // Set continuous mode flag to True
        continuousReading = true;
    }
    else // Otherwise stop
    {
        // Prepare SDATAC message and empty holder for receiving
        uint8_t SDATAC_mes = 0x11;
        uint8_t rx_mes     = 0x00; // just empty message, we do need any response here

        // After SDATAC message we must wait 4 clocks, but since we have a small
        // delay before and after reading in xfer function we can ignore it
        // Safe SPI transaction (2 MHz for config then back to 8 MHz)
        spiTransaction_OFF();
        spiTransaction_ON(SPI_RESET_CLOCK);
        xfer('B', 1u, &SDATAC_mes, &rx_mes);
        spiTransaction_OFF();
        spiTransaction_ON(SPI_NORMAL_OPERATION_CLOCK);

        // Turn OFF start signal (pull it DOWN)
        digitalWrite(PIN_START, on_off);

        // Set continuous mode flag to False
        continuousReading = false;
    }
}

// Reads ONE complete command datagram from the queue.
// Returns the byte count (0 if none).  Mirrors the old signature so
// message_lib.cpp stays untouched.
int32_t udp_read(char* buf, size_t cap)
{
    if (!buf || cap == 0) return 0;
    if (xQueueReceive(cmdQue, buf, 0) == pdTRUE)
        return strnlen(buf, cap);
    return 0;
}




// TASKS
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
// DRDY interrupt for ADC task
// Called **automatically** the very moment the ADS1299’s DRDY pin makes a LOW transition
// (FALLING edge) – because in `setup()` you did:
//     attachInterrupt(PIN_DRDY, drdy_isr, FALLING);
//
// Timing constraints
// -------------------
// • DRDY goes LOW once per conversion (500 Hz → every 2 ms, 4 kHz → every 250 µs).
// • The ISR must finish extremely quickly (< 10–15 µs) so we do *not* read SPI here.
//   All heavy lifting is delegated to a FreeRTOS task; the ISR’s only job is to wake it.
//
void IRAM_ATTR drdy_isr() // IRAM_ATTR: place code in IRAM, not flash -> no cache miss
{
    // Prepare a flag that tells FreeRTOS whether a higher-priority task unblocked
    // hp == pdTRUE  ->  the scheduler should run immediately after this ISR
    // hp == pdFALSE ->  it can wait until the next tick
    BaseType_t hp = pdFALSE;

    // Atomically increments the “notification value” that belongs to adcTaskHandle (ADC task).
    // If that task was blocked on ulTaskNotifyTake(), it becomes Ready.
    // If the ADC task’s priority ≥ the one that was interrupted, hp is set to pdTRUE.
    vTaskNotifyGiveFromISR(adcTaskHandle, &hp); // A task notification is a built-in counting semaphore—lighter and 45 % faster than a classic xSemaphoreGiveFromISR().
    
    // Perform an *immediate* context switch only when necessary
    // (i.e. when the ADC task outranks whatever task was interrupted).
    // This means the ADC task can start poking the SPI bus within ~5 µs after DRDY fell.
    if (hp)
    {
        // portYIELD_FROM_ISR() tells FreeRTOS:
        // “when you exit the current exception frame, switch to the
        // highest-priority Ready task instead of returning to the interrupted task”
        portYIELD_FROM_ISR();
    }
    
    // On exit the CPU automatically re-enables interrupts and continues running
    // the selected task.
}

// ADC continuous frame pulling and Signal processing.
// Why like this? because then we do not have to pass data vectors from ADC to UDP task
// which were taking too much time and stallking device and cause at some points
// frame loss from wifi side (wifi task were to slow)
// The ADC task queues a single 52-byte frame to adcFrameQue.
// DSP packs FRAMES_PER_PACKET (N) frames and later hands the full datagram to the network task.
void IRAM_ATTR task_getADCsamplesAndPack(void*)
{
    // Prelocate tx empty data with zeros for ADC sample read (we are sending zeros and ADC gives us back samples)
    const uint8_t tx_mes[ADC_SAMPLES_FRAME] = {0};

    // Raw ADC data from SPI
    // we need it separetely to parse samle and remove two preambules from it, so we can have 48 bytes per one raw ADC frame instead of 54 
    static uint8_t rawADCdata[ADC_SAMPLES_FRAME];

    // Parsed ADC frame without preambs
    static uint8_t parsedADCdata[ADC_PARSED_FRAME];

    // Buffer to store ONE parsed ADC frame (preamble removed) with timestamp appended. size is ADC_FULL_FRAME_SIZE (52 B)
    static uint8_t dataBuffer[ADC_PACKET_BYTES];

    // Buffer for unpacked ADC samples from 24 to 32 bits which we will use for processing
    static int32_t dspBuffer[NUMBER_OF_ADC_CHANNELS] = {0};

    // We need to know if we were in continuous mode each loop.
    // If yes we just go as usual
    // If not and continuous mode started we must clean all internal buffers so data there is fresh
    bool wasReading = false;

    // Bytes counter - how many we already wrote and it also works as index.
    // First value is 0, then we move it by ADC_FULL_FRAME_SIZE, then again by ADC_FULL_FRAME_SIZE and so on
    uint32_t bytesWritten = 0u;

    // Start infinite loop
    for (;;) // Endless loop – a FreeRTOS task never returns.
    {
        // If we just started continuous mode we must clear all internal variables and buffers
        if (continuousReading && !wasReading)
        {
            ulTaskNotifyTake(pdTRUE, 0); // clear stale notify count

            // Reset cursor – next packet starts at byte 0
            bytesWritten = 0;
        }

        // store were we continuously reading or not for the next frame
        wasReading = continuousReading;
        
        uint32_t timeStamp = getTimer8us(); // 8us timer

        // Wait until ADC pulls DRDY down (adc samples are ready to read)
        // We will wait here forever
        ulTaskNotifyTake(pdTRUE       ,  // clear on exit
                         portMAX_DELAY); // no timeout, hangs for ever

        // Write timestamp (4 bytes) into the buffer at the end of the channel data for this frame.
        // - We use memcpy here (instead of casting uint8_t* to uint32_t*) because:
        //   (1) The offset into the buffer (bytesWritten + ADC_PARSED_FRAME) must be divisible by 4,
        //   (2) The base address of dataBuffer itself must also be 4-byte aligned.
        //   If either is not guaranteed, pointer casting is unsafe on some MCUs (may cause alignment faults).
        // - memcpy is always safe, even if alignment or buffer padding is not guaranteed.
        // - The timestamp sits directly after the 48 bytes of channel data, at offset +48 in each frame.
        // - Suitable for real-time use, provides low-latency timestamping.
        timeStamp = getTimer8us() - timeStamp; // 8us timer
        memcpy(&dataBuffer[bytesWritten + ADC_PARSED_FRAME], &timeStamp, sizeof(timeStamp));

        // If we are in continuous mode - do stuff if not - do nothing at all
        if (continuousReading)
        {
            // Get ADC samples
            // We are sending SPI messages with zeros to ADCs and ADCs give us back samples one by one in return
            // Here both master and slave should have Chip Select active
            xfer('B', ADC_SAMPLES_FRAME, tx_mes, rawADCdata);

            // Now lets remove two preambs from raw ADC frame, it will save us 6 bytes and we can pack more frames together because of that
            removeAdcPreambles(rawADCdata, parsedADCdata);

            // Unpack all smaple to 32 bits, left-shift by 8 bits (multiply by 256) to
            // let signal use full dynamic range of a signed 32-bit integer and apply digital gain.
            // It's needed to preserve as much dynamic range as possible.
            // I added constant 8 bit shoft after filters started to fall apart on higher sampling rates because
            // keeping signal at 24 bits without moving up and 31 bits coeefficients is just
            // not enough unfortunately
            // Unpack is also here outside of filters chain since we have digital gain, which means we have to run it every time.
            // Digital gain can help to reduce precision errors for filters and processing even more.
            // It's advised to use as high gain as possible if signal does not occupy the entire +-4.5V range (all 24 bits)
            unpack_24to32_and_gain(parsedADCdata, dspBuffer, g_digitalGain);

            // Filtering
            // BYPASS if global for all filters is OFF
            // --------------------------------------------------------------------------------------------
            adcEqualizer_16ch_7tap(dspBuffer,                                             g_adcEqualizer  && g_filtersEnabled); // if we need adc frequency responce equalizer - filter data using FIR with 7 taps
            dcBlockerIIR_16ch_2p  (dspBuffer, g_selectSamplingFreq, g_selectDCcutoffFreq, g_removeDC      && g_filtersEnabled); // Remove DC
            notch5060Hz_16ch_4p   (dspBuffer, g_selectSamplingFreq, g_selectNetworkFreq , g_block5060Hz   && g_filtersEnabled); // Notch filter for 50/60 Hz
            notch100120Hz_16ch_4p (dspBuffer, g_selectSamplingFreq, g_selectNetworkFreq , g_block100120Hz && g_filtersEnabled); // Notch filter for 100/120 Hz

            // Pack all samples back to 24 bits with scaling them back by 8 bits (>>8 or /256).
            // Shift by 8 was added to signal to occupy full dynamic range of int32 during unpacking
            pack_32to24(dspBuffer, parsedADCdata);

            // Copy one processed (or raw, if filters are off) ADC frame (16 channels × 24 bits = 48 bytes),
            // where the timestamp (4 bytes) has already been appended at the end in dataBuffer.
            // Each frame totals 52 bytes in the packet; memcpy writes only the 48 bytes of channel data here.
            memcpy(&dataBuffer[bytesWritten], // Write pointer for next frame in datagram
                   parsedADCdata,             // Source: 48 bytes of processed or raw channel data
                   ADC_PARSED_FRAME);         // Number of bytes to copy: 48 (no timestamp, just data)

            // Increment amount of writen bytes (which also means frames).
            // this way we can count and also move pointer so next ADC frame will be writen nicely right after this one.
            bytesWritten += ADC_FULL_FRAME_SIZE;

            // Is the data buffer now exactly full?
            if (bytesWritten >= ADC_PACKET_BYTES)
            {
                // Send one complete packet (ADC frames + time-stamps) to Wi-Fi task.
                // Battery voltage is merged in the UDP task just before transmission.
                xQueueSend(adcFrameQue,    // queue handle
                           dataBuffer,     // pointer to packet
                           0); // wait if both slots are full in que. It means if UDP never reads from que DSP will stay here forever. DSP is not allowed to write to que if que is full

                // Reset cursor – next packet starts at byte 0
                bytesWritten = 0;
            }
        }

        #ifdef DEBUG
            // test signal to see when our task got it done so you can see it on oscilloscope.
            // This is test signal, all chips selects are deactivated
            uint8_t ADC_data_out = 0;
            uint8_t dummyByte    = 0;
            xfer('T', 1, &dummyByte, &ADC_data_out);
        #endif
    }
}

// Data sender task
// This network task runs over Wi-Fi and doesn’t need to be hard real-time.
// Putting it in IRAM wastes space needed for critical routines.
// IRAM code runs without touching flash, but this task will go back to flash anyway.
// Flash fetches can be blocked during Wi-Fi or SPI1 use, causing unexpected delays.
// If the task lives in IRAM, those stalls can even crash or hang it.
// Keeping non-critical tasks in flash makes behavior more predictable.
// It also leaves IRAM free for ISRs and DSP loops that truly need zero-wait execution.
// Only put the fastest, most time-sensitive code into IRAM.
void task_dataTransmission(void*)
{
    // Pre-allocate buffer for several parsed and processed ADC frames
    // actually holds one full UDP datagram (N frames + battery)
    static uint8_t txBuf[UDP_PACKET_BYTES];

    // Start infinite loop
    for (;;) // Endless loop – a FreeRTOS task never returns.
    {

        // wait forever until DSP overwrites mailbox with a new set of processed frames
        xQueueReceive(adcFrameQue, txBuf, portMAX_DELAY);

        // Append the latest battery voltage (4-byte float)
        Battery_Sense::value_t vbatt = BatterySense.getVoltage();
        memcpy(&txBuf[ADC_PACKET_BYTES], &vbatt, Battery_Sense::DATA_SIZE);
        
        // Send if peer active
        if (net.wantStream())
            net.sendData(txBuf, UDP_PACKET_BYTES);
    }
}

// Main loop and Setup
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
// Setting up pins, wifi connection, reset ADC at the start of the board and initialize ADC and wifi tasks
void setup()
{
    // CONFIGURE SPI PINS
    pinMode(PIN_SCLK     , OUTPUT);
    pinMode(PIN_MOSI     , OUTPUT);
    pinMode(PIN_MISO     , INPUT );
    pinMode(PIN_DRDY     , INPUT ); // DATA-READY PIN or INT PIN
    pinMode(PIN_CS_UNUSED, OUTPUT);
    digitalWrite(PIN_CS_UNUSED, HIGH); // Deactivate default (unused) CS pin

    // CONFIGURE NEW CS PINS FOR MASTER & SLAVE ADS1299
    pinMode(PIN_CS_MASTER, OUTPUT);
    pinMode(PIN_CS_SLAVE , OUTPUT);
    digitalWrite(PIN_CS_MASTER, HIGH); // Deactivate master CS by default
    digitalWrite(PIN_CS_SLAVE , HIGH); // Deactivate slave CS by default

    // START PIN ---
    pinMode(PIN_START, OUTPUT);
    digitalWrite(PIN_START, LOW);

    // CONFIGURE REST AND POWER DOWN PINS
    pinMode(PIN_PWDN , OUTPUT);
    pinMode(PIN_RESET, OUTPUT);
    digitalWrite(PIN_PWDN , HIGH); // Power down chip if LOW
    digitalWrite(PIN_RESET, HIGH); // Reset chip if LOW

    // INITIALIZE SPI
    // On ESP32-C3, you can override the default pins with:
    spi.begin(PIN_SCLK, PIN_MISO, PIN_MOSI, PIN_CS_UNUSED);

    // Now lets handle spi handle to SPI lib and helpers
    spi_init(&spi);

    // GET RID OF TRI-STATE FOR MISO, so signal does not decay slowly if last bit was equal to 1
    pinMode(PIN_MISO, INPUT_PULLDOWN);

    // Configure LED pin
    pinMode(PIN_LED, OUTPUT);          // make it an output
    digitalWrite(PIN_LED, LOW);        // start OFF

    WiFi.mode(WIFI_MODE_STA);          // station-only; turns off the soft-AP
    WiFi.setSleep(true);               // let the modem nap between DTIM beacons
    

    wifi_config_t cfg;
    esp_wifi_get_config(WIFI_IF_STA, &cfg);
    cfg.sta.listen_interval = 1;
    esp_wifi_set_config(WIFI_IF_STA, &cfg);
 
    net.begin(WIFI_SSID, WIFI_PASSWORD, UDP_PORT_CTRL, UDP_PORT_PC_DATA);

    esp_wifi_set_ps(WIFI_PS_MAX_MODEM); // deepest power-save level while connected

    // hand sockets to the message parser
    msgCtx.udp              = net.udp();   // raw WiFiUDP
    msgCtx.spi              = &spi;
    msgCtx.udp_ip           = UDP_IP;
    msgCtx.udp_port_pc_ctrl = UDP_PORT_CTRL;
    msg_init(&msgCtx);

    // Just to be 100 % sure – locks the CPU clock to 160 MHz.
    // So, if clock here is not 80 Mhz anymore - reason to push 160 was to make sure, that
    // ADC and DSP task is so fast i still have a lot of overhead before next sample appears. And
    // based on what i've seen when i felt that processing is 99% ready - 160 MHz uses just maybe 30 mW more
    // in mormal mode. at 4000 Hz and max packing of data (28 frames) board was using 470 mW which is still
    // around 8+ hours of lifetime on 1100 mAh lipo. And for normal use it's 380 - 400 mW which is 10+ hours.
    // And for anyone who wants to use 4000 Hz - i don't think they need 10+ hours anyway.
    setCpuFrequencyMhz(160);

    // Right at the end we have to reset ADC so it's at default state.
    ads1299_full_reset();

    // FreeRTOS resources
    // 5-slot queue that holds exactly 5 complete UDP datagrams.
    //
    // NOTE – This queue is not a read/write-collision guard.  The kernel
    //        already serialises access. The extra slots simply adds head-
    //        room: the ADC task keeps running even if the queue is FULL.
    //        it means ADC and processing are safe and sender task should
    //        catch up.
    //
    // Timing math:
    //   • One 28-frame packet @500 SPS = 56 ms.
    //   • 5 slots -> 280 ms breathing room before the ADC task must wait.
    //
    // Typical brief Wi-Fi stall or “floof-storm”:
    //   1) UDP task copies packet from slot 0 (queue locked while copying).
    //   2) Lock releases -> higher-priority ADC pre-empts and refills slot 0.
    //   3) If the stall persists, ADC writes the next packet into slot 1, 2, 3, 4.
    //      Queue now full -> ADC never blocks and continue the processing skipping putting frames inside
    //   4) UDP later drains slot 0, then slot 1 and so on – FIFO order guaranteed by
    //      FreeRTOS, no extra bookkeeping needed.
    //   5) Queue empty -> both tasks resume normal cadence; occasional
    //      overlaps handled transparently with zero frame loss.
    //
    // Blocking rules:
    //   - ADC and DSP task never blocks. If sender task is too slow and adc task cant write it will skip writing right away
    //   - Data Transmittion task blocks until at least one item is inside the que and if ADC/DSP task is running
    adcFrameQue = xQueueCreate(5,                 // 5 items (two full packets)
                               ADC_PACKET_BYTES); // size of one ADC frames with time stamps – battery not included

    // Que for command from PC
    cmdQue = xQueueCreate(8,               // up to 8 in-flight commands
                          CMD_BUFFER_SIZE);   

    // High-priority task.
    // Reads every DRDY pulse, removes preambula from ADC data, processes samples, assembles FRAMES_PER_PACKET ADC frames with time stamps,
    // then sends data to the queue.
    xTaskCreatePinnedToCore(task_getADCsamplesAndPack, // entry point
                            "adc",                     // task name for debugging
                            2048,                      // stack (bytes) BASED ON REAL TEST WITH HIGH SPEED ADC USES AROUND 500 BYTES ONLY EVEN WITH 28 FRAMES PACKED
                            nullptr,                   // no task argument
                            configMAX_PRIORITIES - 1,  // almost top priority
                            &adcTaskHandle,            // handle needed by the ISR
                            0);                        // run on core 0

    // Lower-priority task: blocks on the queue, adds battery voltage, transmits packet via Wi-Fi/BLE.
    // Separated from the ADC and DSP tasks -> so slow networking cannot stall sampling and processing.
    xTaskCreatePinnedToCore(task_dataTransmission,    // entry point
                            "sender",                 // task name
                            2048,                     // larger stack BASED ON REAL TEST WITH HIGH SPEED SENDER USES AROUND 500 BYTES ONLY EVEN WITH 28 FRAMES PACKED
                            nullptr,                  // no task argument
                            configMAX_PRIORITIES - 2, // just below the ADC task
                            nullptr,                  // we don’t need the handle later
                            0);                       // keep both tasks on the same core

    // DRDY line goes HIGH -> LOW at the end of every ADC conversion.
    // The ISR merely notifies the ADC task; all heavy SPI I/O happens in task context.
    attachInterrupt(PIN_DRDY,  // GPIO number
                    drdy_isr,  // ISR function (in IRAM)
                    FALLING ); // trigger on falling edge

    // Start ADC so it tries to send data right away without any other need so config or what ever
    // Signal will be square wave with 1s period
    continious_mode_start_stop(HIGH);
}

// This loop will repeat again and again forever - yeah yeah, i wasn't supa used to esp programming :3
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
void loop()
{
    // Wait until between last loop start and this one exactely given amount of ms passed. Default is 50 ms
    uint32_t currentTime    = millis();                                           // get current time
    uint32_t timeDifference = MAIN_LOOP_PERIOD_MS - (currentTime - previousTime); // compare how much time passed since last loop and get how long to wait to get needed delay

    // If delay more than 0 ms AND less than period we need - wait.
    // Otherwise save current time and proceed
    if ((timeDifference > 0) && (timeDifference < MAIN_LOOP_PERIOD_MS)) // just 
    {
        delay(timeDifference);
    }
    else
    {
        previousTime = currentTime;
    }

    // LED heartbeat (writes to physical pin only on transitions)
    net.driveLed(LEDheartBeat);  // set pattern if state changed
    LEDheartBeat.update();       // update pin (non-blocking)
    BatterySense.update();       // Check battery voltage
    net.update();                // Beacon for getting IP address & housekeeping  
    
    // Always check for inbound control commands
    parse_and_execute_command();
}