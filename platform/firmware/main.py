"""
MicroPython firmware for the BTT Pico. Copy this file onto the board's
filesystem as main.py (e.g. via Thonny or mpremote) so it runs on boot.

Listens for line-delimited commands over USB serial (stdin/stdout):
    RAISE   - home both motors independently against their top endstops
    LOWER   - move both motors down a fixed step count from the homed zero
    STOP    - abort whatever RAISE/LOWER is in progress
    STATUS  - report homed state and current position
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

STEP_B_PIN = 6  # moved to Z and back 2026-08-14 -- Z channel had a different microstep
DIR_B_PIN = 5   # default, causing mismatched travel per step vs motor A; back on Y for
EN_B_PIN = 7    # consistency with motor A now that the Y port swap has been re-checked
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
# MOTION CONFIG - tune once the mechanism is running.
# ---------------------------------------------------------------------------
STEP_PULSE_US = 800          # time high and time low per step (speed knob)
HOMING_TIMEOUT_STEPS = 25000  # safety cutoff if an endstop never triggers (LOWER_STEPS + margin)
LOWER_STEPS = 20000          # distance from top (homed zero) to bottom
JOG_STEPS = 50                # small bench-test move, ignores endstops entirely

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


def step_once(step_pin):
    step_pin.value(1)
    utime.sleep_us(STEP_PULSE_US)
    step_pin.value(0)
    utime.sleep_us(STEP_PULSE_US)


def home_both():
    """Step both motors upward together, every iteration, each one
    independently stopping the instant its own endstop triggers. Both
    motors are rigidly connected to the same platform, so homing them
    fully sequentially (one at a time) would rack the frame -- this keeps
    any skew during homing bounded to whatever drift already existed,
    rather than one motor's entire travel distance."""
    dir_a.value(DIR_UP_A)
    dir_b.value(DIR_UP_B)
    a_done = False
    b_done = False
    for _ in range(HOMING_TIMEOUT_STEPS):
        if check_stop_requested():
            return False, False
        if not a_done and endstop_a.value() == ENDSTOP_TRIGGERED_VALUE:
            a_done = True
        if not b_done and endstop_b.value() == ENDSTOP_TRIGGERED_VALUE:
            b_done = True
        if a_done and b_done:
            return True, True
        if not a_done:
            step_once(step_a)
        if not b_done:
            step_once(step_b)
    return a_done, b_done  # timed out - at least one never triggered


def lower_both(steps, dir_up_a, dir_up_b):
    """Step both motors downward together for a fixed count."""
    dir_a.value(0 if dir_up_a else 1)
    dir_b.value(0 if dir_up_b else 1)
    for _ in range(steps):
        if check_stop_requested():
            return False
        step_once(step_a)
        step_once(step_b)
    return True


def cmd_raise():
    global homed, stop_requested
    stop_requested = False
    drivers_enable()
    ok_a, ok_b = home_both()
    if ok_a and ok_b:
        homed = True
        print("OK RAISED")
    elif stop_requested:
        homed = False
        print("OK STOPPED")
    else:
        homed = False
        print("ERROR HOMING_FAILED")


def cmd_lower():
    global stop_requested
    if not homed:
        print("ERROR NOT_HOMED")
        return
    stop_requested = False
    drivers_enable()
    completed = lower_both(LOWER_STEPS, not DIR_UP_A, not DIR_UP_B)
    if completed:
        print("OK LOWERED")
    elif stop_requested:
        print("OK STOPPED")
    else:
        print("ERROR LOWER_FAILED")


def cmd_status():
    print("HOMED" if homed else "NOT_HOMED")


def cmd_jog(step_pin, dir_pin, dir_up):
    """Move one motor JOG_STEPS in one direction. No endstop check, no
    homed-state requirement -- purely for confirming DIR polarity by eye
    at a distance too small to cause damage."""
    global stop_requested
    stop_requested = False
    drivers_enable()
    dir_pin.value(dir_up)
    for _ in range(JOG_STEPS):
        if check_stop_requested():
            print("OK STOPPED")
            return
        step_once(step_pin)
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
        elif cmd == "STOP":
            print("OK IDLE")  # nothing running; STOP mid-motion is handled inline
        elif cmd == "STATUS":
            cmd_status()
        elif cmd == "JOG_A_UP":
            cmd_jog(step_a, dir_a, DIR_UP_A)
        elif cmd == "JOG_A_DOWN":
            cmd_jog(step_a, dir_a, not DIR_UP_A)
        elif cmd == "JOG_B_UP":
            cmd_jog(step_b, dir_b, DIR_UP_B)
        elif cmd == "JOG_B_DOWN":
            cmd_jog(step_b, dir_b, not DIR_UP_B)
        elif cmd == "":
            continue
        else:
            print("ERROR UNKNOWN_COMMAND")


main()
