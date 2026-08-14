# solar-punk-labs

## Current focus: Z platform (3D printer)

This is one component of a larger (not-yet-defined) project. Right now the active work is a
Z-axis lifting platform for a 3D printer — two lead-screw stepper motors raise/lower a platform.
The end goal for *this* platform is simple: drive it fully up or fully down on command. No
multi-axis motion planning, no G-code semantics needed.

Relevant files:
- `CAD/platform.scad`, `CAD/nema_mounts.scad`, `CAD/latch.scad` — mechanical design, in progress.
  No endstop mount is laid out yet.
- `platform/motor.py`, `platform/main.py` — legacy generic motor-control code from an earlier
  Raspberry Pi–based approach (see commit "added generic motor controls... unlikely to warrant
  a pi"). `main.py` is currently empty. Superseded by `platform/firmware/` and `platform/host/`
  below.
- `platform/firmware/main.py` — MicroPython firmware for the BTT Pico. Implements
  `RAISE`/`LOWER`/`STOP`/`STATUS` over USB serial. Pin numbers at the top are placeholders —
  not yet verified against the BTT Pico's actual pinout.
- `platform/host/lift_control.py` — Pi 5 control script (pyserial), sends the same commands to
  the BTT Pico over `/dev/ttyACM0`.

### Hardware plan (decided, parts ordered as of 2026-08-09)

- **Motors**: two NEMA17 steppers, each on its own lead screw, lifting the same platform.
- **Drivers**: driving them via a **BTT Pico** board (RP2040-based, onboard TMC2209 drivers,
  standard 3-pin JST endstop headers). Each motor gets its own driver output — NOT sharing a
  single STEP/DIR/coil output — specifically so they can be homed/controlled independently.
  (Earlier considered a DM556T external driver, since that's been used on past projects, but
  NEMA17 current draw fits comfortably within the BTT Pico's onboard TMC2209s, so no external
  driver needed for this motor size.)
- **Main MCU**: Raspberry Pi 5 (not the Pico W originally planned — swapped 2026-08-14. The Pi 5's
  USB port both flashes the BTT Pico (drag-and-drop UF2, no separate host needed) and carries
  runtime serial comms over the same cable as a standard `/dev/ttyACM0` device, avoiding a
  dedicated UART wiring link and a second MCU toolchain). Talks to the BTT Pico over USB serial
  with a small custom command set (`RAISE`, `LOWER`, `STOP`, `STATUS`), not Klipper's G-code/host
  protocol — that stack (klippy + Moonraker) is overkill for a two-position platform. BTT Pico
  runs custom MicroPython firmware rather than Klipper.
- **Endstops**: optical (slotted opto-interrupter), not mechanical microswitches — more
  repeatable, no contact wear, good fit for a low-force lead-screw stage. Confirmed compatible
  part spec: VCC 2.7V–5V, active-high signal (low when untriggered, high when triggered) — runs
  fine on the Pico's native 3.3V logic, no level shifting needed.

### Endstop / homing strategy

- Because each motor has its own driver, they can be **homed independently**: send steps to
  motor A only until its endstop triggers, then motor B only until its endstop triggers. This
  fully corrects any accumulated drift/desync between the two screws every homing cycle,
  regardless of skipped steps or friction differences — no need for simultaneous/matched sensing.
- Minimum viable setup: **2 endstops, one per motor, both at the top.** Home upward on each motor
  independently to re-zero; "lowered" position is reached via a software-defined step count
  downward from that zero (no bottom endstop required — over-travel downward is less
  catastrophic than crashing into the top).
- Bottom endstops (if added) are a safety backstop only, not needed for sync correction — don't
  wire two of them in parallel onto one BTT Pico endstop header (risks output contention between
  two active-high push-pull signals); if used, give each its own spare GPIO and OR them in
  firmware instead.
- The "only 3 endstop headers" limitation isn't a hard constraint — those are just a labeled
  subset of GPIO with a convenient JST connector. A 4th endstop can be wired to any other spare
  3.3V-tolerant GPIO pin with loose wires instead of the pre-made connector.
- Mount endstops so they're actuated by the platform frame itself, not by the lead screw/coupler,
  so triggering isn't sensitive to which screw is momentarily slightly ahead of the other.

### Status

Parts arrived and wired as of 2026-08-14 (motors + endstops connected to BTT Pico, one endstop
per motor). Firmware (`platform/firmware/main.py`) and host script (`platform/host/lift_control.py`)
written 2026-08-14, not yet tested against real hardware. Before running: fill in the real BTT
Pico pin numbers, flash the firmware via BOOTSEL/UF2 over USB, then verify DIR polarity and
endstop trigger polarity with the motors disconnected from the lead screws (or at very low
speed) before trusting RAISE/LOWER at full travel.
