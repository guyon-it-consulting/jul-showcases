"""record_run — capture a screencast of the AX agent driving your real browser.

Playwright's sync API is single-threaded, so we grab frames on the MAIN thread:
a few before each step and several during the post-step settle/results-load. Then
ffmpeg assembles them into an MP4.

Usage:
    python browser-agent/record_run.py
    # -> browser-agent/frames/*.jpg and browser-agent/demo_sncf.mp4
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from agent_ax import AXAgent, DEFAULT_MODEL  # noqa: E402
from common.jul_helper import Choice  # noqa: E402

HERE = os.path.dirname(__file__)
FRAMES = os.path.join(HERE, "frames")
FPS = 6


class Recorder:
    def __init__(self, page):
        self.page = page
        self.n = 0
        if os.path.isdir(FRAMES):
            shutil.rmtree(FRAMES)
        os.makedirs(FRAMES)

    def snap(self, count=1, gap=0.12):
        for _ in range(count):
            try:
                self.page.screenshot(path=os.path.join(FRAMES, f"{self.n:05d}.jpg"),
                                     type="jpeg", quality=70)
                self.n += 1
            except Exception:
                pass
            if gap:
                time.sleep(gap)


def run(cdp_url: str, goal: str, url: str, out: str) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        ctx = browser.contexts[0]
        page = ctx.pages[-1] if ctx.pages else ctx.new_page()

        agent = AXAgent(page, goal, model=DEFAULT_MODEL)
        agent.client.system_one(state="warmup",
                                questions={"c": Choice(instructions="pick", criteria={"a": "x", "b": "y"})})
        agent.fm.warmup()

        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3500)
        page.bring_to_front()

        rec = Recorder(page)
        rec.snap(6)  # opening hold on the homepage

        print(f"Recording... goal: {goal}")
        # Drive step by step, grabbing frames around each action.
        while not agent.done and len(agent.history) < 12:
            r = agent.step()
            ex = f'  ⌨ "{r["text"]}"' if r.get("text") else ""
            print(f'  step {r["step"]:2d}  {r["op"]:9s}  {(r.get("label") or "")[:26]:26}{ex}')
            rec.snap(4)   # a few frames showing the resulting state
            # Once the search has been submitted (navigation to interstitial/results),
            # stop deciding and just record the results loading — no stray clicks.
            if "interstitiel" in page.url or "results" in page.url:
                break

        # Results loading + final hold.
        for _ in range(30):
            rec.snap(1, gap=0.25)
            if "results" in page.url:
                break
        rec.snap(12, gap=0.2)   # hold on the results

    print(f"\nCaptured {rec.n} frames. Assembling {out} ...")
    subprocess.run([
        "ffmpeg", "-y", "-framerate", str(FPS), "-i", os.path.join(FRAMES, "%05d.jpg"),
        "-vf", "scale=1280:-2,format=yuv420p", "-c:v", "libx264", "-preset", "medium",
        "-crf", "23", out,
    ], check=True)
    print(f"Done: {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdp", default="http://localhost:9222")
    ap.add_argument("--url", default="https://www.sncf-connect.com")
    ap.add_argument("--goal", default="Book a one-way train from Lyon to Toulouse in 3 days, "
                                      "then stop when journey results are visible.")
    ap.add_argument("--out", default=os.path.join(HERE, "demo_sncf.mp4"))
    args = ap.parse_args()
    run(args.cdp, args.goal, args.url, args.out)
