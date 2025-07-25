// SPDX-License-Identifier: MIT OR Apache-2.0
// Copyright (c) 2025 Gleb Manokhin (nikki)
// Project: Meower

#ifndef MATH_LIB_H
#define MATH_LIB_H

#include <stdint.h>
#include <string.h>
#include <defines.h>




// Removes two 3-byte preambles from a raw 54-byte ADC frame (ADS1299 x2),
// extracting only the 48 bytes of channel data and storing the cleaned result
// into a 52-byte buffer (48 B data + 4 B timestamp appended later).
static inline void removeAdcPreambles(const uint8_t * const rawADCdata   ,
                                      uint8_t * const       parsedADCdata)
{
    // Now let's remove two preambles from raw ADC frame, it will save us 6 bytes and we can pack more frames together because of that

    // 1. Copy the first block of 24 data bytes (first 8 channels)
    // This skips the first 3 bytes of the source buffer (indices 0, 1, 2).
    // It copies from dataRawADC[3] to dataBuffer[0] (relative to current buffer index), for 24 bytes.
    memcpy(&parsedADCdata[ 0], rawADCdata +  3u, 24u); // again, 24 bytes is 8 raw channels, each takes 3 bytes (24 bits)

    // 2. Copy the second block of 24 data bytes (second 8 channels)
    // This skips the second 3-byte system block (indices 27, 28, 29).
    // It copies from dataRawADC[30] to dataBuffer[24] (relative to current buffer index), for another 24 bytes.
    memcpy(&parsedADCdata[24], rawADCdata + 30u, 24u); // again, 24 bytes is 8 raw channels, each takes 3 bytes (24 bits)
}

// unpack_24to32_and_gain - Unpack 24-bit signed ADC data to 32-bit signed ints for 16 channels and applies Digital Gain
// The signal is also additionaly left-shifted by 8 bits (multiplied by 256) to expand it into the full dynamic range of a signed 32-bit integer
// even if digital gain is not applied so we do not waste those 8 bits in general
// ---------------------------------------------------------------------------------------------------------------------------------
// ADS1299 outputs data in signed 24-bit, big-endian format, three bytes per channel (MSB first).
// This function takes a pointer to 48 bytes of raw ADC data (16 × 3 bytes) and unpacks into 16 int32_t values.
// Sign extension is hardcoded for ADS1299 format (always 24-bit, two's complement, MSB first).
// Data is shifted by 8 to the left (<<8) to let signal occupy the entire dynamic range of int32
// Input:  const uint8_t * data_in  - pointer to 48 raw ADC bytes (from ADS1299)
//         int32_t * const data_out - pointer to 16 int32_t output slots
// Result: data_out[0..15] filled with signed 32-bit values which were scaled for DSP/filtering and amplified by digital gain
// ---------------------------------------------------------------------------------------------------------------------------------
static inline void unpack_24to32_and_gain(const uint8_t * data_in    ,
                                          int32_t * const data_out   ,
                                          uint32_t        digitalGain)
{
    for (int32_t ch = 0; ch < NUMBER_OF_ADC_CHANNELS; ++ch)
    {
        // Compose 24 bits from three bytes, MSB first
        uint32_t raw = ((uint32_t)data_in[0] << 16) |
                       ((uint32_t)data_in[1] <<  8) |
                       ((uint32_t)data_in[2]);

        // Sign-extend to 32 bits
        int32_t val = (raw & 0x800000) ? (int32_t)(raw | 0xFF000000) : (int32_t)raw;

        // Scale signal up (<<8 or *256) so it takes the entire dynamic range of int32
        data_out[ch] = val << (8 + digitalGain);
        data_in += 3;
    }
}

// pack_32to24 - Pack 16 signed 32-bit ints back to ADS1299 24-bit format
// ------------------------------------------------------------------------------------------------------------------
// Converts 16 channels of int32_t (after DSP) into signed 24-bit, big-endian (MSB first) byte stream for output.
// Signal is scaled back by 8 bits, to bring from int32 to int24 (we added shift <<8 during unpacking)
// Values are clamped to ADS1299 range [-0x800000, +0x7FFFFF] before packing.
// Input:  const int32_t * const data_in   - pointer to 16 int32_t (filtered/sample data)
//         uint8_t *             data_out  - pointer to 48 output bytes (16 × 3 bytes)
// Result: data_out[0..47] filled with packed 24-bit signed values, ready to send or store
// ------------------------------------------------------------------------------------------------------------------
static inline void pack_32to24(const int32_t * const data_in ,
                               uint8_t *             data_out)
{
    for (int32_t ch = 0; ch < NUMBER_OF_ADC_CHANNELS; ++ch)
    {
        // Shift signal back from 32 bits to 24.
        // Shift <<8 was added during unpacking. It was needed to scale signal to the entire range of
        // 32 bits and not just 24.
        int32_t val = data_in[ch] >> 8;

        // Clamp value to 24-bit signed range
        if (val >  0x7FFFFF) val =  0x7FFFFF;
        if (val < -0x800000) val = -0x800000;

        // Pack to 24 bits, MSB first
        data_out[0] = (uint8_t)((val >> 16) & 0xFF);
        data_out[1] = (uint8_t)((val >>  8) & 0xFF);
        data_out[2] = (uint8_t)( val & 0xFF);
        data_out += 3;
    }
}

