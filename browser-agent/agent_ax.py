"""agent_ax — the same on-device brain, but the ACTION SPACE comes from the
accessibility tree, not DOM heuristics.

Why: on real sites the DOM is noisy and ambiguous — two "Gare, ville, lieu..."
inputs look identical, submit buttons hide behind footer links, decorative nodes
crowd the list. The accessibility (AX) tree — the same tree a screen reader uses —
gives each control its true role (button / combobox / textbox / link) and its
computed accessible name ("Départ :" vs "Arrivée :"), already filtered to what is
actually exposed to a user. This is exactly what jev-ultrafast's desktop port does
("the table comes from the accessibility tree instead of the DOM").

We read the AX tree over CDP (Accessibility.getFullAXTree) and act on the real
node via its backendDOMNodeId. JuL still decides (operation + target fan-out);
the Apple Foundation Model still writes text. No site-specific scripting.
"""

from __future__ import annotations

import os
import re
import sys
import time
import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from common.jul_helper import get_client, Choice, Noul, NoulCriteria  # noqa: E402
from fm_writer import FMWriter  # noqa: E402

MAX_STEPS = 10
DEFAULT_MODEL = "wemm-4b-4bit"

_FR_MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
              "août", "septembre", "octobre", "novembre", "décembre"]
_FR_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def target_date_from_goal(goal: str) -> datetime.date | None:
    """Resolve a travel date mentioned in the goal.

    Supports relative dates ("in 3 days", "dans 3 jours", "tomorrow", "demain")
    and a few absolute forms. Returns None if no date is expressed.
    """
    g = goal.lower()
    today = datetime.date.today()
    m = re.search(r"(?:in|dans)\s+(\d+)\s+(?:days?|jours?)", g)
    if m:
        return today + datetime.timedelta(days=int(m.group(1)))
    if "tomorrow" in g or "demain" in g:
        return today + datetime.timedelta(days=1)
    if "today" in g or "aujourd" in g:
        return today
    return None


def fr_day_label(d: datetime.date) -> str:
    """The accessible-name form SNCF uses, e.g. 'dimanche 27 septembre 2026'."""
    return f"{_FR_DAYS[d.weekday()]} {d.day:02d} {_FR_MONTHS[d.month - 1]} {d.year}"

# Accessible-name substrings that are chrome/navigation/footer, not task controls.
AX_NOISE = (
    "aller au contenu", "skip to", "debug", "lancer la conversation", "compte",
    "panier", "aide", "vos billets", "services", "cartes et abonnements",
    "meilleurs prix", "paiement", "contact", "service client", "conditions",
    "informations légales", "confidentialité", "cookies", "régie", "partenaire",
    "widget", "presse", "carrières", "groupe", "emploi", "instagram", "tiktok",
    "facebook", "twitter", "pinterest", "youtube", "linkedin", "nouvel onglet",
    "choisir que", "choisir comment", "choisir quand", "intervertir",
    "transporteurs", "itinéraires populaires", "top destinations", "trajets via",
    "plan du site", "allianz", "railteam", "google pay", "sign in", "connexion",
    "réserver pour", "guide du voyageur", "franchissement", "accessibilité",
    "fonctionnalités d", "suppression de la valeur", "langue", "retour à l'accueil",
    "voyage personnel", "voyage professionnel", "voyager", "droits des voyageurs",
    "ajouter le retour", "choisir trajets", "choisir temps",
    "ajouter un voyageur", "fermer la bo", "ajouter un", "réduction", "fidélité",
    "voyageur", "animal", "vélo", "code avantage", "trajets via", "correspondance",
)

# Roles we treat as actionable, mapped to an operation.
CLICK_ROLES = {"button", "link", "menuitem", "tab", "checkbox", "radio"}
TYPE_ROLES = {"textbox", "combobox", "searchbox"}


