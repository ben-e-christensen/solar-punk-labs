# Z-Lift Platform

Two NEMA17 lead-screw steppers raise/lower a platform, driven by a BTT SKR Pico
(RP2040, onboard TMC2209s) running custom MicroPython firmware
(`firmware/main.py`). A Raspberry Pi 5 talks to it over USB serial
(`/dev/ttyACM0`) via `host/lift_control.py` and the tkinter GUI
`host/lift_gui.py`.

## Flashing / updating the firmware

All of this runs on the **Pi 5** (the SKR Pico hangs off its USB port).

### One-time setup

Creates a venv so nothing installs system-wide (skip if `.venv` already exists):

```bash
cd ~/path/to/repo/platform    # wherever this repo lives on the Pi
python3 -m venv .venv
source .venv/bin/activate
pip install mpremote pyserial
```

### Every time `firmware/main.py` changes

Copy `main.py` onto the board's internal filesystem:

```bash
source .venv/bin/activate
mpremote connect /dev/ttyACM0 fs cp firmware/main.py :main.py
```

Close the GUI (or anything else holding `/dev/ttyACM0`) first — mpremote needs
the port to itself.

Then **reset the board so it actually runs the new code**: reopen
`host/lift_gui.py` and click **Reset Board**, or manually send Ctrl-B (exit raw
REPL) then Ctrl-D (soft reset) over the serial connection.

> **Don't use `mpremote reset`.** It soft-resets from raw-REPL mode, where
> MicroPython deliberately skips auto-running `main.py`, so the board looks
> dead/unresponsive afterward. The same applies after using `mpremote exec` for
> debugging — if the board seems hung, it's this, not a hardware fault; the
> Reset Board button fixes it.

### Sanity check after flashing

The GUI's STATUS poll should come back with a `HOMED`/`NOT_HOMED` reply within
~5 seconds. After any wiring/port change, use the Jog buttons (small bounded
moves that ignore endstops) to confirm each motor locks and moves the right
direction before trusting a full RAISE/LOWER.

### Initial MicroPython install

Only needed once, or after erasing the board — no UF2 drag-and-drop is needed
for normal firmware updates:

1. Hold **BOOTSEL**, plug in USB — the board mounts as an `RPI-RP2` drive.
2. Drag on a `.uf2` from https://micropython.org/download/RPI_PICO/ (the
   generic RP2040 build works fine for the BTT/SKR Pico).
3. The board reboots automatically into MicroPython.

## Running the GUI

```bash
cd host
source ../.venv/bin/activate   # needs pyserial; smbus2 + matplotlib optional
python3 lift_gui.py
```
