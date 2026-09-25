"""record_run — film a real qa-browser run, with JuL's decisions shown on the page.

    python qa-browser/record_run.py qa-browser/tickets/truffaut-arrosoir.md
    # -> qa-browser/demo_truffaut.mp4

It runs `run.py` unchanged and only listens in: before each action it outlines the element JuL
picked and writes the step and the decision in a caption at the bottom of the page, then grabs
frames. Frames are taken only around actions, so the time JuL spends thinking is cut from the
video; the real decision time is printed in each caption.
"""

from __future__ import annotations

import os
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

OVERLAY = """(a) => {
  let o = document.getElementById('qa-ov');
  if (!o) { o = document.createElement('div'); o.id = 'qa-ov'; document.documentElement.appendChild(o); }
  o.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483647;background:rgba(15,23,42,.94);' +
    'color:#fff;font:20px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;padding:16px 28px;box-shadow:0 -4px 16px rgba(0,0,0,.3)';
  if (a.card) o.style.cssText += ';top:0;display:flex;flex-direction:column;justify-content:center;padding:60px 120px;font-size:24px';
  o.innerHTML = '';
  for (const [text, style] of a.lines) { const d = document.createElement('div'); d.textContent = text;
    d.style.cssText = style || ''; d.style.whiteSpace = 'pre-wrap'; o.appendChild(d); }
  const b = document.createElement('div'); b.textContent = 'JuL · local · 0 token généré · 0 €';
  b.style.cssText = 'position:absolute;right:24px;top:12px;font-size:14px;color:#94a3b8'; o.appendChild(b);
}"""
MUTED, STRONG = "color:#94a3b8;font-size:16px", "font-weight:600"
OK, KO = "color:#4ade80;font-weight:600", "color:#f87171;font-weight:600"


def show(lines, card=False, frames=6):
    page = S["page"]
    try:
        page.page.evaluate(OVERLAY, {"lines": lines, "card": card})
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
    t, step = S["ticket"], S["step"]
    n = t.steps.index(step) + 1
    op, el, conf, ms, how = S["dec"]
    lines = [(f"Étape {n}/{len(t.steps)} — PO : {step.text}", STRONG)]
    if el is not None:
        what = f"{op.upper()} {qa.describe(el)}"
        if op == "type" and step.quoted:
            what += f'   ⌨ "{step.quoted[0]}"'
        src = f"JuL, confiance {conf:.2f}, décision en {ms / 1000:.0f} s" if how == "jul" else "rejoué depuis la trace"
        lines.append((("✓ " if done else "→ ") + what, OK if done else ""))
        lines.append((src, MUTED))
    return lines


orig_init, orig_pick, orig_click, orig_type, orig_check = (
    qa.Page.__init__, qa.Brain.pick, qa.Page.click, qa.Page.type, qa.Brain.check)


def init(self, page):
    orig_init(self, page)
    S["page"] = self


def pick(self, step, page, last=None):
    if not S["intro"]:
        S["intro"] = True
        t = S["ticket"]
        lines = [(t.title, "font-size:30px;font-weight:700;margin-bottom:18px"), (f"Site : {t.site}", MUTED), ("", "")]
        lines += [(f"{i}. {s.text}", "") for i, s in enumerate(t.steps, 1)]
        lines += [("", ""), ("Critères de validation", STRONG)] + [(f"• {c.text}", "") for c in t.criteria]
        lines += [("", ""), ("Le PO écrit le test. JuL le joue dans un vrai navigateur.", "color:#fbbf24")]
        show(lines, card=True, frames=30)
    r = orig_pick(self, step, page, last)
    S["step"], S["dec"] = step, (r[0], r[1], r[2], self.ms[-1] if self.ms else 0, "jul")
    if r[1] is None:
        show(step_lines() + [("JuL : rien à faire ici, étape facultative ignorée", MUTED)], frames=8)
    return r


def click(self, el):
    highlight(self, el)
    show(step_lines(), frames=9)
    orig_click(self, el)
    show(step_lines(done=True), frames=6)


def type_(self, el, text):
    highlight(self, el)
    show(step_lines(), frames=8)
    orig_type(self, el, text)
    show(step_lines(done=True), frames=7)


def check(self, criterion, evidence):
    p = orig_check(self, criterion, evidence)
    S["crit"].append((criterion.text, p, self.ms[-1]))
    t = S["ticket"]
    lines = [("Critères de validation — vérifiés par JuL sur la page", STRONG)]
    for text, pr, ms in S["crit"]:
        lines.append((f"{'✓' if pr >= 0.5 else '✗'} {text}   (JuL {pr:.2f})", OK if pr >= 0.5 else KO))
    show(lines, frames=8)
    if len(S["crit"]) == len(t.criteria):
        passed = all(pr >= 0.5 for _, pr, _ in S["crit"])
        lines.append(("", ""))
        lines.append((f"{'PASS' if passed else 'FAIL'} — {len(t.steps)} étapes, {len(t.criteria)} critères, "
                      f"{self.calls} décisions JuL, 0 €", "font-size:28px;font-weight:700;" +
                      ("color:#4ade80" if passed else "color:#f87171")))
        lines.append(("Rejouable à volonté avec --replay : JuL ne revient que si la page a changé.", MUTED))
        show(lines, frames=25)
    return p


def main():
    ticket_path = sys.argv[1] if len(sys.argv) > 1 else str(HERE / "tickets" / "truffaut-arrosoir.md")
    out = HERE / ("demo_" + Path(ticket_path).stem.split("-")[0] + ".mp4")
    S["ticket"] = qa.parse(Path(ticket_path).read_text(encoding="utf-8"))
    if FRAMES.exists():
        shutil.rmtree(FRAMES)
    FRAMES.mkdir()
    qa.Page.__init__, qa.Brain.pick, qa.Page.click, qa.Page.type, qa.Brain.check = init, pick, click, type_, check
    sys.argv = [sys.argv[0], ticket_path] + sys.argv[2:]
    code = 0
    try:
        qa.main()
    except SystemExit as e:
        code = e.code or 0
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(FRAMES / "%05d.jpg"),
                    "-vf", "scale=1366:-2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(out)], check=True)
    print(f"Video: {out}  ({S['n']} frames at {FPS} fps)")
    sys.exit(code)


if __name__ == "__main__":
    main()
