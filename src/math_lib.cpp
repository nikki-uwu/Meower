// #include <math_lib.h>

// // Generate fixed-point IIR filter coefficients for Butterworth HPF or Notch
// // ------------------------------------------------------------------------------
// // Input:
// //   fs         - sampling frequency (e.g. 250 Hz)
// //   f0         - cutoff (for high-pass) or notch center frequency
// //   order      - filter order (typically 2)
// //   Q          - quality factor for notch filters; set to 0.0 for Butterworth HPF
// //   B_out[3]   - output numerator coefficients (Q1.31 fixed-point)
// //   A_out[2]   - output denominator coefficients (Q1.31 fixed-point)
// //   shift_out  - output shift value to scale result safely back down to int32
// //
// // Notes:
// //   - Only supports 2nd-order Butterworth HPF or Notch
// //   - Output format is compatible with DSP task IIR branch
// //   - Coefficients scaled to signed 32-bit and shift is returned

// void design_iir_filter(float fs,
//                        float f0,
//                        int order,
//                        float Q,
//                        int32_t *B_out,
//                        int32_t *A_out,
//                        int32_t *shift_out)
// {
//     // Step 1: Normalize frequency
//     float nyquist = fs * 0.5f;
//     float norm_f  = f0 / nyquist;

//     float Bf[3] = {0}, Af[3] = {0};

//     // Notch filter via biquad (IIR notch)
//     if (Q > 0.0f)
//     {
//         float omega = 2.0f * M_PI * norm_f;
//         float alpha = sinf(omega) / (2.0f * Q);

//         Bf[0] = 1.0f;
//         Bf[1] = -2.0f * cosf(omega);
//         Bf[2] = 1.0f;

//         Af[0] = 1.0f + alpha;
//         Af[1] = -2.0f * cosf(omega);
//         Af[2] = 1.0f - alpha;

//         // normalize B by Af[0], and same for Af
//         for (int i = 0; i < 3; ++i) {
//             Bf[i] /= Af[0];
//             Af[i] /= Af[0];
//         }
//     }

//     // High-pass Butterworth filter (2nd order assumed)
//     // This path is taken when Q = 0.0f
//     else
//     {
//         float ita = 1.0f / tanf(M_PI * norm_f);
//         float q = sqrtf(2.0f);

//         float norm = 1.0f / (1.0f + q * ita + ita * ita);
//         Bf[0] = norm;
//         Bf[1] = -2.0f * norm;
//         Bf[2] = norm;

//         Af[0] = 1.0f; // always 1
//         Af[1] = 2.0f * norm * (ita * ita - 1.0f);
//         Af[2] = norm * (1.0f - q * ita + ita * ita);
//     }

//     // Step 2: Fixed-point scaling
//     float max_coeff = 0.0f;
//     for (int i = 0; i < 3; ++i)
//     {
//         float absB = fabsf(Bf[i]);
//         float absA = (i < 2) ? fabsf(Af[i+1]) : 0.0f; // skip Af[0] (always 1)
//         if (absB > max_coeff) max_coeff = absB;
//         if (absA > max_coeff) max_coeff = absA;
//     }

//     // Add 1-bit guard margin
//     float max_val = max_coeff * 2.0f;
//     float log2val = log2f(max_val);
//     int shift = 31 - (int)ceilf(log2val);
//     if (shift < 0) shift = 0;

//     int64_t scale = (int64_t)1 << shift;

//     for (int i = 0; i < 3; ++i)
//         B_out[i] = (int32_t)lrintf(Bf[i] * scale);

//     for (int i = 0; i < 2; ++i)
//         A_out[i] = (int32_t)lrintf(Af[i+1] * scale); // skip Af[0] which is 1.0

//     *shift_out = shift;
// }




