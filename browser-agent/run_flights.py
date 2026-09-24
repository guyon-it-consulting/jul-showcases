"""run_flights — the exact Browser Use × Jev scenario, on a REAL site.

Drives Google Flights to search Zürich → London, with the on-device brain:
JuL decides each operation/target, the Apple Foundation Model writes the city
names. Reports the same kind of numbers as jev-ultrafast (steps, wall clock),
all on-device for $0.

Run:
    python browser-agent/run_flights.py            # headless
    python browser-agent/run_flights.py --headed   # watch it (recommended)
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from agent_web import WebFlightsAgent, DEFAULT_MODEL, Choice  # noqa: E402

URL = "https://www.google.com/travel/flights?hl=en"
DEFAULT_GOAL = ("Search one-way flights from Zurich to London in economy, "
                "then stop when flight results are visible.")


def run(goal: str, model: str, headed: bool, keep_open: bool) -> None:
    from playwright.sync_api import sync_playwright

    print(f"Goal : {goal}")
    print(f"URL  : {URL}")
    print(f"Brain: {model} (JuL decides) + Apple Foundation Model (writes text)\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)

        agent = WebFlightsAgent(page, goal, model=model)
        # Warm the model (first call loads weights; excluded from timing).
        agent.client.system_one(state="warmup",
                                questions={"c": Choice(instructions="pick", criteria={"a": "x", "b": "y"})})

        if agent.handle_consent():
            print("· accepted cookie consent\n")

        t0 = time.perf_counter()
        decide_ms = write_ms = 0
        for rec in agent.run():
            tag = {"ok": "→", "done": "✓", "stuck": "⚠"}.get(rec["result"], "→")
            extra = f'  ⌨ "{rec["text"]}" ({rec["write_ms"]}ms)' if rec["text"] else ""
            print(f'{tag} step {rec["step"]:2d}  {rec["op"]:9s} conf={rec["op_conf"]:.2f}  '
                  f'{(rec["label"] or ""):32.32}  decide={rec["decide_ms"]}ms{extra}')
            decide_ms += rec["decide_ms"]
            write_ms += rec["write_ms"]

        wall_ms = int((time.perf_counter() - t0) * 1000)
        url_now = page.url
        # Outcome check: both cities entered, and result-like content on the page.
        try:
            has_from = page.get_by_role("combobox", name="Where from?").first.input_value()
        except Exception:
            has_from = ""
        import re
        body = ""
        try:
            body = page.inner_text("body")
        except Exception:
            pass
        cities_ok = ("Zurich" in body or "Zürich" in body) and "London" in body
        priced = bool(re.search(r"[€$£]\s?\d", body))
        reached = "/search" in url_now or (cities_ok and priced)
        if keep_open and headed:
            print("\n(keeping browser open 20s for inspection)")
            page.wait_for_timeout(20000)
        browser.close()

    print("\n" + "=" * 64)
    print(f"  Steps           : {len(agent.history)}")
    print(f"  Final URL       : {url_now}")
    print(f"  Looks reached   : {'likely' if reached else 'unclear'}")
    print(f"  JuL decide time : {decide_ms} ms total")
    print(f"  FM write time   : {write_ms} ms total")
    print(f"  Wall clock      : {wall_ms} ms  (vs jev-ultrafast's ~7,100 ms hosted)")
    print(f"  Cost            : $0.00  (both models on-device)")
    print("=" * 64)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="On-device browser agent on real Google Flights (Zürich→London).")
    ap.add_argument("--goal", default=DEFAULT_GOAL)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--headed", action="store_true", help="show the browser")
    ap.add_argument("--keep-open", action="store_true", help="hold the browser open at the end (headed)")
    args = ap.parse_args()
    run(args.goal, args.model, args.headed, args.keep_open)
