# size_report.py ──────────────────────────────────────────────────────────
#
# • Shows a concise RAM / IRAM / Flash overview with percentages.
# • Lists **where selected DSP-critical symbols actually live** (.rodata,
#   .dram0.data, .bss, …) so you can verify DRAM_ATTR / const placement.
# • Works on Windows, Linux and macOS.

Import("env")
import shutil, subprocess, re, pathlib, textwrap, sys

# ── Board capacities ────────────────────────────────────────────────────
RAM_BYTES  = 0x50000       # 327 680  (ESP32-C3 DRAM + RTC fast RAM)
IRAM_BYTES = 0x20000       # 131 072  (instruction RAM)
FLASH_APP  = 0x140000      # 1 310 720 factory-partition budget

# ── DSP symbols we care about ───────────────────────────────────────────
DSP_SYMBOLS = [
    # --- Global Frame Packing Variables ---
    "FRAMES_PER_PACKET_LUT",    # const uint32_t[5] - lookup table for adaptive packing
    "g_framesPerPacket",        # volatile uint32_t - current frames per UDP packet
    "g_bytesPerPacket",         # volatile uint32_t - ADC data bytes threshold
    "g_udpPacketBytes",         # volatile uint32_t - total UDP payload size
    
    # --- FIR Equalizer (adcEqualizer_16ch_7tap) ---
    # Note: These are static inside the function, shown with C++ mangling
    "fir_idx",                  # uint8_t - circular buffer index
    "fir_hist",                 # int32_t[16][7] - circular buffer, 16ch × 7 taps
    
    # --- DC Blocker IIR (dcBlockerIIR_16ch_2p) ---
    "coef_B",                   # int32_t[26][3] - numerator coeffs (25 sets + bypass)
    "coef_A",                   # int32_t[26][2] - denominator coeffs 
    "x1_q", "x2_q",            # int32_t[16] - input state history per channel
    "y1_q", "y2_q",            # int32_t[16] - output state history per channel
    
    # --- 50/60 Hz Notch (notch5060Hz_16ch_4p) ---
    "BQ_B",                     # int32_t[11][3] - biquad numerators (10 sets + bypass)
    "BQ_A",                     # int32_t[11][2] - biquad denominators
    "state",                    # int32_t[16][2][4] - per channel, 2 stages, 4 states
    
    # --- 100/120 Hz Notch (notch100120Hz_16ch_4p) ---
    # Same names but different functions - C++ mangles them differently
    
    # --- Main Task Data Buffers ---
    "rawADCdata",               # uint8_t[54] - raw SPI data (2×27 bytes)
    "parsedADCdata",            # uint8_t[48] - stripped preambles (16ch × 3 bytes)
    "dataBuffer",               # uint8_t[1456] - packed frames (max 28 × 52 bytes)
    "dspBuffer",                # int32_t[16] - unpacked samples for DSP
    
    # --- UDP Task Buffer ---
    "txBuf",                    # uint8_t[1460] - final UDP payload + battery
    
    # --- Global Filter Control Flags ---
    "g_filtersEnabled",         # volatile bool - master filter switch
    "g_adcEqualizer",          # volatile bool - FIR on/off
    "g_removeDC",              # volatile bool - DC blocker on/off
    "g_block5060Hz",           # volatile bool - 50/60Hz notch on/off
    "g_block100120Hz",         # volatile bool - 100/120Hz notch on/off
    "g_digitalGain",           # volatile uint32_t - bit shift amount (0-8)
    "g_selectSamplingFreq",    # volatile uint32_t - rate index (0-4)
    "g_selectNetworkFreq",     # volatile uint32_t - 50Hz=0, 60Hz=1
    "g_selectDCcutoffFreq",    # volatile uint32_t - cutoff index (0-4)
    
    # --- Queue Handles ---
    "adcFrameQue",             # QueueHandle_t - 5 slots, variable size
    "cmdQue",                  # QueueHandle_t - 8 slots × 512 bytes
]

# ── Helpers ─────────────────────────────────────────────────────────────
def pretty(n):
    return f"{n:,}".rjust(9)

def pct(used, total):
    return f"{used * 100 / total:5.1f} %"

def find_tool(name_hint):
    return (env.get(name_hint) or
            env.WhereIs(name_hint) or
            shutil.which(name_hint))

# ── Post-build hook ─────────────────────────────────────────────────────
def _after_build(source, target, env):
    elf = pathlib.Path(env.subst("$PROG_PATH"))
    if not elf.exists():
        print("⚠️  Cannot find firmware.elf – memory report skipped")
        return

    # ---------- size summary ----------
    size_tool = find_tool("SIZE") or find_tool("riscv32-esp-elf-size") or "size"
    result = subprocess.run([size_tool, "-A", elf], text=True, capture_output=True)
    if result.returncode:
        print(result.stdout)
        print("⚠️  size tool returned an error")
        return
    raw_table = result.stdout

    ram = iram = flash = 0
    for line in raw_table.splitlines():
        m = re.match(r"\s*(\.[\w_.]+)\s+(\d+)", line)
        if not m:
            continue
        sect, sz = m.group(1), int(m.group(2))

        if sect in (".dram0.data", ".dram0.bss", ".noinit", ".rtc_noinit") \
           or sect.startswith(".rtc_fast"):
            ram += sz
        elif sect.startswith(".iram0"):
            iram += sz
        elif sect == ".flash_rodata_dummy":
            pass
        elif sect.startswith(".flash") or sect.startswith(".text"):
            flash += sz

    print("\n──────────  MEMORY USAGE SUMMARY  ──────────")
    print(f"RAM   : {pretty(ram)} / {pretty(RAM_BYTES )}  ({pct(ram , RAM_BYTES )})")
    print(f"IRAM  : {pretty(iram)} / {pretty(IRAM_BYTES)}  ({pct(iram, IRAM_BYTES)})")
    print(f"Flash : {pretty(flash)}/ {pretty(FLASH_APP )}  ({pct(flash,FLASH_APP )})")
    print("────────────────────────────────────────────\n")

    # ---------- section map ----------
    print("Section map (from size -A):")
    print(textwrap.indent(raw_table.rstrip(), "  "))
    print("────────────────────────────────────────────\n")

    # ---------- symbol placement ----------
    nm_tool = find_tool("NM") or find_tool("riscv32-esp-elf-nm") or "nm"
    nm_out  = subprocess.run(
        [nm_tool, "-C", "-S", "--size-sort", "--radix=d", elf],  # <- added -C
        text=True, capture_output=True)

    if nm_out.returncode:
        print("⚠️  nm tool error – symbol map skipped")
        return

    symbol_lines = []
    for line in nm_out.stdout.splitlines():
        # Format with -C -S: <addr> <size> <type> <demangled-name>
        parts = line.strip().split(maxsplit=3)
        if len(parts) < 4:
            continue
        addr_str, size_str, stype, demangled = parts
        for target in DSP_SYMBOLS:
            if demangled.endswith(target):
                symbol_lines.append(
                    (target, int(addr_str), int(size_str), stype, demangled)
                )
                break

    if symbol_lines:
        print("DSP-critical symbol locations:")
        for tgt, addr, sz, stype, full in symbol_lines:
            print(f"  {tgt:<22} @ 0x{addr:08X}  {sz:6} B  sect '{stype}'   «{full}»")
        print("Type legend: R=.rodata  D=.data  B=.bss  S=.noinit  etc.")
        print("────────────────────────────────────────────\n")
    else:
        print("⚠️  Tracked DSP symbols not present (optimised out or LTO-ed)\n")

# Register the hook
env.AddPostAction("buildprog", _after_build)
