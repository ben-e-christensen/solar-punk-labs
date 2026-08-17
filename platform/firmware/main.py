"""
MicroPython firmware for the BTT Pico. Copy this file onto the board's
filesystem as main.py (e.g. via Thonny or mpremote) so it runs on boot.

Listens for line-delimited commands over USB serial (stdin/stdout):
    RAISE   - home both motors up until each hits its own top endstop,
              counting each motor's steps; replies OK RAISED A=<n> B=<n>
    LOWER   - lower both motors by the fixed FULL_LOWER_STEPS count.
              Stateless: no homed requirement, no sensors involved. The
              platform is squared at the top by every RAISE, so an equal
              fixed count lands both sides at the same bottom by
              construction (bottom endstops were tried 2026-08-15 and
              removed the same day -- see CLAUDE.md).
    STOP    - abort whatever RAISE/LOWER is in progress
    STATUS  - report homed state and current position
    ENDSTOPS - report the live value of the top endstop pins (hand-block
              each opto and watch the value flip to verify wiring without
              any motion)
    JOG_A_UP / JOG_A_DOWN / JOG_B_UP / JOG_B_DOWN
            - move one motor a small fixed step count (JOG_STEPS), ignores
              endstops/homed state entirely -- for bench-testing DIR polarity
              without the risk of a full RAISE/LOWER run

Two motors ("A"/"B"), each with its own STEP/DIR/EN output and its own top
endstop input. Both are rigidly connected to the same platform, so RAISE
and LOWER always move them simultaneously (each stopping independently on
its own endstop during RAISE) rather than one at a time -- see CLAUDE.md.
"""

from machine import Pin
import sys
import select
import utime

# ---------------------------------------------------------------------------
# PIN CONFIG - VERIFY AGAINST YOUR BTT PICO'S PINOUT DIAGRAM BEFORE RUNNING.
# These are placeholders; the values below are almost certainly wrong for
# your board revision. Wrong pins just won't work (no damage risk on RP2040
# GPIO), but confirm before wiring expectations against this code.
# ---------------------------------------------------------------------------
STEP_A_PIN = 11
DIR_A_PIN = 10
EN_A_PIN = 12
ENDSTOP_A_PIN = 4

STEP_B_PIN = 14  # E0 port -- Y driver output confirmed-ish dead 2026-08-14 (motor spins
DIR_B_PIN = 13   # freely at idle while A holds). Ports have different hardwired standalone
EN_B_PIN = 15    # microstepping (X=8 Y=32 Z=64 E=16) -- keep MICROSTEP_B below in sync.
ENDSTOP_B_PIN = 3

# Enable pins on TMC2209-based boards are typically active-low (0 = driver
# enabled). Flip if your board is the opposite.
ENABLE_ACTIVE_LOW = True

# Which DIR pin level moves the motor "up" (toward its endstop). Unknown
# until tested -- flip either constant if a motor moves the wrong way.
DIR_UP_A = 1
DIR_UP_B = 1

# Active-high per part spec (low = untriggered, high = triggered). The
# 2026-08-14 bench reading that suggested the opposite turned out to be a
# wiring/sensor problem, not a real polarity difference -- revisit only
# after independently confirming a real low->high transition on the pin.
ENDSTOP_TRIGGERED_VALUE = 1

# ---------------------------------------------------------------------------
# MICROSTEPPING - the SKR/BTT Pico's TMC2209s run in STANDALONE mode here
# (nothing configures them over UART), so microstep resolution comes from
# each port's hardwired MS1/MS2 straps, which differ per port because they
# double as UART address pins: X=8, Y=32, Z=64, E=16 microsteps/full-step.
# A STEP pulse on Y therefore moves 1/4 as far as one on X. Compensate by
# giving motor B RATIO_B pulses (at RATIO_B x the rate) per motor A pulse.
# Update these if a motor moves ports.
# ---------------------------------------------------------------------------
MICROSTEP_A = 8   # motor A on X port
MICROSTEP_B = 16  # motor B on E0 port
RATIO_B = MICROSTEP_B // MICROSTEP_A  # B pulses per A pulse for equal travel

# ---------------------------------------------------------------------------
# MOTION CONFIG - tune once the mechanism is running.
# All step counts below are in motor-A pulses (8 microsteps each); motor B
# automatically gets RATIO_B x as many pulses to travel the same distance.
# Raise speed is set by RAISE_PULSE_US (smaller = faster); lower speed is
# derived from it via LOWER_SPEED_MULT (changed 2026-08-15 from independent
# constants to a single easy multiplier knob).
# ---------------------------------------------------------------------------
RAISE_PULSE_US = 800         # time high and time low per step while homing up
LOWER_SPEED_MULT = 5         # lower runs this many times faster than raise --
                             # the one knob to change lowering speed
