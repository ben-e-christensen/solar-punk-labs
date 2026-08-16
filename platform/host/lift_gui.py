"""
GUI + automation for the Z-lift platform, run on the Raspberry Pi 5.

Workflow (see CLAUDE.md):
  - BEGIN: raises until both top endstops trigger (works from any starting
    position), then arms the automation.
  - CYCLE: lowers until both BOTTOM endstops trigger, then raises back to
    the top endstops. Fully stateless -- both legs run to endstops, no
    step-count memory. Runs automatically every CYCLE_INTERVAL_MIN minutes
    once BEGIN has completed; the button also fires one on demand.
  - STOP: aborts any motion immediately and cancels the automation
    (click BEGIN to re-home and restart it).
  - BEGIN STRESS TEST: mechanical soak test -- homes up like BEGIN, then
    runs lower+raise cycles back-to-back (1 s pause between) until STOP
    or a motion error. Each segment still saves CSV/PNG data as usual.
  - LOWER FULL: lower by the firmware's fixed FULL_LOWER_STEPS count,
    IGNORING the bottom endstops -- recovery move for when a stuck bottom
    endstop makes LOWER stop instantly.

Charge data (two ADS1115 electrometer channels, "roots" and
"grounded_roots") is sampled ONLY while the platform is moving, at
SAMPLE_HZ (100 Hz; the ADCs run in continuous-conversion mode so each
sample is one register read). After every raise/lower segment the samples are written
to data/<timestamp>_<segment>.csv, plotted to a matching .png, and shown
in a single reusable graph window (updated in place rather than opening a
new window per segment, so the 30-minute automation doesn't accumulate
windows).

Also includes the Jog bench-test panel and the Reset Board button (fixes a
board left in raw REPL by mpremote, where main.py isn't running).

Usage:
    python3 lift_gui.py          (venv active; needs pyserial, smbus2,
                                  matplotlib)
"""

import csv
import pathlib
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import serial

import charge_sensors
import lift_control

POLL_STATUS_SECONDS = 5
SAMPLE_HZ = 100            # sensor sample rate while the platform is moving
CYCLE_INTERVAL_MIN = 30    # automated lower+raise cycle period
DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


