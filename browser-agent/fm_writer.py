"""fm_writer — generate the value to type into a field, using the on-device
Apple Foundation Model via the `fm` CLI (macOS 26+, Apple Silicon).

This is the second, strictly separated brain of the agent: JuL *decides* which
operation and which element (never generates text); when the chosen operation is
TYPE_TEXT, the Apple Foundation Model *writes* the value. Both run 100% on-device
— no cloud, no API key, nothing leaves the Mac.

Requires the one-time `sudo fm license` acceptance. Verify with `fm available`.
"""

from __future__ import annotations

import subprocess
import time


class FMWriter:
    """Wraps `fm respond` to produce a single short field value."""

    def __init__(self, command: str = "fm"):
        self.command = command
        self.available = self._check()

    def _check(self) -> bool:
        try:
            out = subprocess.run([self.command, "available"],
                                 capture_output=True, text=True, timeout=20)
            return "available" in (out.stdout + out.stderr).lower()
        except Exception:
            return False

    def warmup(self) -> int:
        """Trigger the model's cold start before a timed run. Returns latency ms."""
        if not self.available:
            return 0
        _, ms = self.write_field("warmup", "city", "")
        return ms

    def write_field(self, goal: str, field_label: str, current_value: str = "",
                    filled: dict | None = None) -> tuple[str, int]:
        """Return (value_to_type, latency_ms). Falls back to '' if fm is unavailable.

        `filled` maps already-filled field labels to their values, so the model can
        disambiguate (e.g. if 'Where from?' is already 'Zurich', 'Where to?' is the
        other city in the goal).
        """
        if not self.available:
            return "", 0
        context = ""
        if filled:
            context = "Values already entered: " + ", ".join(f'{k}={v}' for k, v in filled.items()) + "\n"
        prompt = (
            "You are filling one field to progress toward a travel-search goal. "
            "Output ONLY the exact value to type — a place or city name — with no "
            "quotes, no explanation, no extra words.\n"
            f"Goal: {goal}\n"
            f"{context}"
            f'Field to fill now: "{field_label}"\n'
            "Given the goal and what is already entered, the next value to type is:"
        )
        t0 = time.perf_counter()
        try:
            out = subprocess.run([self.command, "respond", prompt],
                                 capture_output=True, text=True, timeout=30)
        except Exception:
            return "", int((time.perf_counter() - t0) * 1000)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        # Take the first non-empty line, strip stray quotes/markup.
        value = ""
        for line in out.stdout.splitlines():
            line = line.strip().strip('"').strip("'").strip()
            if line:
                value = line
                break
        return value, latency_ms


if __name__ == "__main__":
    w = FMWriter()
    print("fm available:", w.available)
    if w.available:
        v, ms = w.write_field("Fly from Zurich to London", "Where to?")
        print(f"-> {v!r} in {ms} ms")