LOWER_PULSE_US = RAISE_PULSE_US // LOWER_SPEED_MULT
JOG_PULSE_US = 800           # bench-test jogs
RAISE_MAX_STEPS = 27000      # RAISE ends at the top endstops OR this cap,
                             # whichever comes first (cap-without-endstops
                             # reports ERROR HOMING_FAILED, which parks the
                             # GUI automation). Kept tight, not a huge
                             # last-resort number, because the rig runs
                             # unattended for weeks at a time.
JOG_STEPS = 50                # small bench-test move, ignores endstops entirely
MAX_LAG_STEPS = 2000         # rigid-platform guard during RAISE: once ONE
                             # motor has hit its top endstop, the other may
                             # run at most this many more steps before the
                             # move aborts with ERROR HOMING_FAILED. The
                             # platform is rigid, so the two sides can only
                             # be slightly out of sync -- if one side needs
                             # thousands more steps, its endstop is dead or
                             # miswired and continuing just rams and racks
                             # the frame.
FULL_LOWER_STEPS = 24000     # LOWER travel: tune to just under a real
                             # full-travel raise count (read A=<n> off an
                             # OK RAISED reply after raising from the
                             # bottom). Over-travel downward just stalls
                             # the motors (skipped steps, no crash) and the
                             # next RAISE re-homes anyway.

# ---------------------------------------------------------------------------

step_a = Pin(STEP_A_PIN, Pin.OUT)
dir_a = Pin(DIR_A_PIN, Pin.OUT)
en_a = Pin(EN_A_PIN, Pin.OUT)
endstop_a = Pin(ENDSTOP_A_PIN, Pin.IN, Pin.PULL_DOWN)

step_b = Pin(STEP_B_PIN, Pin.OUT)
dir_b = Pin(DIR_B_PIN, Pin.OUT)
en_b = Pin(EN_B_PIN, Pin.OUT)
endstop_b = Pin(ENDSTOP_B_PIN, Pin.IN, Pin.PULL_DOWN)

homed = False
stop_requested = False
# Per-motor step counts measured during the last successful RAISE.
# Telemetry only (reported in replies/STATUS, and useful for tuning
# FULL_LOWER_STEPS) -- nothing replays these counts.
raise_steps_a = 0
raise_steps_b = 0

poller = select.poll()
poller.register(sys.stdin, select.POLLIN)


def drivers_enable():
    en_a.value(0 if ENABLE_ACTIVE_LOW else 1)
    en_b.value(0 if ENABLE_ACTIVE_LOW else 1)


def drivers_disable():
    en_a.value(1 if ENABLE_ACTIVE_LOW else 0)
    en_b.value(1 if ENABLE_ACTIVE_LOW else 0)


def check_stop_requested():
    """Non-blocking check for an incoming STOP command mid-motion."""
    global stop_requested
    if poller.poll(0):
        line = sys.stdin.readline().strip().upper()
        if line == "STOP":
            stop_requested = True
    return stop_requested


def step_once(step_pin, pulse_us):
    step_pin.value(1)
    utime.sleep_us(pulse_us)
    step_pin.value(0)
    utime.sleep_us(pulse_us)


def step_b_unit(pulse_us):
    """One motor-A-equivalent unit of travel on motor B: RATIO_B pulses at
    RATIO_B x the pulse rate, so both motors cover the same distance in the
    same wall-clock time despite the port's finer hardwired microstepping.
    pulse_us is the motor-A pulse time for the current move."""
    b_pulse = pulse_us // RATIO_B
    for _ in range(RATIO_B):
        step_once(step_b, b_pulse)


def home_both():
    """Step both motors upward together, every iteration, each one
    independently stopping the instant its own top endstop triggers,
    counting each motor's steps. Both motors are rigidly
    connected to the same platform, so homing them fully sequentially (one
    at a time) would rack the frame -- this keeps any skew during homing
    bounded to whatever drift already existed. Motion is bounded by
    RAISE_MAX_STEPS: endstop OR step cap, whichever comes first.

    Returns (a_done, b_done, count_a, count_b)."""
    dir_a.value(DIR_UP_A)
    dir_b.value(DIR_UP_B)
    a_done = False
    b_done = False
    count_a = 0
    count_b = 0
    lag = 0
    for _ in range(RAISE_MAX_STEPS):
        if check_stop_requested():
            return False, False, count_a, count_b
        if not a_done and endstop_a.value() == ENDSTOP_TRIGGERED_VALUE:
            a_done = True
        if not b_done and endstop_b.value() == ENDSTOP_TRIGGERED_VALUE:
            b_done = True
        if a_done and b_done:
            return True, True, count_a, count_b
        if a_done or b_done:
            lag += 1
            if lag > MAX_LAG_STEPS:
                return a_done, b_done, count_a, count_b  # other endstop dead?
        if not a_done:
            step_once(step_a, RAISE_PULSE_US)
            count_a += 1
        if not b_done:
            step_b_unit(RAISE_PULSE_US)
            count_b += 1
    return a_done, b_done, count_a, count_b  # hit safety cap


