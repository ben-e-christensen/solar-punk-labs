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

- Both motors are rigidly connected to the same platform, so they must move **simultaneously**,
  not one at a time — moving only one motor racks the frame against the other, fixed side.
  Originally planned as fully sequential (motor A homes completely, then motor B) since each
  motor has its own driver and can technically be homed independently; corrected 2026-08-14
  after realizing that racks the platform in this build. RAISE now steps both motors together
  every iteration, each one independently stopping the instant its own endstop triggers (so a
  motor that's already home just idles while the other catches up) — this still self-corrects
  drift between the two screws every homing cycle, but bounds any skew during homing to
  whatever drift already existed rather than one motor's entire travel distance. LOWER already
  moved both motors together in lockstep.
- **2 endstops, one per motor, both at the top** (settled 2026-08-15 after a same-day detour
  through bottom endstops). RAISE runs up until each motor's top endstop triggers — this
  squares the platform at the top on every single raise. LOWER moves both motors down by the
  **fixed** `FULL_LOWER_STEPS` count (24000): since the top just got squared and both sides
  descend the same count, the bottom position is square by construction, no bottom sensing
  needed. Both moves are stateless — no counted-step replay (the old replay scheme was fragile
  because it depended on an exact remembered count, and silently no-opped when BEGIN started
  with the platform already at the top: counted raise ~0, so every cycle "moved" ~0 while
  reporting OK).
- Bottom endstops were physically tried 2026-08-15 and removed the same day: the two sides
  never trigger at exactly the same moment, and any sensing/wiring fault at the bottom rams
  the frame; they also can't square anything the top endstops don't already square. Unplugged;
  firmware support removed.
- Sensorless (StallGuard) bottom homing was considered and parked: the SKR Pico's TMC2209
  UART is hardwired to gpio8 (TX) / gpio9 (shared), addresses X=0 Z=1 Y=2 E0=3, so it needs no
  wiring — but StallGuard requires writing SGTHRS (and current etc.) over that UART, which in
  the other project Klipper did invisibly from the `[tmc2209 ...]` config sections (the DIAG
  jumper only routes the driver's DIAG output onto its own port's endstop pin; jumper alone
  does nothing in standalone mode since SGTHRS powers up at "never"). Doing it here means a
  MicroPython TMC2209 UART driver — a real sub-project that would also unlock uniform
  microstepping (killing the RATIO_B hack) and current control. Also lead screws are the worst
  case for StallGuard (mechanical advantage hides the stall from the motor). Revisit only if
  fixed-count lowering proves insufficient.
- The "only 3 endstop headers" limitation isn't a hard constraint — those are just a labeled
  subset of GPIO with a convenient JST connector. A 4th endstop can be wired to any other spare
  3.3V-tolerant GPIO pin with loose wires instead of the pre-made connector.
- Mount endstops so they're actuated by the platform frame itself, not by the lead screw/coupler,
  so triggering isn't sensitive to which screw is momentarily slightly ahead of the other.

### Status

Parts arrived and wired as of 2026-08-14 (motors + endstops connected to BTT Pico, one endstop
per motor). Firmware (`platform/firmware/main.py`) and host script (`platform/host/lift_control.py`)
written 2026-08-14. Pin numbers verified against a real Klipper config for the same board
(SKR/BTT Pico). Endstop polarity confirmed active-high (an earlier "always high" reading turned
out to be a flipped JST wire, not a real polarity difference). Motor B is back on the Y header
(endstop also on Y). The "out of step" X-vs-Y mismatch (and the earlier "Y port dead"
suspicion) was diagnosed 2026-08-14: the SKR Pico's TMC2209s run in standalone mode under this
firmware (nothing configures them over UART), so each port's microstep resolution comes from
its hardwired MS1/MS2 straps, which differ per port because they double as Klipper UART
address pins -- X=8, Y=32, Z=64, E=16 microsteps per full step. A STEP pulse on Y moves 1/4
the distance of one on X. The firmware compensates: all step counts are in motor-A (X,
8-microstep) units and motor B gets RATIO_B pulses at RATIO_B x the pulse rate per unit, so
distances and wall-clock speeds match. If a motor changes ports, update MICROSTEP_A/_B at the
top of the firmware.

Later on 2026-08-14 the Y driver output was judged dead for real (with drivers idle-enabled,
motor A's screw locks but motor B spins freely -- no coil current; cross-check by moving B's
cable to the X header, POWER OFF FIRST, still pending). Motor B moved to the **E0 port**
(step gpio14, dir gpio13, en gpio15, MICROSTEP_B=16 so RATIO_B=2); its endstop stays on the Y
endstop header. Never plug/unplug a stepper cable with VIN applied -- hot-disconnecting a coil
is the classic TMC2209 killer and likely what took out Y (Z's health unknown, same risk
exposure). DIR polarity for motor B not yet re-confirmed on E0.

Next bench session (pending as of 2026-08-14, firmware already edited for E0 but not yet
flashed):
1. Power everything off (USB + motor VIN).
2. Optional cross-check: motor B's cable into the X header, power on -- screw locks means Y
   driver truly dead (proceed); still free means cable/motor is the real fault and E0 won't fix
   it (revert firmware pins to Y and debug the cable instead).
3. Motor B cable into E0, power on, flash firmware (`mpremote ... fs cp ... :main.py`), Reset
   Board via GUI.
4. `JOG_B_UP`: confirm screw locks, then same distance/direction as `JOG_A_UP`. Wrong
   direction -> flip `DIR_UP_B` to 0.
If E0 ever dies too, Z is the last spare output: MICROSTEP_B = 64 (RATIO_B becomes 8).

RAISE and LOWER confirmed working on X + E0 (2026-08-14, after fixing a double direction
inversion that made LOWER move upward).

### Charge sensors / automated cycling (reworked 2026-08-14, sensors not yet wired)

End goal: two ADS1115 ADCs, one per electrometer, named **"roots"** and **"grounded_roots"**,
ride on the platform and wire to the Pi 5's I2C bus (not the Pico). Charge data only exists
while the platform is moving, so sampling happens ONLY during a RAISE/LOWER.

Operating workflow (all in `lift_gui.py`):
- Click **BEGIN** (any starting position, no hand-cranking needed since the stateless rework):
  raises until both top endstops trigger. On success, automation arms: a **CYCLE** (lower by
  `FULL_LOWER_STEPS`, raise back to the top endstops) fires every `CYCLE_INTERVAL_MIN`
  (30 min). The CYCLE button also fires one on demand; **RAISE**/**LOWER** buttons run either
  move individually without touching the automation; **STOP** aborts motion and disarms
  automation (BEGIN re-arms).
- Every raise is endstop-bounded AND step-capped: `RAISE_MAX_STEPS` (27000) ends the move at
  the endstops OR the cap, whichever first. Cap kept tight, not a huge last-resort number,
  because the rig runs unattended for ~6 weeks; cap-without-endstops = ERROR HOMING_FAILED,
  which disarms the automation so a failed endstop parks the system instead of cycling blind.
  LOWER is a fixed count, so it's inherently bounded. Step counts are still measured and
  reported on raises (`OK RAISED A=<n> B=<n>`; `STATUS` -> `HOMED A=.. B=..`) but they are
  telemetry only — nothing replays them; use them to tune `FULL_LOWER_STEPS` to just under a
  real full-travel raise (over-travel downward just skips steps harmlessly, and the next raise
  re-homes anyway).
- **Lag guard** (`MAX_LAG_STEPS`, 2000, added 2026-08-15): during a raise, once ONE motor has
  hit its top endstop, the other gets at most 2000 more steps before the move aborts with
  ERROR HOMING_FAILED. The platform is rigid, so the two sides can only be slightly out of
  sync — a side needing thousands more steps means its endstop is dead/miswired, and
  continuing just rams and racks the frame (learned at the bottom during the bottom-endstop
  detour: an unseen endstop rammed the full cap and locked the mechanism).
- **ENDSTOPS** (firmware command + GUI button next to the Jog panel): reports the live value
  of the top endstop pins (`TOP_A= TOP_B=`). Hand-block each opto and click it to verify
  wiring with zero motion after any endstop rework.
- Sampling: 100 Hz (`SAMPLE_HZ`) from a dedicated thread per motion segment;
  `charge_sensors.ContinuousSampler` puts the ADS1115s in continuous-conversion mode (860 SPS
  internally) so each sample is one register read per sensor. Drops to 1 Hz when no sensor is
  readable (unwired bench runs). After each segment: CSV + PNG saved to `platform/host/data/`
  (`<timestamp>_<raise|lower>.{csv,png}`, columns timestamp / elapsed_s / segment / roots_V /
  grounded_roots_V; segment repeats raise|lower per row for easy multi-file concatenation) and
  one reusable graph window updates in place (no window-per-cycle spam). BOTH legs save --
  raise files exist too, look for `_raise` names. When the sampler can't configure any sensor
  it falls back to 1 Hz and (since 2026-08-15) logs a WARNING line with the exact reason
  (smbus2 missing / bus unavailable / per-sensor config errors) instead of degrading silently;
  it upgrades to 100 Hz mid-segment if readings start arriving. A ~46-samples-per-lower CSV is
  the 1 Hz fallback signature -- check that log line, not the sampling code.
- `charge_sensors.py`: addresses 0x48 (roots) / 0x49 (grounded_roots) -- confirmed against
  the wired hardware 2026-08-15 (roots at 1001000b, grounded_roots at 1001001b), matching
  the defaults, no change needed. AIN0 vs GND, +/-4.096 V FSR
  (`_PGA_BITS`/`FSR_VOLTS` change together). Degrades gracefully (reports why per sensor) when
  smbus2/bus/device is missing, so the GUI runs anywhere. `python3 charge_sensors.py` does a
  one-shot smoke-test read.
- Host deps in the venv: `pip install pyserial smbus2 matplotlib` (GUI runs without
  matplotlib, just no graphs).
- Speeds: `RAISE_PULSE_US` (800) sets the raise; lower is derived as
  `RAISE_PULSE_US // LOWER_SPEED_MULT` (`LOWER_SPEED_MULT` = 3 as of 2026-08-15 -- the one
  knob for lowering speed; was independent constants at 2x before). `JOG_PULSE_US` separate.
- GUI STOP button stays enabled during motion (it used to be disabled with everything else, so
  it could never abort). Mid-motion it sends STOP write-only on a second serial handle; the
  blocked RAISE/LOWER worker still receives the "OK STOPPED" reply.
- `lift_control.py` serial timeout raised 60s -> 180s: a full-travel RAISE (~80s) outlived the
  old timeout, which silently desynced replies for every later command.

- **STRESS TEST** (GUI button): mechanical soak test while the rest of the build
  continues -- homes up like BEGIN, then runs lower+raise cycles back-to-back (1 s pause
  between cycles) until STOP or a motion error. Reuses the BEGIN/CYCLE state machine; since
  the 2026-08-15 stateless rework its cycles are identical to normal ones. Each segment still
  saves CSV/PNG like a normal cycle, and the GUI logs "STRESS TEST ABORTED by motion error"
  whenever a stress cycle disarms on an error.
- `LOWER_FULL` survives in the firmware only as a legacy alias for `LOWER` (they were separate
  commands while `LOWER` was counted-replay); the GUI's LOWER FULL button was replaced by the
  RAISE/LOWER buttons 2026-08-15.

There's also `platform/host/lift_gui.py` -- a tkinter GUI with RAISE/LOWER/STOP/STATUS buttons,
a Jog panel (A/B, up/down, `JOG_STEPS` from firmware -- small bounded move that ignores
endstops, for bench-testing DIR polarity without risking a full RAISE/LOWER), and a Reset Board
button (see below). Run with `python3 lift_gui.py` from `platform/host/` (venv active).

#### Flashing/updating the firmware

One-time setup (creates a venv so nothing installs system-wide):
```
cd platform  # or repo root, adjust paths below accordingly
python3 -m venv .venv
source .venv/bin/activate
pip install mpremote pyserial
```

Every time `platform/firmware/main.py` changes:
```
source .venv/bin/activate
mpremote connect /dev/ttyACM0 fs cp platform/firmware/main.py :main.py
```
then reset the board so it actually runs the new code -- use the **Reset Board** button in
`lift_gui.py`, or manually send Ctrl-B (exit raw REPL) then Ctrl-D (soft reset) over the serial
connection. A plain `mpremote reset` is unreliable: MicroPython deliberately skips auto-running
`main.py` after a soft-reset performed while in raw-REPL mode (which is the mode mpremote's own
`reset`/`exec` subcommands leave the board in), so the board can appear to hang/not respond to
RAISE/LOWER/etc. after using `mpremote exec` for debugging -- that's this issue, not a hardware
fault, if it happens again.

Initial MicroPython install (only needed once, or after erasing the board): hold BOOTSEL, plug
in USB, board mounts as a `RPI-RP2` drive -- drag on a `.uf2` from
https://micropython.org/download/RPI_PICO/ (the generic RP2040 build works fine for the
BTT/SKR Pico), board reboots automatically into MicroPython.
