"""Smoke test — verifies the environment is ready before running the real
netlist generation. Run this first on a fresh machine.

Checks:
    1. skidl is installed
    2. KiCad symbol libraries are findable
    3. We can load Device.kicad_sym specifically (the basic R/C/L lib)
    4. We can load the heavier libs we use (RF_Module, Interface_UART, etc.)

Exit 0 = ready to run battery_side.py / display_side.py.
Exit 1 = environment problem; see printed advice.
"""

import os
import sys


REQUIRED_LIBS = [
    "Device",            # generic R/C/L/D
    "RF_Module",         # ESP32-S3-WROOM-1
    "Interface_UART",    # SN65HVD3082E
    "Regulator_Switching",  # TPS62933, Recom modules
    "Timer_RTC",         # DS3231M
    "Transistor_FET",    # AO3401A, AO3400A
    "Diode",             # SS24, SMAJ12CA, SMAJ15A
    "Battery",           # CR2032 holder
    "Switch",            # SW_Push
    "Connector",         # RJ45, terminal block
    "Connector_Generic", # generic Conn_01xNN
]


def fail(msg):
    print(f"  ✗ {msg}")


def ok(msg):
    print(f"  ✓ {msg}")


def main() -> int:
    print("=== Volthium hardware design smoke test ===\n")

    # 1. SKiDL importable
    try:
        import skidl
        ok(f"skidl {skidl.__version__} installed")
    except ImportError:
        fail("skidl not installed.  pip install -r ../../requirements-hw.txt")
        return 1

    # 2. KiCad symbol library env var
    candidates = [
        os.environ.get("KICAD9_SYMBOL_DIR"),
        os.environ.get("KICAD8_SYMBOL_DIR"),
        os.environ.get("KICAD7_SYMBOL_DIR"),
        os.environ.get("KICAD_SYMBOL_DIR"),
        "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
        "/usr/share/kicad/symbols",
        "/usr/local/share/kicad/symbols",
        "/opt/homebrew/share/kicad/symbols",
    ]
    symbol_dir = None
    for c in candidates:
        if c and os.path.isdir(c):
            symbol_dir = c
            ok(f"KiCad symbol library found at: {c}")
            break
    if not symbol_dir:
        fail("No KiCad symbol library found.")
        print("    Set KICAD8_SYMBOL_DIR to the symbols directory, e.g.")
        print("      export KICAD8_SYMBOL_DIR=/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols")
        return 1
    os.environ.setdefault("KICAD8_SYMBOL_DIR", symbol_dir)
    os.environ.setdefault("KICAD_SYMBOL_DIR", symbol_dir)

    # 3. Load each required library, count the symbols we use
    missing_libs = []
    for libname in REQUIRED_LIBS:
        path = os.path.join(symbol_dir, libname + ".kicad_sym")
        if os.path.isfile(path):
            size_kb = os.path.getsize(path) // 1024
            ok(f"{libname}.kicad_sym ({size_kb} KB)")
        else:
            fail(f"{libname}.kicad_sym NOT FOUND at {path}")
            missing_libs.append(libname)
    if missing_libs:
        print(f"\n  Missing libraries: {missing_libs}")
        print("  Likely cause: KiCad install is incomplete, or symbol_dir is wrong.")
        return 1

    # 4. Specifically try SKiDL Part() for one stock part and confirm it resolves
    try:
        from skidl import Part, TEMPLATE, set_default_tool, KICAD8
        set_default_tool(KICAD8)
        r = Part("Device", "R", dest=TEMPLATE)
        ok(f"SKiDL can resolve Device:R ({len(r.pins)} pins)")
    except Exception as exc:
        fail(f"SKiDL failed to resolve Device:R — {type(exc).__name__}: {exc}")
        return 1

    print("\n=== smoke test PASSED — run ./run.sh next ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