def lower_both_fixed(steps):
    """Step both motors downward together for a fixed count. Every RAISE
    squares the platform against the top endstops, so an equal fixed count
    lands both sides at the same bottom position by construction -- no
    bottom sensing needed."""
    dir_a.value(0 if DIR_UP_A else 1)
    dir_b.value(0 if DIR_UP_B else 1)
    for _ in range(steps):
        if check_stop_requested():
            return False
        step_once(step_a, LOWER_PULSE_US)
        step_b_unit(LOWER_PULSE_US)
    return True


def cmd_raise():
    global homed, stop_requested, raise_steps_a, raise_steps_b
    stop_requested = False
    drivers_enable()
    ok_a, ok_b, count_a, count_b = home_both()
    if ok_a and ok_b:
        homed = True
        raise_steps_a = count_a
        raise_steps_b = count_b
        print("OK RAISED A={} B={}".format(count_a, count_b))
    elif stop_requested:
        homed = False
        print("OK STOPPED")
    else:
        homed = False
        print("ERROR HOMING_FAILED")


def cmd_lower():
    global homed, stop_requested
    stop_requested = False
    drivers_enable()
    completed = lower_both_fixed(FULL_LOWER_STEPS)
    # Whatever happened, we're no longer at the homed top position; the
    # next RAISE re-homes.
    homed = False
    if completed:
        print("OK LOWERED {}".format(FULL_LOWER_STEPS))
    elif stop_requested:
        print("OK STOPPED")
    else:
        print("ERROR LOWER_FAILED")


def cmd_status():
    if homed:
        print("HOMED A={} B={}".format(raise_steps_a, raise_steps_b))
    else:
        print("NOT_HOMED")


def cmd_jog(step_pin, dir_pin, dir_up, pulses, pulse_us):
    """Move one motor JOG_STEPS worth of travel in one direction (B gets
    RATIO_B x the pulses to match A's distance). No endstop check, no
    homed-state requirement -- purely for confirming DIR polarity by eye
    at a distance too small to cause damage."""
    global stop_requested
    stop_requested = False
    drivers_enable()
    dir_pin.value(dir_up)
    for _ in range(pulses):
        if check_stop_requested():
            print("OK STOPPED")
            return
        step_once(step_pin, pulse_us)
    print("OK JOGGED")


def main():
    print("READY")
    while True:
        line = sys.stdin.readline()
        if not line:
            continue
        cmd = line.strip().upper()
        if cmd == "RAISE":
            cmd_raise()
        elif cmd == "LOWER":
            cmd_lower()
        elif cmd == "LOWER_FULL":
            cmd_lower()  # legacy alias from when LOWER was counted-replay
        elif cmd == "STOP":
            print("OK IDLE")  # nothing running; STOP mid-motion is handled inline
        elif cmd == "STATUS":
            cmd_status()
        elif cmd == "ENDSTOPS":
            print("TOP_A={} TOP_B={}".format(
                endstop_a.value(), endstop_b.value()))
        elif cmd == "JOG_A_UP":
            cmd_jog(step_a, dir_a, DIR_UP_A, JOG_STEPS, JOG_PULSE_US)
        elif cmd == "JOG_A_DOWN":
            cmd_jog(step_a, dir_a, not DIR_UP_A, JOG_STEPS, JOG_PULSE_US)
        elif cmd == "JOG_B_UP":
            cmd_jog(step_b, dir_b, DIR_UP_B, JOG_STEPS * RATIO_B, JOG_PULSE_US // RATIO_B)
        elif cmd == "JOG_B_DOWN":
            cmd_jog(step_b, dir_b, not DIR_UP_B, JOG_STEPS * RATIO_B, JOG_PULSE_US // RATIO_B)
        elif cmd == "":
            continue
        else:
            print("ERROR UNKNOWN_COMMAND")


main()
