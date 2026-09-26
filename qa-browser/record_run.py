"""record_run — film real qa-browser runs, with JuL's decisions shown on the page.

    python qa-browser/record_run.py qa-browser/tickets/truffaut-arrosoir.md qa-browser/tickets/wordery-hobbit.md
    # -> qa-browser/demo.mp4 (one video, the tickets one after the other)

It runs `run.py` unchanged for each ticket and only listens in: before each action it outlines
the element JuL picked and writes the step and the decision in a caption, in the ticket's own
language, then grabs frames. Frames are taken only around actions, so the time JuL spends
thinking is cut from the video; the real decision time is printed in each caption.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import run as qa  # noqa: E402

FRAMES = HERE / "frames"
FPS = 5
S = {"page": None, "n": 0, "ticket": None, "step": None, "dec": None, "crit": [], "intro": False}

TEXT = {"site": "Site", "step": "Step", "po": "Product Manager", "crit": "Acceptance criteria",
        "assert": "In-journey assertion — checked by JuL on the page",
        "checked": "Acceptance criteria — checked by JuL on the page",
        "tag": "The Product Manager writes the test in English. JuL runs it in a real browser.",
        "jul": "JuL, confidence {c:.2f}, decided in {s:.0f} s", "replay": "replayed from the trace",
        "skip": "JuL: nothing to do here, optional step skipped",
        "sum": "{r} — {n} steps, {k} criteria, {d} JuL decisions, $0",
        "foot": "Replay at will with --replay: JuL only comes back if the page changed."}

OVERLAY = """(a) => {
  let o = document.getElementById('qa-ov');
  if (!o) { o = document.createElement('div'); o.id = 'qa-ov'; document.documentElement.appendChild(o); }
  o.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483647;background:rgba(15,23,42,.94);pointer-events:none;' +
    'color:#fff;font:20px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;padding:16px 28px;box-shadow:0 -4px 16px rgba(0,0,0,.3)';
  if (a.card) o.style.cssText += ';top:0;display:flex;flex-direction:column;justify-content:center;padding:60px 120px;font-size:24px';
  o.innerHTML = '';
  for (const [text, style] of a.lines) { const d = document.createElement('div'); d.textContent = text;
    d.style.cssText = style || ''; d.style.whiteSpace = 'pre-wrap'; o.appendChild(d); }
  const b = document.createElement('div'); b.textContent = a.badge;
  b.style.cssText = 'position:absolute;right:24px;top:12px;font-size:14px;color:#94a3b8'; o.appendChild(b);
}"""
MUTED, STRONG = "color:#94a3b8;font-size:16px", "font-weight:600"
OK, KO = "color:#4ade80;font-weight:600", "color:#f87171;font-weight:600"


def tr():
    return TEXT


def show(lines, card=False, frames=6):
    page = S["page"]
    badge = f"{S['idx']}/{S['total']} · JuL · local · 0 token · 0 €"
    try:
        page.page.evaluate(OVERLAY, {"lines": lines, "card": card, "badge": badge})
    except Exception:
        return
    for _ in range(frames):
        try:
            page.page.screenshot(path=str(FRAMES / f"{S['n']:05d}.jpg"), type="jpeg", quality=82)
            S["n"] += 1
        except Exception:
            pass
        page.page.wait_for_timeout(60)


def highlight(page, el):
    try:
        page._call(el, "function(){this.scrollIntoView({block:'center'});"
                       "this.style.outline='4px solid #f59e0b';this.style.outlineOffset='3px';}")
        page.page.wait_for_timeout(300)
    except Exception:
        pass


def step_lines(done=False):
    t, step, L = S["ticket"], S["step"], tr()
    n = t.steps.index(step) + 1
    op, el, conf, ms, how = S["dec"]
    lines = [(f"{L['step']} {n}/{len(t.steps)} — {L['po']} : {step.text}", STRONG)]
    if el is not None:
        what = f"{op.upper()} {qa.describe(el)}"
        if op == "type" and step.quoted:
            what += f'   ⌨ "{step.quoted[0]}"'
        src = L["jul"].format(c=conf, s=ms / 1000) if how == "jul" else L["replay"]
        lines.append((("✓ " if done else "→ ") + what, OK if done else ""))
        lines.append((src, MUTED))
    return lines


orig_init, orig_pick, orig_click, orig_type, orig_check = (
    qa.Page.__init__, qa.Brain.pick, qa.Page.click, qa.Page.type, qa.Brain.check)


def init(self, page):
    orig_init(self, page)
    S["page"] = self


def pick(self, step, page, last=None):
    L = tr()
    if not S["intro"]:
        S["intro"] = True
        t = S["ticket"]
        lines = [(t.title, "font-size:30px;font-weight:700;margin-bottom:18px"), (f"{L['site']} : {t.site}", MUTED), ("", "")]
        lines += [(f"{i}. {s.text}", "") for i, s in enumerate(t.steps, 1)]
        lines += [("", ""), (L["crit"], STRONG)] + [(f"• {c.text}", "") for c in t.criteria]
        lines += [("", ""), (L["tag"], "color:#fbbf24")]
        show(lines, card=True, frames=30)
    r = orig_pick(self, step, page, last)
    S["step"], S["dec"] = step, (r[0], r[1], r[2], self.ms[-1] if self.ms else 0, "jul")
    if r[1] is None:
        show(step_lines() + [(L["skip"], MUTED)], frames=8)
    return r


def hide():
    try:
        S["page"].page.evaluate("() => document.getElementById('qa-ov')?.remove()")
    except Exception:
        pass


def click(self, el):
    highlight(self, el)
    show(step_lines(), frames=9)
    hide()                                      # the caption must never be under the pointer
    orig_click(self, el)
    show(step_lines(done=True), frames=6)
    hide()


def type_(self, el, text):
    highlight(self, el)
    show(step_lines(), frames=8)
    hide()
    orig_type(self, el, text)
    show(step_lines(done=True), frames=7)
    hide()


def check(self, criterion, evidence):
    p = orig_check(self, criterion, evidence)
    L = tr()
    if getattr(criterion, "check", False):                  # a mid-journey assertion, not a final criterion
        show([(L["assert"], STRONG),
              (f"{'✓' if p >= 0.5 else '✗'} {criterion.text}   (JuL {p:.2f})", OK if p >= 0.5 else KO)],
             frames=12)
        return p
    S["crit"].append((criterion.text, p))
    t, L = S["ticket"], tr()
    lines = [(L["checked"], STRONG)]
    for text, pr in S["crit"]:
        lines.append((f"{'✓' if pr >= 0.5 else '✗'} {text}   (JuL {pr:.2f})", OK if pr >= 0.5 else KO))
    show(lines, frames=8)
    if len(S["crit"]) == len(t.criteria):
        passed = all(pr >= 0.5 for _, pr in S["crit"])
        lines.append(("", ""))
        lines.append((L["sum"].format(r="PASS" if passed else "FAIL", n=len(t.steps), k=len(t.criteria),
                                      d=self.calls), "font-size:28px;font-weight:700;" +
                      ("color:#4ade80" if passed else "color:#f87171")))
        lines.append((L["foot"], MUTED))
        show(lines, frames=25)
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tickets", nargs="*", default=[str(HERE / "tickets" / "vistaprint-cart-en.md")])
    ap.add_argument("--out", default=str(HERE / "demo.mp4"))
    args, rest = ap.parse_known_args()
    if FRAMES.exists():
        shutil.rmtree(FRAMES)
    FRAMES.mkdir()
    qa.Page.__init__, qa.Brain.pick, qa.Page.click, qa.Page.type, qa.Brain.check = init, pick, click, type_, check
    codes = []
    S["total"] = len(args.tickets)
    for i, path in enumerate(args.tickets, 1):
        S.update(ticket=qa.parse(Path(path).read_text(encoding="utf-8")), idx=i, intro=False, crit=[], step=None)
        sys.argv = [sys.argv[0], path] + rest
        try:
            qa.main()
            codes.append(0)
        except SystemExit as e:
            codes.append(e.code or 0)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(FRAMES / "%05d.jpg"),
                    "-vf", "scale=1366:-2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    args.out], check=True)
    print(f"Video: {args.out}  ({S['n']} frames at {FPS} fps), exit codes {codes}")
    sys.exit(max(codes))


if __name__ == "__main__":
    main()