// // Scale float IIR coefficients into signed int32_t with shared Q1.31 shift
// // ---------------------------------------------------------------------------------------------------------------------------------
// // ---------------------------------------------------------------------------------------------------------------------------------
// // Purpose:
// //   Given two float arrays (A[] and B[]) representing IIR filter coefficients,
// //   this function finds the largest absolute value among them, computes a shared
// //   safe shift, and converts all values into int32_t using a Q1.31-style scale.
// //
// // Inputs:
// //   A_in[]         - pointer to float array of denominator coefficients (Af)
// //   B_in[]         - pointer to float array of numerator coefficients (Bf)
// //   len            - number of coefficients in each array (both must be same length)
// //   safety_margin  - guard multiplier. use powers of 2. 1 means no guard. 2 means we protect by 1 bit, 4 means
// //                    by 2 bitd and so on. But in general for this you never need more than 2. Use ether 1 or 2
// //
// // Outputs:
// //   A_scaled[]     - output scaled int32 array for A coefficients
// //   B_scaled[]     - output scaled int32 array for B coefficients
// //   shift_out      - how many bits we scaled up by (to be used for fixed-point DSP)
// //
// // Why this works:
// //   - Q1.31 format stores numbers in the range [-1.0, +1.0) in signed int32
// //   - Scaling all coefficients by 2^shift preserves their ratios while fitting
// //     into the representable range
// //   - We leave 1 bit of headroom (by default) to avoid rounding-induced overflow
// void scale_coef_to_32_bits(const float* A_in,
//                            const float* B_in,
//                            int len,
//                            float safety_margin,
//                            int32_t* A_scaled,
//                            int32_t* B_scaled,
//                            int32_t* shift_out)
// {
//     float max_coeff = 0.0f;

//     // Step 1: Find the largest absolute value among all A and B coefficients
//     for (int i = 0; i < len; ++i)
//     {
//         float absA = fabsf(A_in[i]);
//         float absB = fabsf(B_in[i]);

//         if (absA > max_coeff) max_coeff = absA;
//         if (absB > max_coeff) max_coeff = absB;
//     }

//     // Step 2: Apply safety margin (e.g., 2.0f = +1 bit of rounding headroom)
//     float padded_val = max_coeff * safety_margin;

//     // Step 3: Find how many bits this padded value would require
//     float log2val = log2f(padded_val);

//     // Step 4: Convert to final shift - for Q1.31 max safe shift is 31
//     int shift = 31 - (int)ceilf(log2val);
//     if (shift < 0) shift = 0;

//     int64_t scale = (int64_t)1 << shift;
//     *shift_out = shift;

//     // Step 5: Convert all values to scaled int32
//     for (int i = 0; i < len; ++i)
//     {
//         A_scaled[i] = (int32_t)lrintf(A_in[i] * scale);
//         B_scaled[i] = (int32_t)lrintf(B_in[i] * scale);
//     }
// }


// // Design a native 4th-order IIR notch filter
// // ---------------------------------------------------------------------------------------------------------------------------------
// // ---------------------------------------------------------------------------------------------------------------------------------
// // Purpose:
// //   Designs a real-valued 4th-order IIR notch (band-stop) filter centered at `f0` with quality factor `Q`,
// //   returned in fixed-point Q1.31 format.
// //
// // Why native 4th order?
// //   - Unlike runtime cascades of 2x biquads, this directly generates a combined transfer function
// //     so that all coefficients can be pipelined into a single-stage 4th-order processor.
// //   - Scaling is done *after* convolution for maximum numeric fidelity.
// //
// // Inputs:
// //   fs        - sampling frequency (e.g. 250 Hz)
// //   f0        - notch center frequency (e.g. 50 or 100 Hz)
// //   Q         - quality factor (must be > 0.0). Higher Q = narrower notch
// //
// // Outputs:
// //   B_out[6]  - output numerator coefficients (Q1.31, B[0..5])
// //   A_out[5]  - output denominator coefficients (Q1.31, A[1..5]) — A[0] is always 1.0, not stored
// //   shift_out - bit shift needed to safely return from Q1.31 fixed-point to int32
// void design_iir_notch_order4(float fs,
//                              float f0,
//                              float Q,
//                              int32_t* B_out,
//                              int32_t* A_out,
//                              int32_t* shift_out)
// {
//     // Step 1: Build two identical 2nd-order biquads in float
//     float nyquist = fs * 0.5f;
//     float norm_f  = f0 / nyquist;
//     float omega   = 2.0f * M_PI * norm_f;
//     float alpha   = sinf(omega) / (2.0f * Q);
//     float cosw    = cosf(omega);