class LiftGUI:
    def __init__(self, root):
        self.root = root
        root.title("Z-Lift Control")

        self.result_queue = queue.Queue()
        self.busy = False
        self.moving = False            # a RAISE/LOWER is in flight
        self.cycle_phase = None        # None | "begin" | "lower" | "raise"
        self.auto_after_id = None
        self.stress = False            # stress test: back-to-back cycles until STOP
        self.stress_cycles = 0
        self.segment_name = None       # "raise" / "lower" while moving
        self.segment_samples = []      # (elapsed_s, wall_time, {name: value})
        self.segment_start = None
        self.graph_window = None
        self.graph_canvas = None
        self.graph_figure = None

        main = ttk.Frame(root, padding=12)
        main.grid(sticky="nsew")

        self.status_var = tk.StringVar(value="Status: unknown")
        ttk.Label(main, textvariable=self.status_var, font=("", 12, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 2)
        )
        self.auto_var = tk.StringVar(value="Automation: off (click BEGIN)")
        ttk.Label(main, textvariable=self.auto_var).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 10)
        )

        self.begin_btn = ttk.Button(main, text="BEGIN", command=self.begin_pressed)
        self.begin_btn.grid(row=2, column=0, sticky="ew", padx=2, pady=2)
        self.cycle_btn = ttk.Button(main, text="CYCLE", command=self.cycle_pressed)
        self.cycle_btn.grid(row=2, column=1, sticky="ew", padx=2, pady=2)
        self.stop_btn = ttk.Button(main, text="STOP", command=self.stop_pressed)
        self.stop_btn.grid(row=2, column=2, sticky="ew", padx=2, pady=2)

        self.stress_btn = ttk.Button(main, text="BEGIN STRESS TEST", command=self.stress_pressed)
        self.stress_btn.grid(row=3, column=0, columnspan=2, sticky="ew", padx=2, pady=2)
        self.lower_full_btn = ttk.Button(
            main, text="LOWER FULL", command=lambda: self.run_command("LOWER_FULL")
        )
        self.lower_full_btn.grid(row=3, column=2, sticky="ew", padx=2, pady=2)

        ttk.Separator(main).grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)

        ttk.Label(main, text="Jog (small move, ignores endstops -- for checking DIR polarity)").grid(
            row=5, column=0, columnspan=3, sticky="w"
        )
        self.jog_a_up_btn = ttk.Button(main, text="A ▲", command=lambda: self.run_command("JOG_A_UP"))
        self.jog_a_up_btn.grid(row=6, column=0, sticky="ew", padx=2, pady=2)
        self.jog_a_down_btn = ttk.Button(main, text="A ▼", command=lambda: self.run_command("JOG_A_DOWN"))
        self.jog_a_down_btn.grid(row=7, column=0, sticky="ew", padx=2, pady=2)
        self.jog_b_up_btn = ttk.Button(main, text="B ▲", command=lambda: self.run_command("JOG_B_UP"))
        self.jog_b_up_btn.grid(row=6, column=1, sticky="ew", padx=2, pady=2)
        self.jog_b_down_btn = ttk.Button(main, text="B ▼", command=lambda: self.run_command("JOG_B_DOWN"))
        self.jog_b_down_btn.grid(row=7, column=1, sticky="ew", padx=2, pady=2)
        self.endstops_btn = ttk.Button(main, text="ENDSTOPS", command=lambda: self.run_command("ENDSTOPS"))
        self.endstops_btn.grid(row=6, column=2, rowspan=2, sticky="nsew", padx=2, pady=2)

        ttk.Separator(main).grid(row=8, column=0, columnspan=3, sticky="ew", pady=8)

        ttk.Label(main, text="Charge sensors (live only while platform is moving)").grid(
            row=9, column=0, columnspan=3, sticky="w"
        )
        self.sensor_var = tk.StringVar(value="platform idle")
        ttk.Label(main, textvariable=self.sensor_var, font=("Courier", 11)).grid(
            row=10, column=0, columnspan=3, sticky="w", padx=2, pady=(0, 4)
        )

        ttk.Separator(main).grid(row=11, column=0, columnspan=3, sticky="ew", pady=8)

        self.reset_btn = ttk.Button(main, text="Reset Board (fix stuck/unresponsive)", command=self.reset_board)
        self.reset_btn.grid(row=12, column=0, columnspan=3, sticky="ew", padx=2, pady=2)

        self.log = tk.Text(main, width=58, height=14, state="disabled")
        self.log.grid(row=13, column=0, columnspan=3, sticky="nsew", pady=(10, 0))

        # STOP is intentionally NOT in this list: it must stay clickable
        # while a RAISE/LOWER is in flight, or it can't abort anything.
        self.buttons = [
            self.begin_btn,
            self.cycle_btn,
            self.stress_btn,
            self.lower_full_btn,
            self.jog_a_up_btn,
            self.jog_a_down_btn,
            self.jog_b_up_btn,
            self.jog_b_down_btn,
            self.endstops_btn,
            self.reset_btn,
        ]

        if not MATPLOTLIB_AVAILABLE:
            self.log_line("matplotlib not installed -- graphs disabled, CSVs still saved")

        self.root.after(200, self.poll_queue)
        self.root.after(1000, self.auto_status)

    # ------------------------------------------------------------------ util

    def log_line(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for b in self.buttons:
            b.configure(state=state)

    # -------------------------------------------------------------- commands

    def run_command(self, command):
        if self.busy:
            return
        self.set_busy(True)
        if command in ("RAISE", "LOWER", "LOWER_FULL"):
            self.start_segment("raise" if command == "RAISE" else "lower")
        self.log_line(f"> {command}")

        def worker():
            try:
                reply = lift_control.send_command(command)
            except serial.SerialException as e:
                reply = f"ERROR CONNECTION: {e}"
            self.result_queue.put((command, reply))

        threading.Thread(target=worker, daemon=True).start()

    def begin_pressed(self):
        """First raise of a session: home up to the top endstops (works from
        any starting position). On success, automation starts."""
        if self.busy:
            return
        self.cycle_phase = "begin"
        self.run_command("RAISE")

    def cycle_pressed(self):
        self.start_cycle(manual=True)

    def stress_pressed(self):
        """Mechanical stress test: home up (like BEGIN), then run lower+raise
        cycles back-to-back until STOP or a motion error."""
        if self.busy:
            return
        self.cancel_auto_cycle()
        self.stress = True
        self.stress_cycles = 0
        self.auto_var.set("Stress test: homing raise...")
        self.log_line("stress test: starting with homing raise")
        self.cycle_phase = "begin"
        self.run_command("RAISE")

    def start_cycle(self, manual=False):
        if self.busy:
            if not manual:
                if self.stress:
                    # STATUS poll etc. in the way; retry quickly.
                    self.schedule_next_stress_cycle(delay_ms=2000)
                else:
                    # Auto-fire collided with something in progress; retry soon.
                    self.log_line("auto-cycle deferred (busy), retrying in 60s")
                    self.schedule_auto_cycle(delay_ms=60 * 1000)
            return
        self.cancel_auto_cycle()
        self.cycle_phase = "lower"
        self.log_line("cycle: lowering...")
        self.run_command("LOWER")

    def stop_pressed(self):
        self.cancel_auto_cycle()
        if self.stress:
            self.log_line(f"stress test stopped after {self.stress_cycles} full cycle(s)")
        self.stress = False
        self.auto_var.set("Automation: off (click BEGIN)")
        self.cycle_phase = None
        if not self.moving:
            self.run_command("STOP")
            return
        # A RAISE/LOWER worker is blocked holding a serial read for its
        # reply. Send STOP write-only on a second handle (Linux allows the
        # port to be opened twice); the firmware picks it up mid-motion and
        # the in-flight worker receives the "OK STOPPED" reply as usual.
        self.log_line("> STOP (mid-motion)")

        def worker():
            try:
                with serial.Serial(lift_control.PORT, lift_control.BAUD, timeout=2) as ser:
                    ser.write(b"STOP\n")
            except serial.SerialException as e:
                self.result_queue.put(("STOP", f"ERROR CONNECTION: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def reset_board(self):
        if self.busy:
            return
        self.set_busy(True)
        self.log_line("> RESET BOARD")

        def worker():
            try:
                with serial.Serial(lift_control.PORT, lift_control.BAUD, timeout=2) as ser:
                    ser.reset_input_buffer()
                    ser.write(b"\x02")  # Ctrl-B: exit raw REPL -> friendly REPL
                    time.sleep(0.3)
                    ser.write(b"\x04")  # Ctrl-D: soft reset from friendly REPL -> runs main.py
                    time.sleep(1.0)
                    out = ser.read(500).decode(errors="replace")
                if "READY" in out:
                    reply = "OK REBOOTED"
                else:
                    reply = f"UNCERTAIN, raw output: {out!r}"
            except serial.SerialException as e:
                reply = f"ERROR CONNECTION: {e}"
            self.result_queue.put(("RESET", reply))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------ automation

    def schedule_auto_cycle(self, delay_ms=None):
        self.cancel_auto_cycle()
        if delay_ms is None:
            delay_ms = CYCLE_INTERVAL_MIN * 60 * 1000
        self.auto_after_id = self.root.after(delay_ms, self.start_cycle)
        due = time.strftime("%H:%M:%S", time.localtime(time.time() + delay_ms / 1000))
        self.auto_var.set(f"Automation: next cycle at {due} (every {CYCLE_INTERVAL_MIN} min)")

    def cancel_auto_cycle(self):
        if self.auto_after_id is not None:
            self.root.after_cancel(self.auto_after_id)
            self.auto_after_id = None

    def schedule_next_stress_cycle(self, delay_ms=1000):
        """Brief pause between stress cycles so replies/logs stay legible and
        the motors get a beat between direction reversals."""
        self.cancel_auto_cycle()
        self.auto_after_id = self.root.after(delay_ms, self.start_cycle)
        self.auto_var.set(f"Stress test: running ({self.stress_cycles} cycle(s) done) -- STOP to end")

    # --------------------------------------------------------- data capture

    def start_segment(self, name):
        self.segment_name = name
        self.segment_samples = []
        self.segment_start = time.time()
        self.moving = True
        threading.Thread(
            target=self._sample_loop,
            args=(self.segment_samples, self.segment_start),
            daemon=True,
        ).start()

    def _sample_loop(self, samples, started):
        """Dedicated 100 Hz sampler thread, one per motion segment. The ADCs
        run in continuous-conversion mode (860 SPS internally), so each
        sample is just a register read per sensor. Exits when the segment's
        reply arrives (self.moving cleared) or a new segment replaces the
        sample list. Drops to 1 Hz if no sensor is delivering data, so an
        unwired bench run doesn't log thousands of error rows."""
        sampler = charge_sensors.ContinuousSampler()
        sampler.start()
        period = 1.0 / SAMPLE_HZ if sampler.ok else 1.0
        next_t = time.monotonic()
        try:
            while self.moving and self.segment_samples is samples:
                now = time.time()
                readings = sampler.read()
                samples.append((now - started, now, readings))
                if len(samples) % max(1, int(SAMPLE_HZ / 4)) == 1:
                    text = "   ".join(
                        f"{k}: {v:.4f} V" if isinstance(v, float) else f"{k}: {v}"
                        for k, v in readings.items()
                    )
                    self.root.after(0, self.sensor_var.set, text)
                next_t += period
                delay = next_t - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_t = time.monotonic()  # fell behind; don't burst
        finally:
            sampler.stop()
        self.root.after(0, self.sensor_var.set, "platform idle")

    def finish_segment(self):
        name = self.segment_name
        samples = self.segment_samples
        started = self.segment_start
        self.moving = False
        self.segment_name = None
        if not name or not samples:
            return
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(started))
        base = DATA_DIR / f"{stamp}_{name}"
        try:
            DATA_DIR.mkdir(exist_ok=True)
            with open(base.with_suffix(".csv"), "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "elapsed_s", "roots_V", "grounded_roots_V"])
                for elapsed, wall, readings in samples:
                    writer.writerow([
                        time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(wall))
                        + f".{int((wall % 1) * 1000):03d}",
                        f"{elapsed:.3f}",
                        readings.get("roots", ""),
                        readings.get("grounded_roots", ""),
                    ])
            self.log_line(f"saved {base.name}.csv ({len(samples)} samples)")
        except OSError as e:
            self.log_line(f"CSV save failed: {e}")
        self.show_graph(name, stamp, samples, base.with_suffix(".png"))

    # ------------------------------------------------------------- graphing

    def show_graph(self, name, stamp, samples, png_path):
        if not MATPLOTLIB_AVAILABLE:
            return
        numeric = {
            sensor: [
                (elapsed, readings[sensor])
                for elapsed, _, readings in samples
                if isinstance(readings.get(sensor), float)
            ]
            for sensor in ("roots", "grounded_roots")
        }
        if self.graph_window is None or not self.graph_window.winfo_exists():
            self.graph_window = tk.Toplevel(self.root)
            self.graph_window.title("Charge data")
            self.graph_figure = Figure(figsize=(7, 4), dpi=100)
            self.graph_canvas = FigureCanvasTkAgg(self.graph_figure, master=self.graph_window)
            self.graph_canvas.get_tk_widget().pack(fill="both", expand=True)
        fig = self.graph_figure
        fig.clear()
        ax = fig.add_subplot(111)
        plotted = False
        for sensor, points in numeric.items():
            if points:
                xs, ys = zip(*points)
                ax.plot(xs, ys, label=sensor)
                plotted = True
        ax.set_xlabel("elapsed (s)")
        ax.set_ylabel("voltage (V)")
        ax.set_title(f"{name} @ {stamp}")
        if plotted:
            ax.legend()
        else:
            ax.text(0.5, 0.5, "no numeric sensor data\n(sensors unreadable this segment)",
                    ha="center", va="center", transform=ax.transAxes)
        fig.tight_layout()
        self.graph_canvas.draw()
        self.graph_window.lift()
        try:
            fig.savefig(png_path)
            self.log_line(f"saved {png_path.name}")
        except OSError as e:
            self.log_line(f"PNG save failed: {e}")

    # -------------------------------------------------------------- polling

    def auto_status(self):
        if not self.busy:
            self.run_command("STATUS")
        self.root.after(POLL_STATUS_SECONDS * 1000, self.auto_status)

    def poll_queue(self):
        try:
            while True:
                command, reply = self.result_queue.get_nowait()
                self.log_line(f"< {reply}")
                if command in ("RAISE", "LOWER", "LOWER_FULL"):
                    self.finish_segment()
                if command in ("STATUS", "RAISE", "LOWER", "LOWER_FULL"):
                    if "HOMED" in reply and "NOT_HOMED" not in reply:
                        self.status_var.set("Status: HOMED (raised)")
                    elif "NOT_HOMED" in reply:
                        self.status_var.set("Status: NOT HOMED")
                    elif reply.startswith("ERROR CONNECTION"):
                        self.status_var.set("Status: board not responding")
                self.set_busy(False)
                self.advance_cycle(command, reply)
        except queue.Empty:
            pass
        self.root.after(200, self.poll_queue)

    def advance_cycle(self, command, reply):
        """State machine for BEGIN and CYCLE sequences."""
        phase = self.cycle_phase
        if phase is None:
            return
        ok = reply.startswith("OK") and "STOPPED" not in reply
        if phase == "begin" and command == "RAISE":
            self.cycle_phase = None
            if ok:
                if self.stress:
                    self.log_line("stress test: homed, cycling until STOP")
                    self.schedule_next_stress_cycle()
                else:
                    self.log_line("BEGIN complete -- automation armed")
                    self.schedule_auto_cycle()
            else:
                self.stress = False
                self.auto_var.set("Automation: off (BEGIN failed -- fix and retry)")
        elif phase == "lower" and command in ("LOWER", "LOWER_FULL"):
            if ok:
                self.cycle_phase = "raise"
                self.log_line("cycle: raising...")
                self.run_command("RAISE")
            else:
                self.cycle_phase = None
                if self.stress:
                    self.log_line(
                        f"STRESS TEST ABORTED by motion error after {self.stress_cycles} cycle(s)"
                    )
                self.stress = False
                self.auto_var.set("Automation: off (cycle failed -- click BEGIN to restart)")
        elif phase == "raise" and command == "RAISE":
            self.cycle_phase = None
            if ok:
                if self.stress:
                    self.stress_cycles += 1
                    self.log_line(f"stress cycle {self.stress_cycles} complete")
                    self.schedule_next_stress_cycle()
                else:
                    self.log_line("cycle complete")
                    self.schedule_auto_cycle()
            else:
                if self.stress:
                    self.log_line(
                        f"STRESS TEST ABORTED by motion error after {self.stress_cycles} cycle(s)"
                    )
                self.stress = False
                self.auto_var.set("Automation: off (cycle failed -- click BEGIN to restart)")


def main():
    root = tk.Tk()
    LiftGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