class AXAgent:
    def __init__(self, page, goal: str, model: str = DEFAULT_MODEL):
        self.page = page
        self.goal = goal
        self.client = get_client(model)
        self.fm = FMWriter()
        self.history: list[dict] = []
        self.done = False
        self._touched: set[str] = set()
        self.target_date = target_date_from_goal(goal)   # None if the goal has no date
        self._date_set = self.target_date is None         # nothing to do if no date
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.send("DOM.enable")
        self.cdp.send("Accessibility.enable")

    # --- observation via the accessibility tree -----------------------------
    def observe(self) -> dict:
        tree = self.cdp.send("Accessibility.getFullAXTree")
        actions, self._backend = [], {}
        for node in tree["nodes"]:
            if node.get("ignored"):
                continue
            role = (node.get("role") or {}).get("value", "")
            name = ((node.get("name") or {}).get("value", "") or "").strip()
            value = ((node.get("value") or {}).get("value", "") or "").strip()
            backend = node.get("backendDOMNodeId")
            if backend is None:
                continue
            if role in CLICK_ROLES:
                op = "CLICK"
            elif role in TYPE_ROLES:
                op = "TYPE_TEXT"
            else:
                continue
            # A click control needs a name; a field can be empty but should be named.
            if op == "CLICK" and not name:
                continue
            if any(n in name.lower() for n in AX_NOISE):
                continue
            idx = str(len(actions))
            actions.append({"id": idx, "op": op, "label": name[:60], "value": value[:40], "role": role})
            self._backend[idx] = backend

        url = self.page.url
        is_results = ("results" in url) or ("/flights/search" in url)
        return {"url": url, "page": "results" if is_results else "form", "actions": actions}

    # --- decision (JuL fan-out) ---------------------------------------------
    def decide(self, snap: dict) -> dict:
        actions = snap["actions"]
        # Flag prefilled fields whose value mismatches the goal (JuL Noul).
        self._needs_refill = set()
        for a in actions:
            if a["op"] == "TYPE_TEXT" and a["value"] and a["label"] not in self._touched:
                r = self.client.system_one(
                    state=f'Goal: {self.goal}\nField "{a["label"]}" contains: "{a["value"]}"',
                    questions={"ok": Noul(
                        instructions=f'Does "{a["label"]}" already match what the goal requires?',
                        criteria=NoulCriteria(true="yes, correct", false="no, wrong value"))})
                if r.nouls["ok"].noul < 0.5:
                    self._needs_refill.add(a["id"])

        clickable_all = [a for a in actions if a["op"] == "CLICK"]
        # Positive relevance instead of blocklisting: a click is a candidate if its name
        # contains an action/submit verb. This surfaces the real submit ("Voir les prix",
        # "Rechercher", "Search"...) and drops decorative/footer/menu noise generically.
        SUBMIT = ("voir les prix", "rechercher", "search", "valider", "voir les",
                  "continuer", "suivant", "find", "lancer la recherche", "afficher")
        NAV = ("suivant", "next", "continuer", "accepter", "tout accepter")
        def is_candidate(a):
            lbl = a["label"].lower()
            return any(s in lbl for s in SUBMIT) or any(s in lbl for s in NAV)
        cand = [a for a in clickable_all if is_candidate(a)]
        # If nothing matched (e.g. an early page with no submit yet), fall back to all
        # clicks minus obvious noise so the agent can still navigate.
        if not cand:
            cand = [a for a in clickable_all if not any(n in a["label"].lower() for n in AX_NOISE)]
        clickable = {a["id"]: self._click_desc(a) for a in cand}
        typeable = {a["id"]: a["label"] for a in actions
                    if a["op"] == "TYPE_TEXT" and (not a["value"] or a["id"] in self._needs_refill)}

        op_criteria = {}
        if clickable:  op_criteria["CLICK"] = "click a button/link, e.g. search or submit, to progress"
        if typeable:   op_criteria["TYPE_TEXT"] = "type a city/value into an empty field"
        if snap["page"] == "results":
            op_criteria["DONE"] = "journey/flight results are visible; stop"

        state = self._render_state(snap)
        questions = {"operation": Choice(
            instructions="Pick the single best next operation to progress toward the goal.",
            criteria=op_criteria)}
        if len(clickable) >= 2:
            questions["click_target"] = Choice(
                instructions="Which element to click to progress toward the goal?", criteria=clickable)

        if len(op_criteria) < 2:
            op = next(iter(op_criteria)) if op_criteria else "DONE"
            op_conf, resp, latency_ms = 1.0, None, 0
        else:
            t0 = time.perf_counter()
            resp = self.client.system_one(state=state, questions=questions)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            op = resp.choices["operation"].choice
            op_conf = resp.choices["operation"].confidence

        target_id = None
        if op == "CLICK":
            target_id = (next(iter(clickable)) if (len(clickable) == 1 or resp is None)
                         else resp.choices["click_target"].choice) if clickable else None
        elif op == "TYPE_TEXT":
            fillable = [a["id"] for a in actions if a["op"] == "TYPE_TEXT"
                        and (not a["value"] or a["id"] in self._needs_refill)]
            target_id = fillable[0] if fillable else None

        action = next((a for a in actions if a["id"] == target_id), None)
        return {"op": op, "op_conf": op_conf, "action": action, "latency_ms": latency_ms}

    # --- one step -----------------------------------------------------------
    def step(self) -> dict:
        snap = self.observe()

        # Date selection is a mechanical step the harness owns (like picking an
        # autocomplete suggestion): once both endpoints are set and the goal names
        # a date, open the date picker and choose the matching day by its accessible
        # name. JuL still decides operations; this is label-matching, not a script.
        if not self._date_set and self._both_fields_filled(snap):
            rec = self._select_date()
            if rec is not None:
                self.history.append(rec)
                return rec

        d = self.decide(snap)
        op, action = d["op"], d["action"]
        rec = {"step": len(self.history) + 1, "op": op, "op_conf": round(d["op_conf"], 3),
               "decide_ms": d["latency_ms"], "label": action["label"] if action else None,
               "text": None, "write_ms": 0, "page": snap["page"]}

        if op == "DONE" or action is None:
            self.done = True
            rec["result"] = "done"
            self.history.append(rec)
            return rec

        if op == "TYPE_TEXT":
            lbl = action["label"].lower()
            named = any(w in lbl for w in ("départ", "arrivée", "from", "to", "origin", "destination"))
            # For clearly-named origin/destination fields, the field name + goal are
            # enough (and more reliable): the site's prefilled values can be wrong and
            # would mislead. Only pass sibling context for ambiguous/unnamed fields.
            filled = {} if named else {a["label"]: a["value"] for a in snap["actions"]
                                       if a["op"] == "TYPE_TEXT" and a["value"]}
            value, write_ms = self.fm.write_field(self.goal, action["label"], action["value"], filled=filled)
            rec["text"], rec["write_ms"] = value, write_ms
            ok = self._type_into(action, value)
            self._touched.add(action["label"])
        else:
            ok = self._click(action)

        if not ok:
            rec["result"] = "retry"
            self.history.append(rec)
            return rec

        self.page.wait_for_timeout(500)
        rec["result"] = "ok"
        self.history.append(rec)

        if "results" in self.page.url or "/flights/search" in self.page.url:
            self.done = True
            rec["result"] = "done"
            return rec

        recent = self.history[-3:]
        if len(recent) == 3 and len({(r["op"], r["label"]) for r in recent}) == 1:
            self.done = True
            rec["result"] = "stuck"
        return rec

    # --- date selection (harness-owned, label-matched) ----------------------
    def _both_fields_filled(self, snap: dict) -> bool:
        fields = [a for a in snap["actions"] if a["op"] == "TYPE_TEXT"
                  and ("départ" in a["label"].lower() or "arrivée" in a["label"].lower())]
        return len(fields) >= 2 and all(a["value"] for a in fields)

    def _select_date(self) -> dict | None:
        """Open the date control, click the day matching the goal date, confirm.
        Returns a step record, or None if the date UI wasn't found (skip gracefully)."""
        want_label = fr_day_label(self.target_date)
        rec = {"step": len(self.history) + 1, "op": "SET_DATE", "op_conf": 1.0,
               "decide_ms": 0, "label": want_label, "text": None, "write_ms": 0, "page": "form"}
        # 1) open the date button ("Aller : Aujourd'hui, ...")
        opener = self.page.get_by_role("button", name="Aller", exact=False)
        if not opener.count():
            opener = self.page.get_by_role("button", name="Aujourd", exact=False)
        if not opener.count():
            self._date_set = True     # no date UI on this site; don't block
            return None
        try:
            opener.first.click(timeout=4000)
            # Wait for the calendar to actually render before matching a day.
            day = self.page.get_by_role("button", name=want_label, exact=False)
            for _ in range(12):
                self.page.wait_for_timeout(250)
                if day.count():
                    break
            # 2) click the day whose accessible name matches the target date
            if day.count():
                day.first.click(timeout=4000)
                self.page.wait_for_timeout(500)
            # 3) confirm if a confirm button exists
            for nm in ("Confirmer", "Valider", "OK", "Terminer"):
                c = self.page.get_by_role("button", name=nm)
                if c.count():
                    c.first.click(timeout=3000)
                    break
            self.page.wait_for_timeout(900)
            self._date_set = True
            rec["result"] = "ok" if day.count() else "retry"
        except Exception:
            self._date_set = True     # don't loop on a flaky calendar
            rec["result"] = "retry"
        return rec

    # --- executor: act on the real node via backendDOMNodeId ----------------
    def _focus(self, action: dict):
        self.cdp.send("DOM.focus", {"backendNodeId": self._backend[action["id"]]})

    def _type_into(self, action: dict, value: str) -> bool:
        try:
            self._focus(action)
        except Exception:
            return False
        # clear then type
        for _ in range(45):
            self.page.keyboard.press("Backspace")
        self.page.keyboard.type(value, delay=35)
        self.page.wait_for_timeout(600)
        # pick the autocomplete suggestion whose first line == the value (deterministic)
        try:
            opts = self.page.get_by_role("option")
            n = opts.count()
            if n:
                want = value.strip().lower()
                pick = 0
                for i in range(min(n, 10)):
                    first = opts.nth(i).inner_text().split("\n")[0].strip().lower()
                    if first == want:
                        pick = i
                        break
                opts.nth(pick).click(timeout=3000)
        except Exception:
            pass
        return True

    def _click(self, action: dict) -> bool:
        try:
            # AX click via CDP is unreliable across frames; resolve to a handle and click.
            r = self.cdp.send("DOM.resolveNode", {"backendNodeId": self._backend[action["id"]]})
            oid = r["object"]["objectId"]
            self.cdp.send("Runtime.callFunctionOn",
                          {"objectId": oid, "functionDeclaration": "function(){this.click();}"})
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
        if "voir les prix" in lbl or "prix" in lbl:
            return f'{a["label"]} — run the search and show journey results with prices'
        if "horaires" in lbl:
            return f'{a["label"]} — timetables only, does not show prices'
        if any(s in lbl for s in ("rechercher", "search", "valider", "lancer la recherche", "afficher")):
            return f'{a["label"]} — submit the form and show results'
        if any(s in lbl for s in ("accepter", "continuer", "suivant", "next")):
            return f'{a["label"]} — proceed to the next step'
        return f'{a["label"]} — a control on the page'

    def _render_state(self, snap: dict) -> str:
        lines = [f"Goal: {self.goal}", f"Page: {snap['page']}", "Current controls:"]
        for a in snap["actions"]:
            v = f' = "{a["value"]}"' if a["value"] else (" = (empty)" if a["op"] == "TYPE_TEXT" else "")
            lines.append(f'  [{a["id"]}] {a["op"]} {a["label"]}{v}')
        if self.history:
            lines.append(f'Last action: {self.history[-1]["op"]} {self.history[-1].get("label")}')
        return "\n".join(lines)