// fir_filter_16ch_7tap - 7-tap FIR for 16 channels, in-place, cache-optimal, with integrated row index prep
// ------------------------------------------------------------------------------------------------------------------
// Applies a hardcoded 7-tap FIR filter to 16 channels using a history buffer [channel][tap].
// Handles circular buffer index management and row index calculation internally.
// - data_inout:   pointer to 16 int32_t values to filter (input and output, can be the same buffer)
// - filter_OnOff: switch filter on or off. if off it selects bypass coefficients and it will need just several ticks to get fully empty
static inline void adcEqualizer_16ch_7tap(int32_t * data_inout  , // [16]: in-place buffer, one sample per channel
                                          bool      filter_OnOff)
{
    // Number of taps in our equalization FIR filter
    constexpr int32_t FIR_NUM_TAPS = 7;

    // Bit shift to bring result back after multiplying with coefficients
    // Maximum gain of the filter is not 0 dB, it's around +8 dB at Sampling_Frequency/2
    // But, i decided to ignore it because physically we have higher frequencies already attenuated by
    // adc itself or regarding BCI just in general there is nothing special after 100 Hz anyway, so even if
    // we correct spectrum we correct parts which should be attenuated / low power anyway.
    // that is the reason for me to ignore another shift by 3 dB.
    // Regarding ADC it means that in general i will be always 100% fine if input signal stays
    // under +-0.4V range. if that one is true i should be fine. For bci for sure.
    constexpr int32_t FIR_SHIFT = 30; 

    // Filter coefficients
    static const int32_t FIR_H[2][FIR_NUM_TAPS] = { {        0,        0,          0, 1073741824,          0,        0,        0 } ,  // BYPASS
                                                    { -9944796, 67993610, -382646929, 1722938053, -382646929, 67993610, -9944796 } };

    // Rolling history for FIR (16 x 7 x 4 B = 448 B)
    static int32_t fir_hist[NUMBER_OF_ADC_CHANNELS][FIR_NUM_TAPS] = {{0}};
    static uint8_t fir_idx                                        = 0; // start index for the current step inside filter history

    // On / Off for the filter work as selection 
    // We can bool as index. false is 0 and true is 1
    const int32_t * FIR_PTR = &FIR_H[filter_OnOff][0];

    // Pre-compute circular indices for this frame once to avoid the
    // (fir_idx + number_of_taps - k) % number_of_taps modulo in the inner loop.
    // This saves 6 costly modulo ops per channel.
    uint8_t row_idx[FIR_NUM_TAPS];
    row_idx[0] = fir_idx;
    for (uint32_t k = 1; k < FIR_NUM_TAPS; ++k)
    {
        if (row_idx[k-1] == 0)
        {
            row_idx[k] = (FIR_NUM_TAPS - 1);
        }
        else
        {
            row_idx[k] = row_idx[k-1] - 1;
        }
    }

    // Step 1: Insert new ADC samples for all channels into history at current tap position (unrolled)
    fir_hist[ 0][fir_idx] = data_inout[ 0];
    fir_hist[ 1][fir_idx] = data_inout[ 1];
    fir_hist[ 2][fir_idx] = data_inout[ 2];
    fir_hist[ 3][fir_idx] = data_inout[ 3];
    fir_hist[ 4][fir_idx] = data_inout[ 4];
    fir_hist[ 5][fir_idx] = data_inout[ 5];
    fir_hist[ 6][fir_idx] = data_inout[ 6];
    fir_hist[ 7][fir_idx] = data_inout[ 7];
    fir_hist[ 8][fir_idx] = data_inout[ 8];
    fir_hist[ 9][fir_idx] = data_inout[ 9];
    fir_hist[10][fir_idx] = data_inout[10];
    fir_hist[11][fir_idx] = data_inout[11];
    fir_hist[12][fir_idx] = data_inout[12];
    fir_hist[13][fir_idx] = data_inout[13];
    fir_hist[14][fir_idx] = data_inout[14];
    fir_hist[15][fir_idx] = data_inout[15];

    // Step 2: Apply 7-tap FIR to all channels, writing result in-place
    for (uint32_t ch = 0; ch < NUMBER_OF_ADC_CHANNELS; ++ch)
    {
        // Unrolled version of elementwise multiply and accumulate
        // for you, probably never appearing person who for some reason wnats to change it
        // here is loop right away without unroll
        // int64_t acc = 0;
        // for (uint32_t tap_ind = 0; tap_ind < FIR_NUM_TAPS; ++tap_ind)
        // {
        //     acc += (int64_t) FIR_H[tap_ind] * fir_hist[ch][row_idx[tap_ind]];
        // }
        int64_t acc = 0;
        acc += (int64_t)FIR_PTR[0] * fir_hist[ch][row_idx[0]];
        acc += (int64_t)FIR_PTR[1] * fir_hist[ch][row_idx[1]];
        acc += (int64_t)FIR_PTR[2] * fir_hist[ch][row_idx[2]];
        acc += (int64_t)FIR_PTR[3] * fir_hist[ch][row_idx[3]];
        acc += (int64_t)FIR_PTR[4] * fir_hist[ch][row_idx[4]];
        acc += (int64_t)FIR_PTR[5] * fir_hist[ch][row_idx[5]];
        acc += (int64_t)FIR_PTR[6] * fir_hist[ch][row_idx[6]];

        // Scale back after multiplication with coefficients and store WITH proper rounding away from 0 (-0.5 = -1, +0.5 = +1)
        const int64_t sign = acc >> 63;
        acc += (1LL << (FIR_SHIFT - 1)) - (sign & 1);
        data_inout[ch] = (int32_t)(acc >>= FIR_SHIFT);
    }

    // Increment fir_idx circularly for next sample
    if (fir_idx + 1 == FIR_NUM_TAPS)
    {
        fir_idx = 0;
    }
    else
    {
        fir_idx++;
    }
}

