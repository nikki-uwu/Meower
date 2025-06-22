import sys
import platform
import numpy as np
import scipy
import scipy.fftpack
import scipy.signal
import pywt
import time

print("---- System Info ----")
print("Python:", sys.version)
print("Platform:", platform.platform())
print("Arch:", platform.architecture())
print("PyWavelets:", pywt.__version__, pywt.__file__)
print("NumPy:", np.__version__, np.__file__)
print("SciPy:", scipy.__version__, scipy.__file__)

print("\n---- NumPy/BLAS Config ----")
np.show_config()

print("\n---- sys.path ----")
for p in sys.path:
    print(p)

print("\n---- PyWavelets CWT Backend ----")
print(pywt._cwt.__doc__)

print("\n---- CWT speed test ----")
fs = 500
Nf = 80
data = np.random.randn(fs)
freqs = np.arange(1, Nf + 1)
# Test both 'morl' and complex Morlet
for wavelet in ['morl', 'cmor1.5-1.0']:
    print(f"\nTesting wavelet: {wavelet}")
    try:
        scales = pywt.scale2frequency(wavelet, 1.0 / freqs) * fs
        t0 = time.perf_counter()
        coef, _ = pywt.cwt(data, scales, wavelet, sampling_period=1/fs)
        elapsed = time.perf_counter() - t0
        print(f"{wavelet} coef shape: {coef.shape}, elapsed: {elapsed:.4f} s")
    except Exception as e:
        print(f"Error for {wavelet}: {e}")

print("\n---- FFT speed test ----")
t0 = time.perf_counter()
np.fft.fft(np.random.randn(4096))
t1 = time.perf_counter()
print(f"np.fft.fft(4096 pts): {t1 - t0:.6f} s")

print("\n---- SciPy FFTPACK speed test ----")
t0 = time.perf_counter()
scipy.fftpack.fft(np.random.randn(4096))
t1 = time.perf_counter()
print(f"scipy.fftpack.fft(4096 pts): {t1 - t0:.6f} s")

print("\n---- FIR filter test ----")
b = scipy.signal.firwin(101, 0.2)
x = np.random.randn(4096)
t0 = time.perf_counter()
scipy.signal.lfilter(b, 1, x)
t1 = time.perf_counter()
print(f"lfilter 4096 pts: {t1 - t0:.6f} s")

print("\n---- PyWavelets DWT speed test ----")
t0 = time.perf_counter()
pywt.dwt(np.random.randn(4096), 'db4')
t1 = time.perf_counter()
print(f"dwt (4096 pts, db4): {t1 - t0:.6f} s")

print("\nDONE")