//     float b1[3] = {1.0f, -2.0f * cosw, 1.0f};
//     float a1[3] = {1.0f + alpha, -2.0f * cosw, 1.0f - alpha};

//     float b2[3], a2[3];
//     memcpy(b2, b1, sizeof(b1));
//     memcpy(a2, a1, sizeof(a1));

//     // Normalize each biquad to have a[0] = 1.0
//     for (int i = 0; i < 3; ++i)
//     {
//         b1[i] /= a1[0];
//         a1[i] /= a1[0];
//         b2[i] /= a2[0];
//         a2[i] /= a2[0];
//     }

//     // Step 2: Multiply biquads to form 4th-order system
//     float Bf[6] = {0}, Af[6] = {0};
//     for (int i = 0; i < 3; ++i)
//         for (int j = 0; j < 3; ++j)
//             Bf[i + j] += b1[i] * b2[j];      // convolution for numerator

//     for (int i = 1; i < 3; ++i)               // skip a[0] = 1.0
//         for (int j = 1; j < 3; ++j)
//             Af[i + j - 1] += a1[i] * a2[j];   // convolution for denominator A[1..5]

//     // --- Step 3: Scale to Q1.31 format using shared logic ---
//     // Af[0] is A[1] here, so we pass Af and Bf both of length 6
//     scale_coef_to_32_bits(Af, Bf, 6, 2.0f, A_out, B_out, shift_out);

//     // Final result: A_out[5] = A[1..5], B_out[6] = B[0..5], shift_out = Q shift
// }


// // External utility to scale float coefficients into Q1.31 with shared shift
// extern void scale_coef_to_32_bits(const float* A_in, const float* B_in,
//                                   int len, float safety_margin,
//                                   int32_t* A_scaled, int32_t* B_scaled,
//                                   int32_t* shift_out);

// // Design a 2nd-order Butterworth high-pass IIR filter
// // ---------------------------------------------------------------------------------------------------------------------------------
// // ---------------------------------------------------------------------------------------------------------------------------------
// // Purpose:
// //   Creates a 2nd-order high-pass IIR filter with a Butterworth response, typically used for DC removal
// //   (e.g., to suppress frequencies below 0.5-1.0 Hz in EEG).
// //
// // Notes:
// //   - Filter is always designed as 2nd order
// //   - Uses Q = sqrt(2) which gives a maximally flat Butterworth roll-off
// //   - Output coefficients are scaled to fixed-point Q1.31 with a shared shift
// //
// // Inputs:
// //   fs        - sampling frequency (e.g. 250 Hz)
// //   f0        - cutoff frequency for high-pass filter (e.g. 0.5 or 1.0 Hz)
// //
// // Outputs:
// //   B_out[3]  - output numerator coefficients (Q1.31, B[0..2])
// //   A_out[2]  - output denominator coefficients (Q1.31, A[1..2]) — A[0] is always 1.0, not stored
// //   shift_out - shift needed to scale results safely back to int32
// void design_iir_dc_blocker(float fs,
//                            float f0,
//                            int32_t* B_out,
//                            int32_t* A_out,
//                            int32_t* shift_out)
// {
//     float nyquist = fs * 0.5f;
//     float norm_f  = f0 / nyquist;

//     // Bilinear transform trick - turns analog poles into digital
//     float ita = 1.0f / tanf(M_PI * norm_f);
//     float q   = sqrtf(2.0f); // Standard Butterworth Q

//     float norm = 1.0f / (1.0f + q * ita + ita * ita);

//     // Numerator (feedforward path)
//     float Bf[3];
//     Bf[0] = norm;
//     Bf[1] = -2.0f * norm;
//     Bf[2] = norm;

//     // Denominator (feedback path)
//     float Af[3];
//     Af[0] = 1.0f; // always 1
//     Af[1] = 2.0f * norm * (ita * ita - 1.0f);
//     Af[2] = norm * (1.0f - q * ita + ita * ita);

//     // Use shared utility to convert to Q1.31 fixed-point
//     scale_coef_to_32_bits(Af, Bf, 3, 2.0f, A_out, B_out, shift_out);
// }
