"""browser-agent — a fully on-device browser agent.

JuL decides the operation and target (speculative fan-out in one pass); the Apple
Foundation Model writes field text on TYPE_TEXT; Playwright executes. Nothing
leaves the Mac: no cloud, no API key, no cost.

By default it drives a bundled local demo site (a multi-step flight search), so
the loop is fully reproducible with no external site or anti-bot. Point --url at
any page to try elsewhere.

Run:
    python browser-agent/run.py
    python browser-agent/run.py --headed          # watch the browser
    python browser-agent/run.py --goal "Find one-way flights from Paris to Tokyo in business"
"""

from __future__ import annotations

import argparse
import functools
import http.server
import os
import socketserver
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from agent import BrowserAgent, DEFAULT_MODEL  # noqa: E402

SITE_DIR = Path(__file__).parent / "demo_site"
DEFAULT_GOAL = ("Search round-trip flights from Zurich to London in economy class, "
                "then stop when flight results are visible.")


def serve_site(directory: Path) -> tuple[socketserver.TCPServer, int]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    httpd.RequestHandlerClass.log_message = lambda *a, **k: None  # quiet
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


def run(url: str | None, goal: str, model: str, headed: bool) -> None:
    from playwright.sync_api import sync_playwright

    httpd = None
    if url is None:
        httpd, port = serve_site(SITE_DIR)
        url = f"http://127.0.0.1:{port}/index.html"

    print(f"Goal : {goal}")
    print(f"URL  : {url}")
    print(f"Model: {model}  (JuL decides) + Apple Foundation Model (writes text)\n")

    total0 = time.perf_counter()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page()
        page.goto(url)

        agent = BrowserAgent(page, goal, model=model)
        # Warm both models before timing the run (first calls load weights).
        agent.client.system_one(state="warmup", questions={
            "c": __import__("agent").Choice(instructions="pick", criteria={"a": "x", "b": "y"})})

        decide_ms_total = write_ms_total = 0
        for rec in agent.run():
            tag = {"ok": "→", "done": "✓", "stuck": "⚠"}.get(rec["result"], "→")
            extra = f'  ⌨ "{rec["text"]}" ({rec["write_ms"]}ms)' if rec["text"] else ""
            print(f'{tag} step {rec["step"]:2d} [{rec["page"]:>7}]  '
                  f'{rec["op"]:9s} conf={rec["op_conf"]:.2f}  '
                  f'{(rec["label"] or ""):22.22}  decide={rec["decide_ms"]}ms{extra}')
            decide_ms_total += rec["decide_ms"]
            write_ms_total += rec["write_ms"]

        # Verify outcome independently (don't trust DONE alone).
        final = page.evaluate("() => document.body.getAttribute('data-page')")
        results_visible = page.evaluate(
            "() => !!document.querySelector('#results-list .result')")
        browser.close()

    if httpd:
        httpd.shutdown()

    total_ms = int((time.perf_counter() - total0) * 1000)
    print("\n" + "=" * 62)
    print(f"  Steps           : {len(agent.history)}")
    print(f"  Goal reached    : {'YES' if results_visible else 'no'} (page='{final}')")
    print(f"  JuL decide time : {decide_ms_total} ms total "
          f"({decide_ms_total // max(1, len(agent.history))} ms/step avg)")
    print(f"  FM write time   : {write_ms_total} ms total (only on TYPE_TEXT steps)")
    print(f"  Wall clock      : {total_ms} ms")
    print(f"  Cost            : $0.00  (both models on-device, nothing sent)")
    print("=" * 62)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="On-device browser agent: JuL decides, Apple FM writes.")
    ap.add_argument("--url", default=None, help="page to drive (default: bundled local demo site)")
    ap.add_argument("--goal", default=DEFAULT_GOAL, help="natural-language goal")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="JuL model preset")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    args = ap.parse_args()
    run(args.url, args.goal, args.model, args.headed)
