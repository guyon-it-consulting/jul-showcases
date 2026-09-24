"""agent_web — the same on-device brain (JuL decides + Apple FM writes) driving a
REAL site: Google Flights, the exact scenario from Browser Use × Jev.

The decision logic is identical to agent.py (JuL speculative fan-out picks the
operation + target; the Apple Foundation Model writes field values). What changes
is the *executor*: real pages need combobox handling — after typing a city you
must pick the first suggestion — and a cookie-consent gate. That extra handling
is code (the harness), never the model, exactly as jev-ultrafast keeps the loop
in code.

Honest scope: Google Flights is a complex, anti-bot-heavy site with ARIA
comboboxes and a calendar date picker. This targets the city origin/destination +
search flow (Zürich → London), which is the crux of the demo; exact date entry
via the calendar is out of scope for this MVP (Flights still shows results).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from common.jul_helper import get_client, Choice, Noul, NoulCriteria  # noqa: E402
from fm_writer import FMWriter  # noqa: E402

SNAPSHOT_JS = (Path(__file__).parent / "snapshot.js").read_text()
MAX_STEPS = 8
DEFAULT_MODEL = "wemm-4b-4bit"

# Elements that are chrome/navigation, not part of the flight-search task. Filtering
# these keeps the action space focused (and the decision fast) — harness policy.
NOISE = ("main menu", "google", "skip to main content", "accessibility", "explore",
         "hotels", "vacation rentals", "change appearance", "google apps", "sign in",
         "learn more", "feedback", "deals with ai", "destinations", "departure",
         "return", "swap")


class WebFlightsAgent:
    def __init__(self, page, goal: str, model: str = DEFAULT_MODEL):
        self.page = page
        self.goal = goal
        self.client = get_client(model)
        self.fm = FMWriter()
        self.history: list[dict] = []
        self.done = False
        self._touched: set[str] = set()   # field labels we've already typed into this run

    # --- consent gate -------------------------------------------------------
    def handle_consent(self) -> bool:
        for name in ("Accept all", "Reject all"):
            try:
                btn = self.page.get_by_role("button", name=name)
                if btn.count():
                    btn.first.click(timeout=4000)
                    self.page.wait_for_timeout(3000)
                    return True
            except Exception:
                pass
        return False

    # --- observation --------------------------------------------------------
    def observe(self) -> dict:
        # Query the real interactive nodes with Playwright and keep handles, so we
        # act on the actual DOM node (like jev-ultrafast) instead of a reconstructed
        # CSS selector — far more robust on complex pages.
        handles = self.page.query_selector_all(
            "a, button, input, select, textarea, [role=button], [role=combobox], [onclick]")
        actions, self._handles = [], {}
        for h in handles:
            try:
                if not h.is_visible():
                    continue
            except Exception:
                continue
            info = h.evaluate("""el => {
                const byId = el.id && document.querySelector('label[for="'+el.id+'"]');
                const tag = el.tagName.toLowerCase();
                let label = (el.getAttribute('aria-label') || (byId && byId.innerText) ||
                             (el.innerText||'').trim() || el.getAttribute('placeholder') ||
                             el.name || el.id || tag).trim().slice(0,60);
                // TYPE_TEXT only for genuine text inputs / textarea. A div/button with
                // role=combobox is a menu -> CLICK, not a place to type.
                let op = 'CLICK';
                if (tag === 'textarea') op = 'TYPE_TEXT';
                else if (tag === 'input') {
                    const t = (el.type||'text').toLowerCase();
                    op = ['text','search','email','tel','url','number'].includes(t) ? 'TYPE_TEXT' : 'CLICK';
                } else if (tag === 'select') op = 'SELECT';
                return {label, op, value: (el.value||'').slice(0,40)};
            }""")
            info["label"] = info["label"] or ""
            if any(n in info["label"].lower() for n in NOISE):
                continue
            idx = str(len(actions))
            info["id"] = idx
            actions.append(info)
            self._handles[idx] = h
            if len(actions) >= 24:
                break
        page_marker = "results" if "/search" in self.page.url else "form"
        return {"url": self.page.url, "page": page_marker, "actions": actions}

    # --- decision (identical fan-out policy as agent.py) --------------------
    def decide(self, snap: dict) -> dict:
        actions = snap["actions"]
        # Mark prefilled text fields whose value does NOT match the goal as "to refill".
        # JuL judges each with a Noul (measured reliable: Lyon vs Zurich goal -> 0.04).
        self._needs_refill = set()
        for a in actions:
            if a["op"] == "TYPE_TEXT" and a["value"] and a["label"] not in self._touched:
                r = self.client.system_one(
                    state=f'Goal: {self.goal}\nField "{a["label"]}" currently contains: "{a["value"]}"',
                    questions={"ok": Noul(
                        instructions=f'Does the current value of "{a["label"]}" already match what the goal requires?',
                        criteria=NoulCriteria(true="yes, correct for the goal",
                                              false="no, wrong value that must be replaced"))})
                if r.nouls["ok"].noul < 0.5:
                    self._needs_refill.add(a["id"])

        state = self._render_state(snap)

        clickable = {a["id"]: self._click_desc(a) for a in actions if a["op"] == "CLICK"}
        # A field is fillable if empty OR prefilled-but-wrong.
        typeable = {a["id"]: a["label"] for a in actions
                    if a["op"] == "TYPE_TEXT" and (not a["value"] or a["id"] in self._needs_refill)}

        op_criteria = {}
        if clickable:  op_criteria["CLICK"] = "click a button/link, e.g. search or submit, to progress"
        if typeable:   op_criteria["TYPE_TEXT"] = "type a city/value into an empty field"
        results = snap.get("page") == "results" or "results" in snap.get("url", "")
        op_criteria["DONE"] = ("flight results are visible; stop" if results
                               else "results already shown; stop")

        questions = {"operation": Choice(
            instructions="Pick the single best next operation to progress toward the goal.",
            criteria=op_criteria)}
        if len(clickable) >= 2:
            questions["click_target"] = Choice(
                instructions="Which element to click to progress toward the goal?", criteria=clickable)

        t0 = time.perf_counter()
        resp = self.client.system_one(state=state, questions=questions)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        op = resp.choices["operation"].choice
        op_conf = resp.choices["operation"].confidence

        target_id = None
        if op == "CLICK":
            target_id = (next(iter(clickable)) if len(clickable) == 1
                         else resp.choices["click_target"].choice)
        elif op == "TYPE_TEXT":
            fillable = [a["id"] for a in actions if a["op"] == "TYPE_TEXT"
                        and (not a["value"] or a["id"] in self._needs_refill)]
            target_id = fillable[0] if fillable else None

        action = next((a for a in actions if a["id"] == target_id), None)
        return {"op": op, "op_conf": op_conf, "action": action, "latency_ms": latency_ms}

    # --- one step -----------------------------------------------------------
    def step(self) -> dict:
        snap = self.observe()
        d = self.decide(snap)
        op, action = d["op"], d["action"]
        rec = {"step": len(self.history) + 1, "op": op, "op_conf": round(d["op_conf"], 3),
               "decide_ms": d["latency_ms"], "label": action["label"] if action else None,
               "text": None, "write_ms": 0}

        if op == "DONE" or action is None:
            self.done = True
            rec["result"] = "done"
            self.history.append(rec)
            return rec

        if op == "TYPE_TEXT":
            filled = {a["label"]: a["value"] for a in snap["actions"]
                      if a["op"] == "TYPE_TEXT" and a["value"]}
            value, write_ms = self.fm.write_field(self.goal, action["label"], action["value"], filled=filled)
            rec["text"], rec["write_ms"] = value, write_ms
            ok = self._fill_combobox(action, value)
            self._touched.add(action["label"])   # never re-flag this field for refill
        else:  # CLICK
            ok = self._click(action)

        if not ok:
            rec["result"] = "retry"      # stale element; re-observe next step
            self.history.append(rec)
            return rec

        self.page.wait_for_timeout(400)
        rec["result"] = "ok"
        self.history.append(rec)

        # Early success: Google Flights navigates to /search when results are shown.
        if "/search" in self.page.url:
            self.done = True
            rec["result"] = "done"
            return rec

        recent = self.history[-3:]
        if len(recent) == 3 and len({(r["op"], r["label"]) for r in recent}) == 1:
            self.done = True
            rec["result"] = "stuck"
        return rec

    # --- executor adapted to real widgets -----------------------------------
    def _fill_combobox(self, action: dict, value: str) -> bool:
        """Type into a field, then pick the first autocomplete suggestion. Returns success."""
        h = self._handles[action["id"]]
        try:
            h.click(timeout=4000)
            try:
                h.fill("")
            except Exception:
                pass
            h.type(value, delay=25)
        except Exception:
            return False
        # Wait for suggestions (combobox pattern), capped like jev-ultrafast.
        self.page.wait_for_timeout(400)
        try:
            opts = self.page.get_by_role("option")
            if opts.count():
                opts.first.click(timeout=3000)
            else:
                h.press("Enter")
        except Exception:
            pass
        return True

    def _click(self, action: dict) -> bool:
        try:
            self._handles[action["id"]].click(timeout=4000)
            return True
        except Exception:
            return False

    def run(self):
        for _ in range(MAX_STEPS):
            if self.done:
                break
            yield self.step()

    # --- helpers ------------------------------------------------------------
    def _click_desc(self, a: dict) -> str:
        lbl = a["label"].lower()
        if any(w in lbl for w in ("search", "explore", "done", "submit", "find")):
            return f'{a["label"]} — run the search and show flight results'
        if "swap" in lbl:
            return f'{a["label"]} — swap origin/destination (usually not needed)'
        return f'{a["label"]} — a control on the page'

    def _render_state(self, snap: dict) -> str:
        lines = [f"Goal: {self.goal}", f"Page: {snap.get('page')}", "Current controls:"]
        for a in snap["actions"]:
            v = f' = "{a["value"]}"' if a["value"] else (" = (empty)" if a["op"] == "TYPE_TEXT" else "")
            lines.append(f'  [{a["id"]}] {a["op"]} {a["label"]}{v}')
        if self.history:
            lines.append(f'Last action: {self.history[-1]["op"]} {self.history[-1].get("label")}')
        return "\n".join(lines)