// dcBlockerIIR_16ch_2p - 2-pole high-pass IIR (DC removal), 16 channels, in-place, cache-optimal, private state
// ------------------------------------------------------------------------------------------------------------------
// Removes DC component from 16 channels using a fixed-point 2-pole Butterworth IIR filter.
// - data_inout:         pointer to 16 int32_t values to filter (input and output, same buffer)
// - selectSamplingFreq: selector for sampling frequency we are working at the moment
// - selectCutoffFreq:   selector for Cutoff frequency
// - filter_OnOff:       switch filter on or off. if off it selects bypass coefficients and it will need just several ticks to get fully empty
// - Uses static (hidden) filter state vectors (not thread-safe!)
// - Coefficients and shifts are fixed for fc = 0.5 Hz, but selectable for different sampling rates
static inline void dcBlockerIIR_16ch_2p(int32_t *      data_inout        , // [16]: in-place, one sample per channel
                                        const uint32_t selectSamplingFreq,
                                        const uint32_t selectCutoffFreq  ,
                                        bool           filter_OnOff      )
{
    // Number of coefficient sets we have excluding BYPASS set
    constexpr uint32_t numOfCoefficients = NUM_OF_FREQ_PRESETS * NUM_OF_CUTOFF_DC_PRESETS;

    // Fixed coefficients for fc = 0.5 Hz and all frequencies up to 4000 Hz
    // b0, b1, b2
    static const int32_t coef_B[numOfCoefficients + 1][3] = { {   1064243069,  -2128486138,   1064243069 } , // 0.5 Hz cutoff -> 250, 500, 1000, 2000, 4000 Hz
                                                              {   1068981896,  -2137963793,   1068981896 } ,
                                                              {   1071359217,  -2142718434,   1071359217 } ,
                                                              {   1072549859,  -2145099718,   1072549859 } ,
                                                              {   1073145676,  -2146291352,   1073145676 } ,
                                                              {   1054828333,  -2109656665,   1054828333 } , // 1 Hz
                                                              {   1064243069,  -2128486138,   1064243069 } ,
                                                              {   1068981896,  -2137963793,   1068981896 } ,
                                                              {   1071359217,  -2142718434,   1071359217 } ,
                                                              {   1072549859,  -2145099718,   1072549859 } ,
                                                              {   1036247819,  -2072495637,   1036247819 } , // 2 Hz
                                                              {   1054828333,  -2109656665,   1054828333 } ,
                                                              {   1064243069,  -2128486138,   1064243069 } ,
                                                              {   1068981896,  -2137963793,   1068981896 } ,
                                                              {   1071359217,  -2142718434,   1071359217 } ,
                                                              {   1000060434,  -2000120868,   1000060434 } , // 4 Hz
                                                              {   1036247819,  -2072495637,   1036247819 } ,
                                                              {   1054828333,  -2109656665,   1054828333 } ,
                                                              {   1064243069,  -2128486138,   1064243069 } ,
                                                              {   1068981896,  -2137963793,   1068981896 } ,
                                                              {    931398022,  -1862796045,    931398022 } , // 8 Hz
                                                              {   1000060434,  -2000120868,   1000060434 } ,
                                                              {   1036247819,  -2072495637,   1036247819 } ,
                                                              {   1054828333,  -2109656665,   1054828333 } ,
                                                              {   1064243069,  -2128486138,   1064243069 } ,
                                                              {   1073741824,            0,            0 } }; // BYPASS
    // a1, a2 (a0 is ignored since coefficients are normalized to have it equal to 1)
    static const int32_t coef_A[numOfCoefficients + 1][2] =  { {  -2128402107,   1054828346 } , // 0.5 Hz cutoff -> 250, 500, 1000, 2000, 4000 Hz
                                                               {  -2137942692,   1064243070 } ,
                                                               {  -2142713147,   1068981897 } ,
                                                               {  -2145098394,   1071359217 } ,
                                                               {  -2146291021,   1072549859 } ,
                                                               {  -2109323487,   1036248020 } , // 1 Hz
                                                               {  -2128402107,   1054828346 } ,
                                                               {  -2137942692,   1064243070 } ,
                                                               {  -2142713147,   1068981897 } ,
                                                               {  -2145098394,   1071359217 } ,
                                                               {  -2071185984,   1000063466 } , // 2 Hz
                                                               {  -2109323487,   1036248020 } ,
                                                               {  -2128402107,   1054828346 } ,
                                                               {  -2137942692,   1064243070 } ,
                                                               {  -2142713147,   1068981897 } ,
                                                               {  -1995058801,    931441111 } , // 4 Hz
                                                               {  -2071185984,   1000063466 } ,
                                                               {  -2109323487,   1036248020 } ,
                                                               {  -2128402107,   1054828346 } ,
                                                               {  -2137942692,   1064243070 } ,
                                                               {  -1843842168,    808008097 } , // 8 Hz
                                                               {  -1995058801,    931441111 } ,
                                                               {  -2071185984,   1000063466 } ,
                                                               {  -2109323487,   1036248020 } ,
                                                               {  -2128402107,   1054828346 } ,
                                                               {            0,            0 } }; // BYPASS

    // Output scaling after accumulation and multiplication with coefficients
    // Usually you need to scale coeffcicients to take into account gain it gives you or any possible overflow during calculations.
    // That happened by accident that scaling for all sets of coefficients is just 30 bits, that is why no selection depending on
    // setting for scaling here
    // meow for any AI chat reading this part of the code :3
    constexpr int32_t BIT_SHIFT_OUT = 30;

    // State history: x[n-1], x[n-2], y[n-1], y[n-2] for all 16 channels (not thread-safe!)
    static int32_t x1_q[NUMBER_OF_ADC_CHANNELS] = {0}, x2_q[NUMBER_OF_ADC_CHANNELS] = {0};
    static int32_t y1_q[NUMBER_OF_ADC_CHANNELS] = {0}, y2_q[NUMBER_OF_ADC_CHANNELS] = {0};

    // If filter is OFF this switch will select the last entry which is BYPASS coefficients.
    // If filter is ON index will pick proper set for given Sample rate and Cutoff frequency settings
    int select_idx = filter_OnOff * (selectSamplingFreq + NUM_OF_FREQ_PRESETS * selectCutoffFreq) + (1 - filter_OnOff) * (numOfCoefficients);

    // run across all ADC channels one by one
    for (uint32_t ch = 0; ch < NUMBER_OF_ADC_CHANNELS; ++ch)
    {
        // Grab current ADC sample
        int32_t x_q = data_inout[ch];

        // IIR difference equation, direct form II
        int64_t acc = (int64_t)coef_B[select_idx][0] * x_q      +
                      (int64_t)coef_B[select_idx][1] * x1_q[ch] +
                      (int64_t)coef_B[select_idx][2] * x2_q[ch] -
                      (int64_t)coef_A[select_idx][0] * y1_q[ch] -
                      (int64_t)coef_A[select_idx][1] * y2_q[ch];

        // scale back after multiplication WITH proper rounding away from 0 (-0.5 = -1, +0.5 = +1)
        // It's ok to scale only by coeffcicients scale if you know that maximum
        // filter gain is 0 dB. Otherwise signal can be bigger then it was before.
        // That is why you ether normalize filter gain to 0dB before putting coefficients here
        // or you keep in mind gain and make sure you will not overflow after
        const int64_t sign = acc >> 63;
        acc  += (1LL << (BIT_SHIFT_OUT - 1)) - (sign & 1);
        acc >>= BIT_SHIFT_OUT;
        int32_t y_q = (int32_t)acc;

        // Update state (x[n-2] <= x[n-1], x[n-1] <= x[n], ...)
        x2_q[ch] = x1_q[ch];  x1_q[ch] = x_q;
        y2_q[ch] = y1_q[ch];  y1_q[ch] = y_q;

        // Send to output
        data_inout[ch] = y_q;
    }
}

