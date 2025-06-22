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
    # --- FIR EQ ---
    "FIR_H",                # 7x int32 FIR taps
    "fir_hist",             # 16x7 int32 circular buffer

    # --- DC Blocker IIR ---
    "coef_B", "coef_A",     # 3 + 2 int32, high-pass IIR
    "x1_q", "x2_q", "y1_q", "y2_q", # 16 int32 each

    # --- 50/60 Hz Notch ---
    "BQ_B", "BQ_A",         # 3 + 2 int32 for 50/60Hz notch
    "state",                # 16x2x4 int32_t, notch biquad filter state

    # --- 100/120 Hz Notch ---
    "coef_B", "coef_A",     # (reuse or unique name for 100/120Hz)
    "x1_q", "x2_q", "y1_q", "y2_q", # for 100/120Hz if separate, else skip

    # --- Data Buffers ---
    "rawADCdata",           # 54B
    "parsedADCdata",        # 48B
    "dataBuffer",           # 1456B+
    "dspBuffer",            # 16x int32
    "txBuf",                # up to 1460B

    "notch100120Hz_16ch_2p",
    "notch5060Hz_16ch_4p",
    "adcEqualizer_16ch_7tap",
    "dcBlockerIIR_16ch_2p",

    # --- Battery Sense class (if big and persistent)
    # "BatterySense",       # only if you want to track this class

    # --- FreeRTOS Queues (if explicit variables)
    # "adcFrameQue", "cmdQue",  # if you want to see queue object size/placement
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
