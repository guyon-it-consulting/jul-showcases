"""run_cdp — drive YOUR real browser (over CDP) with the fully on-device brain,
measured the same way as Browser Use × Jev's `jev-ultrafast`.

Architecture (same division of labor as jev-ultrafast):
  - JuL selects operation + target (speculative fan-out, one decision pass)
  - the Apple Foundation Model writes the field text on TYPE_TEXT (their Mercury role)
  - the code owns the loop; the action space comes from the accessibility tree

Measurement discipline, matched to jev-ultrafast/docs/performance.md:
  - both models are WARMED UP before the clock (their Mercury is cloud, no cold
    start; our JuL + Apple FM run locally, so we pay their cold start once, before)
  - initial navigation is EXCLUDED; the clock starts at the first decision
  - the clock ends at the accepted DONE (includes results loading)
  - we report the same family of outputs: model requests, interactions, FM calls,
    median decision latency, time-to-submit, and an independent outcome check

Prereqs (run once): launch your browser with remote debugging, open the target
site, pass consent/CAPTCHA by hand:
    /Applications/Arc.app/Contents/MacOS/Arc \
        --remote-debugging-port=9222 --user-data-dir="$HOME/.arc-agent"

Then:
    python browser-agent/run_cdp.py --url https://www.sncf-connect.com \
        --goal "Search a train journey from Lyon to Toulouse, stop at results"
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from agent_ax import AXAgent, DEFAULT_MODEL  # noqa: E402
from common.jul_helper import Choice  # noqa: E402

DEFAULT_GOAL = ("Search a train journey from Lyon to Toulouse, then stop when "
                "journey results are visible.")
SUBMIT_WORDS = ("voir les prix", "rechercher", "search", "valider", "voir les")


def run(cdp_url: str, goal: str, model: str, url: str | None, slow: float) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.pages[-1] if ctx.pages else ctx.new_page()

        agent = AXAgent(page, goal, model=model)

        # --- WARM UP both models BEFORE the clock (their Mercury has no cold start) ---
        print("Warming up JuL + Apple Foundation Model (excluded from the clock)...")
        jul_warm = time.perf_counter()
        agent.client.system_one(state="warmup",
                                questions={"c": Choice(instructions="pick", criteria={"a": "x", "b": "y"})})
        jul_warm_ms = int((time.perf_counter() - jul_warm) * 1000)
        fm_warm_ms = agent.fm.warmup()
        print(f"  JuL cold start: {jul_warm_ms} ms | Apple FM cold start: {fm_warm_ms} ms\n")

        # --- Initial navigation is EXCLUDED from the clock (as in jev-ultrafast) ---
        if url:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
        page.bring_to_front()

        print(f"Driving tab: {page.url[:70]}")
        print(f"Goal : {goal}")
        print(f"Brain: {model} (JuL decides) + Apple Foundation Model (writes)\n")

        # --- Clock starts at the first decision, ends at accepted DONE ---
        t0 = time.perf_counter()
        decide_lat, fm_calls, interactions = [], 0, 0
        submit_ms = None
        for rec in agent.run():
            tag = {"ok": "→", "done": "✓", "stuck": "⚠", "retry": "↻"}.get(rec["result"], "→")
            extra = f'  ⌨ "{rec["text"]}"' if rec["text"] else ""
            print(f'{tag} step {rec["step"]:2d}  {rec["op"]:9s} conf={rec["op_conf"]:.2f}  '
                  f'{(rec["label"] or ""):26.26}  decide={rec["decide_ms"]}ms{extra}')
            if rec["decide_ms"]:
                decide_lat.append(rec["decide_ms"])
            if rec["text"]:
                fm_calls += 1
            if rec["op"] in ("CLICK", "TYPE_TEXT", "SELECT") and rec["result"] == "ok":
                interactions += 1
            if submit_ms is None and rec["op"] == "CLICK" and rec["label"] \
                    and any(w in rec["label"].lower() for w in SUBMIT_WORDS):
                submit_ms = int((time.perf_counter() - t0) * 1000)
            if slow:
                time.sleep(slow)

        # After DONE, wait for the real results view to load (SNCF shows an
        # interstitial first). This loading interval is part of the clock, as in
        # jev-ultrafast ("the final interval includes results loading").
        for _ in range(20):
            if "results" in page.url:
                break
            page.wait_for_timeout(500)
        page.wait_for_timeout(1500)
        wall_ms = int((time.perf_counter() - t0) * 1000)
        final_url = page.url

        # --- Independent outcome check (not just DONE): both endpoints + priced results ---
        body = ""
        try:
            body = page.inner_text("body")
        except Exception:
            pass
        endpoints_ok = ("Lyon" in body) and ("Toulouse" in body)
        priced = any(sym in body for sym in ("€", "\u20ac"))
        on_results = "results" in final_url
        verified = on_results and endpoints_ok and priced

    med = int(statistics.median(decide_lat)) if decide_lat else 0
    print("\n" + "=" * 60)
    print(f"  Steps / interactions : {len(agent.history)} / {interactions}")
    print(f"  JuL decisions        : {len(decide_lat)}  (median {med} ms, total {sum(decide_lat)} ms)")
    print(f"  Apple FM writes      : {fm_calls}")
    print(f"  Time to submit       : {submit_ms} ms" if submit_ms else "  Time to submit       : n/a")
    print(f"  Wall clock (to DONE) : {wall_ms} ms")
    print(f"  Independent check    : {'VERIFIED' if verified else 'not verified'} "
          f"(results={on_results}, Lyon+Toulouse={endpoints_ok}, priced={priced})")
    print(f"  Final URL            : {final_url[:60]}")
    print(f"  Cost                 : $0.00  (both models on-device)")
    print("=" * 60)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Drive your real browser (CDP) with the on-device JuL+FM agent.")
    ap.add_argument("--cdp", default="http://localhost:9222")
    ap.add_argument("--goal", default=DEFAULT_GOAL)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--url", default=None, help="navigate here first, EXCLUDED from the clock")
    ap.add_argument("--slow", type=float, default=0.0, help="seconds to pause between steps (to watch)")
    args = ap.parse_args()
    run(args.cdp, args.goal, args.model, args.url, args.slow)