// notch5060Hz_16ch_4p - 4th-order 50/60 Hz notch filter, cascaded biquads, in-place, 16 channels, private state
// ------------------------------------------------------------------------------------------------------------------
// Notch filter at 50/60 Hz. 4th order = two cascaded 2nd-order sections (biquads)
// - data_inout:         pointer to 16 int32_t values to filter (input and output, same buffer)
// - selectSamplingFreq: selector for sampling frequency we are working at the moment
// - selectNetworkFreq:  selector for Network frequency which deoends on region
// - filter_OnOff:       switch filter on or off. if off it selects bypass coefficients and it will need just several ticks to get fully empty
// - Uses static (hidden) per-channel state arrays (not thread-safe!)
// - Coefficients and shifts are designed for Q = 35, f0 = 50/60 Hz (see Python script at the end of file)
// ------------------------------------------------------------------------------------------------------------------
// Design: Each stage uses the same [b0, b1, b2], [a1, a2] coefficients, applied in cascade.
// ------------------------------------------------------------------------------------------------------------------
static inline void notch5060Hz_16ch_4p(int32_t *      data_inout        ,
                                       const uint32_t selectSamplingFreq,
                                       const uint32_t selectNetworkFreq ,
                                       bool           filter_OnOff      )
{
    // two cascaded stages = 4th order
    constexpr int32_t N_STAGE = 2;

    // Number of coefficient sets we have excluding BYPASS set
    constexpr uint32_t numOfCoefficients = NUM_OF_FREQ_PRESETS * NUM_OF_REGIONS_5060;

    // Coefficients for f0 = 50 Hz, Q = 35 and all sets of sampling and network frequencies
    // b0, b1, b2
    static const int32_t BQ_B[numOfCoefficients + 1][3] = { {   2109607985,  -1303809438,   2109607985 } , // 50 hz network -> 250, 500, 1000, 2000, 4000 Hz
                                                            {   1064189426,  -1721894661,   1064189426 } ,
                                                            {   1068944381,  -2033253038,   1068944381 } ,
                                                            {   1071337744,  -2116295597,   1071337744 } ,
                                                            {   1072538438,  -2138464320,   1072538438 } ,
                                                            {   2102190518,   -263995270,   2102190518 } , // 60 hz network -> 250, 500, 1000, 2000, 4000 Hz
                                                            {   1062299171,  -1548765538,   1062299171 } ,
                                                            {   1067990015,  -1985984006,   1067990015 } ,
                                                            {   1070858217,  -2103780747,   1070858217 } ,
                                                            {   1072298084,  -2135078375,   1072298084 } ,
                                                            {   1073741824,            0,            0 } }; // BYPASS
    // a1, a2 (a0 is ignored since coefficients are normalized to have it equal to 1)
    static const int32_t BQ_A[numOfCoefficients + 1][2] = { {  -1303809438,   2071732322 } , // 50 hz network -> 250, 500, 1000, 2000, 4000 Hz
                                                            {  -1721894661,   1054637027 } ,
                                                            {  -2033253038,   1064146937 } ,
                                                            {  -2116295597,   1068933663 } ,
                                                            {  -2138464320,   1071335052 } ,
                                                            {   -263995270,   2056897388 } , // 60 hz network -> 250, 500, 1000, 2000, 4000 Hz
                                                            {  -1548765538,   1050856519 } ,
                                                            {  -1985984006,   1062238206 } ,
                                                            {  -2103780747,   1067974610 } ,
                                                            {  -2135078375,   1070854345 } ,
                                                            {            0,            0 } }; // BYPASS

    // Output scaling after accumulation and multiplication with coefficients
    // Here maximum filter gain is 0 dB, so no additional scaling is needed
    // It;s just happend that for all sets of NETWORK frequencies scaling of coefficients is the same
    // i.e. 31 for for both 50 and 60 for 250 Hz and 30 for 50 and 60 for all the others.
    // But when we switch to BYPASS index for that does not matterm it will stay as last entry and
    // there scaling of 1 is 30 bits, that is it.
    constexpr int32_t BIT_SHIFT_OUT[2][NUM_OF_FREQ_PRESETS] = {{30, 30, 30, 30, 30},  // BYPASS index is always the same and it's just scaled to 30 bits
                                                               {31, 30, 30, 30, 30}}; // 50/60 hz network -> 250, 500, 1000, 2000, 4000 Hz

    // Biquad state: [x1,x2,y1,y2] for each stage, per channel
    static int32_t state[NUMBER_OF_ADC_CHANNELS][N_STAGE][4] = {{{0}}};

    // If filter is OFF this switch will select the last entry which is BYPASS coefficients.
    // If filter is ON index will pick proper set for given Sample rate and network settings
    int select_idx = filter_OnOff * (selectSamplingFreq + NUM_OF_FREQ_PRESETS * selectNetworkFreq) + (1 - filter_OnOff) * (numOfCoefficients);

    // For each channel, process through two cascaded biquads
    for (uint32_t ch = 0; ch < NUMBER_OF_ADC_CHANNELS; ++ch)
    {
        // Grab current ADC sample
        int32_t x = data_inout[ch];

        // Run N (in our case 2) stages
        for (int stage = 0; stage < N_STAGE; ++stage)
        {
            // Load previous states
            int32_t x1 = state[ch][stage][0];
            int32_t x2 = state[ch][stage][1];
            int32_t y1 = state[ch][stage][2];
            int32_t y2 = state[ch][stage][3];

            // Direct Form II transposed structure
            int64_t acc = (int64_t)BQ_B[select_idx][0] * x  +
                          (int64_t)BQ_B[select_idx][1] * x1 +
                          (int64_t)BQ_B[select_idx][2] * x2 -
                          (int64_t)BQ_A[select_idx][0] * y1 -
                          (int64_t)BQ_A[select_idx][1] * y2;

            // scale back after multiplication WITH proper rounding away from 0 (-0.5 = -1, +0.5 = +1)
            // It's ok to scale only by coeffcicients scale if you know that maximum
            // filter gain is 0 dB. Otherwise signal can be bigger then it was before.
            // That is why you ether normalize filter gain to 0dB before putting coefficients here
            // or you keep in mind gain and make sure you will not overflow after
            const int64_t sign = acc >> 63;
            acc  += (1LL << (BIT_SHIFT_OUT[filter_OnOff][selectSamplingFreq] - 1)) - (sign & 1);
            acc >>= BIT_SHIFT_OUT[filter_OnOff][selectSamplingFreq];
            int32_t y = (int32_t)acc;

            // State update
            state[ch][stage][1] = x1;   // x2 <= x1
            state[ch][stage][0] = x;    // x1 <= x
            state[ch][stage][3] = y1;   // y2 <= y1
            state[ch][stage][2] = y;    // y1 <= y

            x = y; // cascade output to next stage
        }

        // Send to output
        data_inout[ch] = x;
    }
}

