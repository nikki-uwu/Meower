import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import firwin2, butter, lfilter, freqz, convolve

# ───────── CONFIG ─────────
Sampling_freq     = 250.0                             # Sample rate in Hz
Nyquist_frequency = Sampling_freq / 2                 # Always half of the sample rate
taps_fir          = 7                                 # Number of FIR taps
Cut_out_frequency = 1.0                               # High-pass cutoff in Hz
Nsig              = 2048                              # Signal length
NFFT              = 512                               # FFT resolution
# ──────────────────────────

# FIR: 7-tap sinc3 equalizer, normalized
Freq_grid = np.linspace(0, Nyquist_frequency, 2048)
H_sinc3   = np.sinc(Freq_grid / Sampling_freq) ** 3
H_inv     = np.ones_like(H_sinc3)
H_inv[1:] = 1.0 / H_sinc3[1:]
h_fir     = firwin2(taps_fir, Freq_grid / Nyquist_frequency, H_inv, window='hamming')
h_fir     = h_fir / np.sum(h_fir)

# Quantization to 32-bit signed integers
max_bits    = np.ceil(np.max(np.log2(np.abs(h_fir)))) + 1
bit_offset  = 31 - max_bits
scale       = 2 ** bit_offset
h_fir_int32 = np.int32(np.round(h_fir * scale))

# IIR: 2nd-order Butterworth high-pass at ~1 Hz
irr_B, iir_A = butter(2, Cut_out_frequency / Nyquist_frequency, btype='highpass')

# synthetic sinc³ signal
freqs  = np.fft.rfftfreq(Nsig, 1/Sampling_freq)
X_spec = np.sinc(freqs / Sampling_freq) ** 3
x_time = np.fft.irfft(X_spec, n=Nsig)

# filter three ways
x_fir       = convolve(x_time, h_fir, mode='same')
x_iir       = lfilter(irr_B, iir_A, x_time)
x_cascade   = lfilter(irr_B, iir_A, x_fir)

# centre snippets
mid = (Nsig - NFFT) // 2
def seg(x): return x[mid:mid+NFFT]
seg_orig, seg_fir, seg_iir, seg_cas = map(seg, (x_time, x_fir, x_iir, x_cascade))

# frequency responses (peak-normalised)
def db(x): return 20*np.log10(np.maximum(np.abs(x),1e-12))
w_fir, H_fir   = freqz(h_fir, worN=NFFT, fs=Sampling_freq)
w_iir, H_iir   = freqz(irr_B, iir_A, worN=NFFT, fs=Sampling_freq)
H_cas = H_fir * H_iir
H_fir_db = db(H_fir)
H_iir_db = db(H_iir)
H_cas_db = db(H_cas)

# Create 2 vertically stacked plots
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharey=True)

def make_right_y_axis(ax):
    ax_right = ax.twinx()
    ax_right.set_ylim(ax.get_ylim())
    ax_right.set_yticks(ax.get_yticks())
    ax_right.set_yticklabels([f"{y:.1f}" for y in ax.get_yticks()])
    return ax_right

# ─── Linear frequency plot ───
ax1.plot(w_fir, H_fir_db, label='SINC3 compensation FIR, 7 taps')
ax1.plot(w_fir, H_iir_db, label='DC removal IIR, 2nd order HP 1 Hz')
ax1.plot(w_fir, H_cas_db, label='Cascade', linestyle='--', color='black')
ax1.set_xlim(0, Nyquist_frequency)
ax1.set_ylim(-10, 10)
ax1.set_xlabel('Frequency (Hz)')
ax1.set_ylabel('Gain (dB)')
ax1.set_title('Filter responses (linear scale)')
ax1.minorticks_on()
ax1.grid(True, which='major', linestyle='-', linewidth=0.5, color='gray', alpha=0.7)
ax1.grid(True, which='minor', linestyle=':', linewidth=0.4, color='gray', alpha=0.4)
ax1.legend()
make_right_y_axis(ax1)

# 100 Hz vertical line on top plot with label
idx_100 = np.argmin(np.abs(w_fir - 100))
ax1.axvline(100, color='red', linestyle=':', linewidth=1.5)
ax1.annotate(f"{H_cas_db[idx_100]:.2f} dB", xy=(100, H_cas_db[idx_100]), xycoords='data',
             xytext=(5, 10), textcoords='offset points', color='red',
             arrowprops=dict(arrowstyle='->', color='red'))

# ─── Log frequency plot ───
ax2.plot(w_fir, H_fir_db, label='SINC3 compensation FIR, 7 taps')
ax2.plot(w_fir, H_iir_db, label='DC removal IIR, 2nd order HP 1 Hz')
ax2.plot(w_fir, H_cas_db, label='Cascade', linestyle='--', color='black')
ax2.set_xscale('log')
ax2.set_xlim(0.01, Nyquist_frequency)
ax2.set_xticks([0.01, 0.1, 1, 10, 100])
ax2.get_xaxis().set_major_formatter(plt.ScalarFormatter())
ax2.set_xlabel('Frequency (Hz, log scale)')
ax2.set_ylabel('Gain (dB)')
ax2.set_title('Filter responses (log10 scale)')
ax2.minorticks_on()
ax2.grid(True, which='major', linestyle='-', linewidth=0.5, color='gray', alpha=0.7)
ax2.grid(True, which='minor', linestyle=':', linewidth=0.4, color='gray', alpha=0.4)
ax2.legend()
make_right_y_axis(ax2)

# -3 dB point on log plot for cascade
idx_m3 = np.argmin(np.abs(H_cas_db + 3))
f_m3 = w_fir[idx_m3]
ax2.axvline(f_m3, color='blue', linestyle=':', linewidth=1.5)
ax2.annotate(f"{f_m3:.2f} Hz", xy=(f_m3, -3), xycoords='data',
             xytext=(5, -25), textcoords='offset points', color='blue',
             arrowprops=dict(arrowstyle='->', color='blue'))

# Add note box higher and left-shifted
note_text = (
    "Note:\n"
    "This plot assumes Fs = 250 Hz.\n"
    "Filters coefficients are fixed; changing Fs shifts the cutoffs.\n"
    "So 1 Hz cutoff becomes 2 Hz if Fs = 500 Hz.\n"
    "Always treat the X-axis as 0 to Fs/2.\n"
    "FIR is designed to recover ADC frequency response\n"
    "up to 0.8 of Nyquist frequency (which is Fs/2)."
)
ax1.text(
    0.84, 0.13, note_text,
    transform=ax1.transAxes,
    fontsize=9,
    va='bottom', ha='right',
    bbox=dict(facecolor='white', alpha=0.8, edgecolor='gray')
)

def on_resize(event):
    ax1.set_ylim(-10, 10)
    ax2.set_ylim(-10, 10)
    ax1.figure.canvas.draw_idle()
    ax2.figure.canvas.draw_idle()

fig.canvas.mpl_connect('resize_event', on_resize)

plt.tight_layout()
plt.show()