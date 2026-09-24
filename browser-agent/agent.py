"""agent — the observe -> decide -> write -> act loop.

Architecture (fully on-device):
  OBSERVE  Playwright + snapshot.js  -> indexed action table
  DECIDE   JuL system_one, speculative fan-out in ONE pass:
             - operation      : CLICK / TYPE_TEXT / SELECT / DONE
             - click_target   : which element, if CLICK
             - type_target    : which element, if TYPE_TEXT
             - select_target  : which element, if SELECT
           We keep the target matching the chosen operation. Two+ decisions,
           one model pass — the TypeSafe "speculative fan-out" pattern, native
           to JuL's system_one(questions={...}).
  WRITE    if TYPE_TEXT -> Apple Foundation Model (fm) generates the value.
  ACT      Playwright executes; freshness + anti-loop guards owned by the code.

JuL only ever *chooses*; it never generates text. The code owns the loop.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

sys_path = os.path.join(os.path.dirname(__file__), "..")
import sys
sys.path.insert(0, sys_path)
sys.path.insert(0, os.path.dirname(__file__))

from common.jul_helper import get_client, Choice  # noqa: E402
from fm_writer import FMWriter  # noqa: E402

SNAPSHOT_JS = (Path(__file__).parent / "snapshot.js").read_text()
MAX_STEPS = 12
DEFAULT_MODEL = "wemm-4b-4bit"   # accuracy matters more than raw speed for routing


class BrowserAgent:
    def __init__(self, page, goal: str, model: str = DEFAULT_MODEL):
        self.page = page
        self.goal = goal
        self.client = get_client(model)
        self.fm = FMWriter()
        self.history: list[dict] = []
        self.done = False

    def observe(self) -> dict:
        return self.page.evaluate(SNAPSHOT_JS)

    def decide(self, snap: dict) -> dict:
        """One JuL pass: operation + speculative targets. Returns the resolved action."""
        actions = snap["actions"]
        state = self._render_state(snap)

        def click_desc(a: dict) -> str:
            lbl = a["label"].lower()
            if any(w in lbl for w in ("search", "submit", "continue", "next", "find", "go")):
                return f'{a["label"]} — submit the form and show results'
            return f'{a["label"]} — a toggle/link (does not submit)'

        # Build the fan-out: one operation Choice + one target Choice per op family.
        # Only offer an operation when it can actually apply (an empty field to fill,
        # a dropdown to set). This is legitimate harness logic — you cannot type into
        # a form with no empty fields — and keeps JuL choosing among real options.
        clickable = {a["id"]: click_desc(a) for a in actions if a["op"] == "CLICK"}
        typeable = {a["id"]: f'{a["label"]}' for a in actions
                    if a["op"] == "TYPE_TEXT" and not a["value"]}      # empty only
        selectable = {a["id"]: f'{a["label"]}' for a in actions
                      if a["op"] == "SELECT" and not a["value"]}       # unset only

        op_criteria = {}
        if clickable:  op_criteria["CLICK"] = "click a button or link, e.g. submit/search, to make progress"
        if typeable:   op_criteria["TYPE_TEXT"] = "type a value into an empty field"
        if selectable: op_criteria["SELECT"] = "choose an option in a dropdown"
        # DONE only when the goal's end state is already on screen (results visible),
        # not merely when the form is filled — a filled form still needs submitting.
        on_results = snap.get("page") == "results"
        op_criteria["DONE"] = ("results are already visible on the page; the goal is achieved"
                               if on_results else
                               "everything is complete AND results are already shown; stop")

        questions = {"operation": Choice(
            instructions="Pick the single best next operation to progress toward the goal.",
            criteria=op_criteria)}
        # Speculative target heads for CLICK/SELECT (semantic choices JuL is good at).
        # TYPE_TEXT ordering is left to the harness: fields are filled in DOM order,
        # skipping ones already filled — a trivial ordering JuL shouldn't have to guess
        # (two empty text fields look near-identical to an embedding model).
        if len(clickable) >= 2:
            questions["click_target"] = Choice(
                instructions="Which element to click to progress toward the goal?", criteria=clickable)
        if len(selectable) >= 2:
            questions["select_target"] = Choice(
                instructions="Which dropdown should be set next?", criteria=selectable)

        t0 = time.perf_counter()
        resp = self.client.system_one(state=state, questions=questions)
        latency_ms = int((time.perf_counter() - t0) * 1000)

        op = resp.choices["operation"].choice
        op_conf = resp.choices["operation"].confidence

        # Resolve the target for the chosen operation.
        def resolve(family: dict, qname: str) -> str | None:
            if not family:
                return None
            if len(family) == 1:
                return next(iter(family))
            return resp.choices[qname].choice

        target_id = None
        if op == "CLICK":
            target_id = resolve(clickable, "click_target")
        elif op == "TYPE_TEXT":
            # First empty typeable field in DOM order (harness-owned ordering).
            empty = [a["id"] for a in actions if a["op"] == "TYPE_TEXT" and not a["value"]]
            target_id = empty[0] if empty else (next(iter(typeable)) if typeable else None)
        elif op == "SELECT":
            target_id = resolve(selectable, "select_target")

        action = next((a for a in actions if a["id"] == target_id), None)
        return {"op": op, "op_conf": op_conf, "action": action, "latency_ms": latency_ms}

    def step(self) -> dict:
        snap = self.observe()
        decision = self.decide(snap)
        op, action = decision["op"], decision["action"]

        record = {
            "step": len(self.history) + 1,
            "op": op,
            "op_conf": round(decision["op_conf"], 3),
            "decide_ms": decision["latency_ms"],
            "label": action["label"] if action else None,
            "text": None,
            "write_ms": 0,
            "page": snap["page"],
        }

        if op == "DONE" or action is None:
            self.done = True
            record["result"] = "done"
            self.history.append(record)
            return record

        # WRITE (only for TYPE_TEXT) via Apple Foundation Model.
        if op == "TYPE_TEXT":
            filled = {a["label"]: a["value"] for a in snap["actions"]
                      if a["op"] in ("TYPE_TEXT", "SELECT") and a["value"]}
            value, write_ms = self.fm.write_field(self.goal, action["label"],
                                                  action["value"], filled=filled)
            record["text"] = value
            record["write_ms"] = write_ms
            self.page.fill(action["sel"], value)
        elif op == "SELECT":
            # Choose the option value from the goal via a small JuL Choice over the options.
            opts = {v: v for v in (action.get("options") or [])}
            chosen = list(opts)[0] if opts else ""
            if len(opts) >= 2:
                r = self.client.system_one(
                    state=f"Goal: {self.goal}\nField: {action['label']}",
                    questions={"opt": Choice(instructions="Pick the option that matches the goal.",
                                             criteria=opts)})
                chosen = r.choices["opt"].choice
            record["text"] = chosen
            self.page.select_option(action["sel"], chosen)
        else:  # CLICK
            self.page.click(action["sel"])

        self.page.wait_for_timeout(120)  # let the page settle
        record["result"] = "ok"
        self.history.append(record)

        # Anti-loop: 3 identical non-progress steps -> stop.
        recent = self.history[-3:]
        if len(recent) == 3 and len({(r["op"], r["label"]) for r in recent}) == 1:
            self.done = True
            record["result"] = "stuck"
        return record

    def run(self):
        for _ in range(MAX_STEPS):
            if self.done:
                break
            yield self.step()

    def _render_state(self, snap: dict) -> str:
        lines = [f"Goal: {self.goal}", f"Page: {snap['page']}", "Current controls:"]
        for a in snap["actions"]:
            v = f' = "{a["value"]}"' if a["value"] else " = (empty)" if a["op"] in ("TYPE_TEXT", "SELECT") else ""
            lines.append(f'  [{a["id"]}] {a["op"]} {a["label"]}{v}')
        if self.history:
            last = self.history[-1]
            lines.append(f'Last action: {last["op"]} {last.get("label")}')
        return "\n".join(lines)