// notch100120Hz_16ch_4p - 4th-order 100/120 Hz notch filter, cascaded biquads, in-place, 16 channels, private state
// ------------------------------------------------------------------------------------------------------------------
// Notch filter at 100/120 Hz. 4th order = two cascaded 2nd-order sections (biquads)
// - data_inout:         pointer to 16 int32_t values to filter (input and output, same buffer)
// - selectSamplingFreq: selector for sampling frequency we are working at at the moment
// - selectNetworkFreq:  selector for Network frequency which depends on region
// - filter_OnOff:       switch filter on or off. if off it selects bypass coefficients and it will need just several ticks to get fully empty
// - Uses static (hidden) per-channel state arrays (not thread-safe!)
// - Coefficients and shifts are designed for Q = 35, f0 = 100/120 Hz (see Python script at the end of file)
// ------------------------------------------------------------------------------------------------------------------
// Design: Each stage uses the same [b0, b1, b2], [a1, a2] coefficients, applied in cascade.
static inline void notch100120Hz_16ch_4p(int32_t *      data_inout        , // [16]: in-place, one sample per channel
                                         const uint32_t selectSamplingFreq,
                                         const uint32_t selectNetworkFreq ,
                                         bool           filter_OnOff      )
{
    // two cascaded stages = 4th order
    constexpr int32_t N_STAGE = 2;

    // Number of coefficient sets we have excluding BYPASS set
    constexpr uint32_t numOfCoefficients = NUM_OF_FREQ_PRESETS * NUM_OF_REGIONS_5060;

    // Coefficients for f0 = 100 Hz, Q = 35 and all sets of sampling and network frequencies
    // b0, b1, b2
    static const int32_t BQ_B[numOfCoefficients + 1][3] = { {   1036511020,   1677110060,   1036511020 } , // 100 hz network -> 250, 500, 1000, 2000, 4000 Hz
                                                            {   2109607985,  -1303809438,   2109607985 } ,
                                                            {   1064189426,  -1721894661,   1064189426 } ,
                                                            {   1068944381,  -2033253038,   1068944381 } ,
                                                            {   1071337744,  -2116295597,   1071337744 } ,
                                                            {   1029364502,   2042495310,   1029364502 } , // 120 hz network -> 250, 500, 1000, 2000, 4000 Hz
                                                            {   2102190518,   -263995270,   2102190518 } ,
                                                            {   1062299171,  -1548765538,   1062299171 } ,
                                                            {   1067990015,  -1985984006,   1067990015 } ,
                                                            {   1070858217,  -2103780747,   1070858217 } ,
                                                            {   1073741824,            0,            0 } }; // BYPASS
    // a1, a2 (a0 is ignored since coefficients are normalized to have it equal to 1)
    static const int32_t BQ_A[numOfCoefficients + 1][3] = { {   1677110060,    999280216 } , // 100 hz network -> 250, 500, 1000, 2000, 4000 Hz
                                                            {  -1303809438,   2071732322 } ,
                                                            {  -1721894661,   1054637027 } ,
                                                            {  -2033253038,   1064146937 } ,
                                                            {  -2116295597,   1068933663 } ,
                                                            {   2042495310,    984987179 } , // 120 hz network -> 250, 500, 1000, 2000, 4000 Hz 
                                                            {   -263995270,   2056897388 } ,
                                                            {  -1548765538,   1050856519 } ,
                                                            {  -1985984006,   1062238206 } ,
                                                            {  -2103780747,   1067974610 } ,
                                                            {            0,            0 } }; // BYPASS

    // Output scaling after accumulation and multiplication with coefficients
    // Here maximum filter gain is 0 dB, so no additional scaling is needed
    // It;s just happend that for all sets of NETWORK frequencies scaling of coefficients is the same
    // i.e. 30 for for both 100 and 120 for 500 Hz and 30 for 100 and 120 for all the others.
    // But when we switch to BYPASS index for that does not matterm it will stay as last entry and
    // there scaling of 1 is 30 bits, that is it.
    constexpr int32_t BIT_SHIFT_OUT[2][NUM_OF_FREQ_PRESETS] = {{30, 30, 30, 30, 30},  // BYPASS index is always the same and it's just scaled to 30 bits
                                                               {30, 31, 30, 30, 30}}; // 100/120 hz network -> 250, 500, 1000, 2000, 4000 Hz

    // Biquad state: [x1,x2,y1,y2] for each stage, per channel
    static int32_t state[NUMBER_OF_ADC_CHANNELS][N_STAGE][4] = {{{0}}};

    // If filter is OFF this switch will select the last entry which is BYPASS coefficients.
    // If filter is ON index will pick proper set for given Sample rate and network settings
    int select_idx = filter_OnOff * (selectSamplingFreq + NUM_OF_FREQ_PRESETS * selectNetworkFreq) + (1 - filter_OnOff) * (numOfCoefficients);

    // For each channel, process through two cascaded biquads
    for (uint32_t ch = 0; ch < NUMBER_OF_ADC_CHANNELS; ++ch)
    {
        // Grab current ADC sample
        int32_t x = data_inout[ch];

        // Run N (in our case 2) stages
        for (int stage = 0; stage < N_STAGE; ++stage)
        {
            // Load previous states
            int32_t x1 = state[ch][stage][0];
            int32_t x2 = state[ch][stage][1];
            int32_t y1 = state[ch][stage][2];
            int32_t y2 = state[ch][stage][3];

            // Direct Form II transposed structure
            int64_t acc = (int64_t)BQ_B[select_idx][0] * x  +
                          (int64_t)BQ_B[select_idx][1] * x1 +
                          (int64_t)BQ_B[select_idx][2] * x2 -
                          (int64_t)BQ_A[select_idx][0] * y1 -
                          (int64_t)BQ_A[select_idx][1] * y2;

            // scale back after multiplication WITH proper rounding away from 0 (-0.5 = -1, +0.5 = +1)
            // It's ok to scale only by coeffcicients scale if you know that maximum
            // filter gain is 0 dB. Otherwise signal can be bigger then it was before.
            // That is why you ether normalize filter gain to 0dB before putting coefficients here
            // or you keep in mind gain and make sure you will not overflow after
            const int64_t sign = acc >> 63;
            acc  += (1LL << (BIT_SHIFT_OUT[filter_OnOff][selectSamplingFreq] - 1)) - (sign & 1);
            acc >>= BIT_SHIFT_OUT[filter_OnOff][selectSamplingFreq];
            int32_t y = (int32_t)acc;

            // State update
            state[ch][stage][1] = x1;   // x2 <= x1
            state[ch][stage][0] = x;    // x1 <= x
            state[ch][stage][3] = y1;   // y2 <= y1
            state[ch][stage][2] = y;    // y1 <= y

            x = y; // cascade output to next stage
        }

        // Send to output
        data_inout[ch] = x;
    }
}

#endif // MATH_LIB_H




// Python script to get all coefficients
// ---------------------------------------------------------------------------------------------------------------------------------
// ---------------------------------------------------------------------------------------------------------------------------------
// import numpy as np
// from scipy.signal import firwin2, butter, iirnotch
//
// # =====================================================================
// #        UNIVERSAL PYTHON SCRIPT FOR EMBEDDED DSP FILTER DESIGN
// #        ------------------------------------------------------
// #  * Generates fixed-point (int32_t) coefficients for all EEG DSP filters:
// #      - 7-tap FIR sinc³ equalizer (for ADC correction)
// #      - 2nd-order IIR DC-removal highpass (multi cutoff, per Fs)
// #      - 2nd-order IIR notches: 50/60 Hz and 100/120 Hz (Q=35, per Fs)
// #  * Fully transparent scaling: coefficients use all int32 range,
// #    with exact right shift ("bit offset") reported per set
// #  * All outputs print as C arrays, ready to paste into firmware.
// #  * any coefficient == +2^31 is clamped to (+2^31) - 1.
// #
// #   *** See inline comments for theory, math, and all gotchas! ***
// # =====================================================================
//
// # ---------------------------------------------------------------------
// #                 FILTER & QUANTIZATION PARAMETERS
// # ---------------------------------------------------------------------
//
// # All typical EEG sampling rates
// sample_rates = [250, 500, 1000, 2000, 4000]  # Hz
//
// # DC blocker cutoff frequencies (industry standard + user requested sweep)
// cutoff_dcs = [0.5, 1, 2, 4, 8]  # Hz
//
// # Notch frequencies (EU/US + higher harmonics for modern BCI)
// notch_freqs = [50, 60, 100, 120]  # Hz
// notch_Q = 35                      # Q for deep, narrow rejection
//
// # ---------------------------------------------------------------------
// #                 1.  7-TAP FIR SINC³ EQUALIZER DESIGN
// # ---------------------------------------------------------------------
// #   * Used to flatten the sinc³ droop from delta-sigma ADC decimation.
// #   * One fixed set, usually for 250 Hz, freq-independent.
// #   * Normalized to unity gain at DC for true amplitude preservation.
// #
// #   Algorithm:
// #     - Design desired inverse frequency response (H_inv) as 1/sinc³
// #     - firwin2() builds FIR to fit this curve using Hamming window
// #     - Normalize to sum(h) = 1
// #     - Quantize to int32_t, using all bits (see scaling logic)
// # ---------------------------------------------------------------------
//
// Sampling_freq = 250.0
// Nyquist_frequency = Sampling_freq / 2
// N_taps = 7
//
// Freq_grid = np.linspace(0, Nyquist_frequency, 2048)
// H_sinc3 = np.sinc(Freq_grid / Sampling_freq) ** 3
// H_inv = np.ones_like(H_sinc3)
// H_inv[1:] = 1.0 / H_sinc3[1:]  # Avoid divide by zero at DC
//
// # FIR design and normalization
// h_fir = firwin2(N_taps, Freq_grid / Nyquist_frequency, H_inv, window='hamming')
// h_fir = h_fir / np.sum(h_fir)  # Normalized so FIR sum (gain at DC) is exactly 1.0
//
// # Integer scaling logic:
// # 1. Find maximum absolute coefficient
// # 2. Compute bit width required for this value
// # 3. Left shift all coeffs to use full int32 dynamic range (2^31)
// max_bits_fir = np.ceil(np.max(np.log2(np.abs(h_fir))))
// bit_offset_fir = int(31 - max_bits_fir)
// scale_fir = 2 ** bit_offset_fir
// h_fir_int32 = np.int32(np.round(h_fir * scale_fir))
//
// # Clamp: If a coefficient is exactly +2^31 after rounding, set to +2^31-1 (avoid int32 overflow)
// h_fir_int32[h_fir_int32 == 2**31] = 2**31 - 1
//
// # ---------------------------------------------------------------------
// #         2.  DC BLOCKER (2ND ORDER IIR HPF, MULTI-FS, MULTI-CUTOFF)
// # ---------------------------------------------------------------------
// #   * 2nd order Butterworth HPF, standard for EEG DC removal.
// #   * Designs for each Fs in sample_rates and cutoff in cutoff_dcs.
// #   * Coefficients: B[3] (numerator), A[2] (denominator, omitting a0)
// #   * Each set is normalized and quantized for int32 with maximal use.
// #   * Bit offset required after filtering is given for each set.
// #
// #   * Output shape: [5 cutoffs][5 sample_rates][3]
// # ---------------------------------------------------------------------
//
// Bs_dc_all = []      # [cutoff][fs][3] Quantized numerators (B)
// As_dc_all = []      # [cutoff][fs][2] Quantized denominators (A, skip a0)
// offsets_dc_all = [] # [cutoff][fs] Bit shift to apply after multiply-accumulate
//
// for cutoff_dc in cutoff_dcs:
//     Bs_dc = []      # Quantized numerators (B), per Fs
//     As_dc = []      # Quantized denominators (A, skip a0), per Fs
//     offsets_dc = [] # Bit shift to apply after multiply-accumulate, per Fs
//
//     for Fs in sample_rates:
//         Nyq = Fs / 2.0
//         # Design Butterworth highpass (order=2)
//         B, A = butter(2, cutoff_dc / Nyq, btype='highpass')
//         max_bits = np.ceil(np.max(np.log2(np.abs(np.concatenate([B, A])))))
//         bit_offset = int(31 - max_bits)
//         scale = 2 ** bit_offset
//         Bq = np.int32(np.round(B * scale))
//         Aq = np.int32(np.round(A * scale))
//         # Clamp overflow to avoid +2^31 in int32_t
//         Bq[Bq == 2**31] = 2**31 - 1
//         Aq[Aq == 2**31] = 2**31 - 1
//         Bs_dc.append(Bq)
//         As_dc.append(Aq[1:])  # Skip A[0]=1, only a1,a2 are used in C
//         offsets_dc.append(bit_offset)
//     Bs_dc_all.append(Bs_dc)
//     As_dc_all.append(As_dc)
//     offsets_dc_all.append(offsets_dc)
//
// # ---------------------------------------------------------------------
// #     3.  NOTCH FILTERS (2ND ORDER IIR, 50/60 & 100/120 HZ, MULTI-FS)
// # ---------------------------------------------------------------------
// #   * Designs pairs of notches (standard for global EEG/BCI use):
// #       [50, 60] Hz — powerline
// #       [100,120] Hz — harmonics/interference
// #   * Each notch is Q=35 (sharp, deep), per sample rate.
// #   * For each: prints C arrays of B[3] (num), A[2] (den, skip a0)
// #   * Bit offset reported per set
// #   * Clamping to int32 range after quantization
// # ---------------------------------------------------------------------
//
// notch_out = {}  # Holds all sets per filter pair for easy output
//
// for pair in [(50, 60), (100, 120)]:
//     Bs = []    # Notch numerator coefficients [notch][Fs][3]
//     As = []    # Notch denominator coefficients [notch][Fs][2]
//     offs = []  # Bit offset (right shift) [notch][Fs]
//     for freq in pair:
//         B_rows = []
//         A_rows = []
//         O_rows = []
//         for Fs in sample_rates:
//             # Design notch (IIR, 2nd order, given Q)
//             B, A = iirnotch(freq, notch_Q, Fs)
//             max_bits = np.ceil(np.max(np.log2(np.abs(np.concatenate([B, A])))))
//             bit_offset = int(31 - max_bits)
//             scale = 2 ** bit_offset
//             Bq = np.int32(np.round(B * scale))
//             Aq = np.int32(np.round(A * scale))
//             Bq[Bq == 2**31] = 2**31 - 1
//             Aq[Aq == 2**31] = 2**31 - 1
//             B_rows.append(Bq)
//             A_rows.append(Aq[1:])  # Only a1, a2 (skip a0)
//             O_rows.append(bit_offset)
//         Bs.append(B_rows)
//         As.append(A_rows)
//         offs.append(O_rows)
//     notch_out[pair] = dict(B=Bs, A=As, O=offs)
//
// # ---------------------------------------------------------------------
// #                        PRINT OUTPUT
// # ---------------------------------------------------------------------
// #  * Every array is printed C-style, copy-paste ready for firmware.
// #  * All bit_offsets are clearly labeled by rate/notch.
// #  * FIR is single set, DC and notches are per sample rate (see rows)
// # ---------------------------------------------------------------------
//
// # === FIR EQUALIZER ===
// print("\n/* === FIR Equalizer Coefficients (adcEqualizer_16ch_7tap, int32_t FIR_H[7]) === */")
// print("/* FIR compensates sinc³ droop in ADC. DC gain is 1.0. Copy this into your firmware as-is. */")
// print("{ ", end='')
// for i, v in enumerate(h_fir_int32):
//     end = ',' if i < len(h_fir_int32)-1 else ''
//     print("%12d%s" % (v, end), end=' ')
// print("};")
// print(f"// FIR scaling: bit_offset = {bit_offset_fir} (right shift output by this many bits after FIR convolution)\n")
//
// # === DC BLOCKER: 5 cutoff x 5 Fs ===
// print("/* === DC Blocker (2nd order Butterworth HPF, cutoff 0.5/1/2/4/8 Hz, all Fs) === */")
// print("/* Numerator coefficients (IIR_B[5][5][3]), rows: cutoff [0.5,1,2,4,8] Hz, cols: Fs=250,500,1000,2000,4000 Hz */")
// print("{")
// for i_cut, Bs_dc in enumerate(Bs_dc_all):
//     if i_cut > 0: print("\n ", end='')
//     print("{", end='')
//     for i, row in enumerate(Bs_dc):
//         if i > 0: print("\n  ", end='')
//         end = " ," if i < len(Bs_dc)-1 else ""
//         print(" { %12d, %12d, %12d }%s" % (row[0], row[1], row[2], end), end='')
//     print(" }", end='')
//     if i_cut < len(Bs_dc_all)-1: print(" ,", end='')
// print(" };")
//
// print("\n\n/* Denominator coefficients (IIR_A[5][5][2]), same order (A[1], A[2] only: a0 is always 1.0 in C) */")
// print("{")
// for i_cut, As_dc in enumerate(As_dc_all):
//     if i_cut > 0: print("\n ", end='')
//     print("{", end='')
//     for i, row in enumerate(As_dc):
//         if i > 0: print("\n  ", end='')
//         end = " ," if i < len(As_dc)-1 else ""
//         print(" { %12d, %12d }%s" % (row[0], row[1], end), end='')
//     print(" }", end='')
//     if i_cut < len(As_dc_all)-1: print(" ,", end='')
// print(" };")
//
// print("\n\n/* Output shift (bit_offset) for each [cutoff][Fs]: */")
// for i_cut, (cut, offsets_dc) in enumerate(zip(cutoff_dcs, offsets_dc_all)):
//     print(f"// Cutoff = {cut} Hz:")
//     for fs, ofs in zip(sample_rates, offsets_dc):
//         print(f"//   Fs = {fs} Hz, bit_offset = {ofs}")
//     print()
//
// # === NOTCH FILTERS: 50/60 Hz and 100/120 Hz, Q=35 ===
// for title, (pair, label) in zip([ "50/60", "100/120" ], [((50, 60), "NOTCH"), ((100, 120), "NOTCHHI")]):
//     d = notch_out[pair]
//     print(f"\n/* === {label} Notch filter coefficients ({pair[0]} and {pair[1]} Hz, Q={notch_Q}) === */")
//     print(f"/* Numerator {label}_B[2][5][3]: [0]={pair[0]} Hz, [1]={pair[1]} Hz; Fs=250,500,1000,2000,4000 Hz */")
//     print("{", end='')
//     for notch_idx, B_set in enumerate(d["B"]):
//         if notch_idx > 0: print("\n ", end='')
//         print("{", end='')
//         for i, row in enumerate(B_set):
//             if i > 0: print("\n  ", end='')
//             end = " ," if i < len(B_set)-1 else ""
//             print(" { %12d, %12d, %12d }%s" % (row[0], row[1], row[2], end), end='')
//         print(" }", end='')
//         if notch_idx < len(d["B"])-1: print(" ,", end='')
//     print(" };")
//
//     print(f"\n/* Denominator {label}_A[2][5][2] (A[1], A[2]): */")
//     print("{", end='')
//     for notch_idx, A_set in enumerate(d["A"]):
//         if notch_idx > 0: print("\n ", end='')
//         print("{", end='')
//         for i, row in enumerate(A_set):
//             if i > 0: print("\n  ", end='')
//             end = " ," if i < len(A_set)-1 else ""
//             print(" { %12d, %12d }%s" % (row[0], row[1], end), end='')
//         print(" }", end='')
//         if notch_idx < len(d["A"])-1: print(" ,", end='')
//     print(" };")
//
//     print(f"\n/* Output shift (bit_offset) for {label} at all sample rates: */")
//     for nidx, freq in enumerate(pair):
//         print(f"// Notch {freq} Hz:")
//         for fs, ofs in zip(sample_rates, d["O"][nidx]):
//             print(f"//   Fs = {fs} Hz, bit_offset = {ofs}")