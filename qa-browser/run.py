"""qa-browser — run a PO's acceptance test in a real browser, with JuL as the only brain.

    python qa-browser/run.py qa-browser/tickets/truffaut-arrosoir.md
    python qa-browser/run.py qa-browser/tickets/truffaut-arrosoir.md --replay   # reuse the last trace

The PO writes the ticket in plain French (see README.md). For each step the harness reads the
page's accessibility tree and JuL decides, in one `system_one` call, the operation (click or
type) and the target element. Optional steps ("Si ...") get a `Noul`: does this element really
do the step here? Each acceptance criterion is a `Noul` on what the final page shows.

JuL never writes: the only text ever typed is the text the PO put in quotes. There is no
second model, no API key, and no token generated, so a run costs $0 and can be replayed at will.
`--replay` goes one step further: it reuses the elements recorded in the last trace and only
calls JuL again for a step whose element has disappeared from the page (the site changed).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from common.jul_helper import Choice, Noul, NoulCriteria, get_client, warmup  # noqa: E402
from ticket import Step, Ticket, parse  # noqa: E402

CLICK_ROLES = {"button", "link", "menuitem", "tab", "checkbox", "radio", "option"}
TYPE_ROLES = {"textbox", "searchbox", "combobox"}
SHORTLIST = 10          # candidates shown to JuL per operation family
STOP = set("le la les un une des du de d l au aux et ou sur dans en à a s si the to of on in "
           "cliquer clique cliquez aller va ouvrir ouvre rechercher recherche chercher saisir "
           "taper vérifier verifier est sont page produit bouton lien "
           "an for if click open go into enter type book button link is".split())

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"


def words(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]+", s) if w not in STOP and len(w) > 1}


# --- observation: the accessibility tree ------------------------------------------------------

class Page:
    def __init__(self, page):
        self.page = page
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.send("DOM.enable")
        self.cdp.send("Accessibility.enable")
        # The site's own XHR/fetch calls in flight (add to cart, search suggestions...). Trackers are
        # ignored: they never go idle. settle() waits for these, so an action is never cut short.
        self.pending: set = set()
        done = lambda r: self.pending.discard(r)  # noqa: E731
        page.on("request", lambda r: self.pending.add(r) if self._own(r) else None)
        page.on("requestfinished", done)
        page.on("requestfailed", done)

    def _own(self, req) -> bool:
        if req.resource_type not in ("xhr", "fetch"):
            return False
        host = lambda u: ".".join(re.sub(r"^https?://([^/:]+).*", r"\1", u).split(".")[-2:])  # noqa: E731
        return host(req.url) == host(self.page.url)

    def elements(self) -> list[dict]:
        """Every named, actionable control exposed to a screen reader, deduplicated."""
        out, seen = [], set()
        for n in self.cdp.send("Accessibility.getFullAXTree")["nodes"]:
            if n.get("ignored") or n.get("backendDOMNodeId") is None:
                continue
            role = (n.get("role") or {}).get("value", "")
            if role in CLICK_ROLES:
                op = "click"
            elif role in TYPE_ROLES:
                op = "type"
            else:
                continue
            name = ((n.get("name") or {}).get("value") or "").strip()
            if not name and op == "type":
                name = self._placeholder(n["backendDOMNodeId"])
            if op == "click" and len(name) <= 3:
                name = self._context_name(n["backendDOMNodeId"]) or name   # icon + badge, e.g. "1"
            name = re.sub(r"\s+", " ", name)[:90]
            if not name or (op, role, name) in seen:
                continue
            seen.add((op, role, name))
            out.append({"op": op, "role": role, "name": name, "node": n["backendDOMNodeId"]})
        return out

    def _placeholder(self, node: int) -> str:
        try:
            attrs = self.cdp.send("DOM.describeNode", {"backendNodeId": node})["node"].get("attributes", [])
        except Exception:
            return ""
        a = dict(zip(attrs[::2], attrs[1::2]))
        return a.get("aria-label") or a.get("placeholder") or a.get("title") or ""

    def _context_name(self, node: int) -> str:
        """A control whose accessible name is only a badge ("1") is named by the text around it
        ("Basket 1"): the closest ancestor, at most two levels up, with a short readable text."""
        try:
            oid = self.cdp.send("DOM.resolveNode", {"backendNodeId": node})["object"]["objectId"]
            r = self.cdp.send("Runtime.callFunctionOn", {"objectId": oid, "returnByValue": True,
                "functionDeclaration": "function(){let e=this;for(let i=0;i<2&&e.parentElement;i++){"
                                       "e=e.parentElement;const t=(e.innerText||'').replace(/\\s+/g,' ').trim();"
                                       "if(t.length>3&&t.length<=40)return t;}return '';}"})
            return r["result"].get("value") or ""
        except Exception:
            return ""

    def visible(self, el: dict) -> bool:
        try:
            box = self.cdp.send("DOM.getBoxModel", {"backendNodeId": el["node"]})["model"]
            return box["width"] > 0 and box["height"] > 0
        except Exception:
            return False

    def _call(self, el: dict, fn: str):
        oid = self.cdp.send("DOM.resolveNode", {"backendNodeId": el["node"]})["object"]["objectId"]
        self.cdp.send("Runtime.callFunctionOn", {"objectId": oid, "functionDeclaration": fn})

    def _stable(self, need: int = 2, interval: int = 350, cap: int = 3000, tol: int = 24):
        """Wait until the visible text stops changing, so a criterion is never read on a
        half-rendered page. Site-agnostic: many pages fetch their data, go network-idle, then
        render it client-side a beat later (a cart line, a result list...). Changes smaller than
        `tol` characters count as stable — a rotating banner or a clock nudges the length by a few
        chars and must not hold the run back, while a real render adds hundreds. Returns as soon as
        the text has held for `need` reads, so a settled page costs one interval."""
        prev, stable, waited = None, 0, 0
        while waited < cap:
            try:
                n = self.page.evaluate("document.body ? document.body.innerText.length : 0")
            except Exception:
                break
            stable = stable + 1 if prev is not None and abs(n - prev) <= tol else 0
            if stable >= need:
                break
            prev = n
            self.page.wait_for_timeout(interval)
            waited += interval

    def settle(self, ms: int = 800):
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        try:
            self.page.wait_for_load_state("networkidle", timeout=1200)
        except Exception:
            pass                                                # trackers can keep a page busy forever
        self.page.wait_for_timeout(ms)
        for _ in range(60):                                     # the site's own calls, up to ~30 s more
            if not self.pending:
                break
            self.page.wait_for_timeout(500)
        self.pending.clear()
        self._stable()                                          # late client-side render (React, etc.)
        try:
            self.cdp.detach()
        except Exception:
            pass
        self.cdp = self.page.context.new_cdp_session(self.page)   # a navigation drops the old one
        self.cdp.send("DOM.enable")
        self.cdp.send("Accessibility.enable")

    def click(self, el: dict):
        """A real mouse click at the element's centre (a trusted event, like a user's), and only once
        the element is really the topmost thing under the pointer: a loading overlay or a spinner
        would otherwise swallow the click, and the test would fail for the wrong reason."""
        self._call(el, "function(){this.scrollIntoView({block:'center'});}")
        for i in range(40):                                     # up to ~20 s, like Playwright's actionability
            q = self.cdp.send("DOM.getContentQuads", {"backendNodeId": el["node"]})["quads"][0]
            x, y = sum(q[0::2]) / 4, sum(q[1::2]) / 4
            oid = self.cdp.send("DOM.resolveNode", {"backendNodeId": el["node"]})["object"]["objectId"]
            on_top = self.cdp.send("Runtime.callFunctionOn", {
                "objectId": oid, "returnByValue": True, "arguments": [{"value": x}, {"value": y}],
                "functionDeclaration": "function(x,y){const t=document.elementFromPoint(x,y);"
                                       "return !!t && (this===t || this.contains(t) || t.contains(this));}"})
            if on_top["result"].get("value"):
                break
            self.page.wait_for_timeout(500)                     # not yet clickable — wait, then re-check
        self.page.mouse.click(x, y)
        self.settle()

    def type(self, el: dict, text: str):
        self._call(el, "function(){this.scrollIntoView({block:'center'}); this.focus(); this.value='';}")
        self.page.keyboard.type(text, delay=30)
        self.page.wait_for_timeout(800)
        self.page.keyboard.press("Enter")
        self.settle()

    def evidence(self, criterion: Step) -> str:
        """What the page shows about a criterion: title, headings, and the lines around its words."""
        p = self.page
        lines = [l.strip() for l in p.inner_text("body").splitlines() if l.strip()]
        keys = set().union(*(words(q) for q in criterion.quoted)) if criterion.quoted else words(criterion.text)
        hits = [i for i, l in enumerate(lines) if keys & words(l)]
        # A wide window around each hit: the criterion word alone ("Flyers") is ambiguous; the lines
        # around it ("Quantity 500 ... Item total 19,99 €") are what let JuL tell a listed cart item
        # from the same word in a menu or a heading.
        keep = sorted({j for i in hits for j in range(max(0, i - 4), min(len(lines), i + 5))})
        excerpt = " | ".join(lines[j] for j in keep)[:1400] or " | ".join(lines[:20])[:800]
        controls = [e["name"] for e in self.elements() if keys & words(e["name"])][:6]
        heads = " | ".join(h.strip() for h in p.locator("h1").all_inner_texts()[:2] if h.strip()) or p.title()
        return (f"Page title: {p.title()}\nMain heading: {heads}\n"
                f"Controls on the page: {' ; '.join(controls) or '(none matching)'}\n"
                f"Page text: {excerpt}")


# --- decisions: JuL only ------------------------------------------------------------------------

def shortlist(step: Step, els: list[dict], page: Page) -> list[dict]:
    want = words(step.text) | set().union(*(words(q) for q in step.quoted)) if step.quoted else words(step.text)
    scored = sorted(els, key=lambda e: -len(want & words(e["name"])))
    picked = [e for e in scored if want & words(e["name"]) and page.visible(e)][:SHORTLIST]
    return picked or [e for e in els if page.visible(e)][:SHORTLIST]


def describe(e: dict) -> str:
    kind = {"link": "link", "button": "button", "combobox": "search / input field",
            "searchbox": "search field", "textbox": "input field"}.get(e["role"], e["role"])
    return f"{kind} « {e['name']} »"


class Brain:
    def __init__(self, client):
        self.client = client
        self.calls, self.ms = 0, []

    def ask(self, state: str, questions: dict):
        t = time.perf_counter()
        r = self.client.system_one(state=state, questions=questions)
        self.calls += 1
        self.ms.append((time.perf_counter() - t) * 1000)
        return r

    def pick(self, step: Step, page: Page, last: dict | None = None) -> tuple[str, dict | None, float]:
        """One system_one call: operation + target. For an optional step the target question also
        offers "none of these", so JuL can say the step does not apply here. The element used by the
        previous step is left out (anti-repeat guard): a new step is a new action."""
        els = [e for e in page.elements()
               if not (last and (e["role"], e["name"]) == (last["role"], last["name"]))]
        fams = {op: shortlist(step, [e for e in els if e["op"] == op], page) for op in ("click", "type")}
        fams = {op: c for op, c in fams.items() if c}
        if "type" in fams and not step.quoted:
            del fams["type"]                                    # nothing to type
        if not fams:
            return "click", None, 0.0
        state = f"QA test step to perform on the web page: {step.text}"
        q = {}
        if len(fams) > 1:
            q["operation"] = Choice(instructions="What does the tester do to perform this step?",
                                    criteria={"click": "click a button or a link",
                                              "type": "type a text into a search box or an input field"})
        for op, cands in fams.items():
            crit = {str(i): describe(e) for i, e in enumerate(cands)}
            if step.optional:
                crit["none"] = "none of these elements: the step does not apply on this page"
            if len(crit) > 1:
                q[op] = Choice(instructions="Which page element must the tester use to perform this step?",
                               criteria=crit)
        r = self.ask(state, q) if q else None
        op = r.choices["operation"].choice if "operation" in q else next(iter(fams))
        if op not in q:                                         # a single candidate, nothing to choose
            return op, fams[op][0], 1.0
        a = r.choices[op]
        return op, (None if a.choice == "none" else fams[op][int(a.choice)]), a.confidence

    def verify(self, criterion: Step, page: Page, tries: int = 4, pause: int = 1400) -> float:
        """Check a criterion, re-reading the page and retrying while it fails, up to a cap — a
        web-first assertion: a criterion is satisfied if it becomes true within the window, so a
        late-rendered element (a cart line loaded after its summary...) is not a false negative.
        A criterion that is really unmet still fails, only later; a met one returns on the first try."""
        p_ok = 0.0
        for i in range(tries):
            p_ok = self.check(criterion, page.evidence(criterion))
            if p_ok >= 0.5 or i == tries - 1:
                break
            page.page.wait_for_timeout(pause)
        return p_ok

    def check(self, criterion: Step, evidence: str) -> float:
        # "The "X" page is displayed": a Choice on the page's title and heading only. Asked as a
        # free Noul over the whole page text, JuL is fooled by a header link that says "X" on any page.
        m = re.search(r"(?i)\b(page|écran|ecran|screen)\b", criterion.text)
        if m and criterion.quoted:
            head = "\n".join(evidence.splitlines()[:2])          # "Page title: ..." + "Main heading: ..."
            r = self.ask(head, {"p": Choice(instructions="What kind of page is the browser showing?",
                                            criteria={"target": f'the "{criterion.quoted[0]}" page itself',
                                                      "other": "another page (a product page, a search page, "
                                                               "the home page...)"})})
            return r.choices["p"].probabilities["target"]
        r = self.ask(f"Acceptance criterion: {criterion.text}\n{evidence}",
                     {"ok": Noul(instructions="Does the page satisfy this acceptance criterion?",
                                 criteria=NoulCriteria(true="satisfied, the page shows it",
                                                       false="not satisfied, the page does not show it"))})
        return r.nouls["ok"].noul


# --- the run ------------------------------------------------------------------------------------

def run(ticket: Ticket, args) -> int:
    from playwright.sync_api import sync_playwright

    trace_path = Path(args.trace)
    trace = json.loads(trace_path.read_text()) if args.replay and trace_path.exists() else None
    recorded = {s["step"]: s for s in trace["steps"]} if trace else {}

    brain = Brain(get_client())
    t_warm = time.perf_counter()
    warmup(brain.client)
    print(f"JuL '{brain.client.model}' ready in {time.perf_counter() - t_warm:.0f} s (excluded from the clock)\n")

    with sync_playwright() as p:
        if args.cdp:
            browser = p.chromium.connect_over_cdp(args.cdp)
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        else:
            browser = p.chromium.launch(headless=not args.headed,
                                        executable_path=args.chrome or os.environ.get("QA_CHROME") or None)
            ctx = browser.new_context(user_agent=UA, locale="en-GB" if ticket.lang == "en" else "fr-FR",
                                      viewport={"width": 1366, "height": 900})
        tab = ctx.new_page()
        tab.goto(ticket.site, wait_until="domcontentloaded", timeout=60000)
        page = Page(tab)
        page.settle(1500)

        print(f"Ticket : {ticket.title}")
        print(f"Site   : {ticket.site}\n")
        t0 = time.perf_counter()
        steps_out, failed = [], False
        for n, step in enumerate(ticket.steps, 1):
            if step.check:                                      # an assertion, checked in place — no click
                p_ok = brain.verify(step, page)
                ok = p_ok >= 0.5
                print(f"{'✓' if ok else '✗'}  {n}. {step.text}   (JuL {p_ok:.2f})")
                steps_out.append({"step": step.text, "assert": True, "ok": ok, "noul": round(p_ok, 3)})
                if not ok and not step.optional:
                    failed = True
                    break
                continue
            rec = recorded.get(step.text)
            el, how, op, conf = None, "jul", "click", 0.0
            if rec and rec.get("skipped"):
                print(f"·  {n}. {step.text}\n     skipped (as recorded)")
                steps_out.append(rec)
                continue
            if rec:
                el = next((e for e in page.elements() if (e["op"], e["role"], e["name"]) ==
                           (rec["op"], rec["role"], rec["name"]) and page.visible(e)), None)
                if el:
                    op, conf, how = rec["op"], 1.0, "replay"
            if el is None:
                op, el, conf = brain.pick(step, page, last=next(
                    (s for s in reversed(steps_out) if not s.get("skipped") and not s.get("assert")), None))
            if el is None:
                if step.optional:
                    print(f"·  {n}. {step.text}\n     skipped: JuL finds nothing to do here ({conf:.2f})")
                    steps_out.append({"step": step.text, "skipped": True})
                    continue
                print(f"✗  {n}. {step.text}\n     no element found")
                failed = True
                break
            text = step.quoted[0] if (op == "type" and step.quoted) else ""
            print(f"→  {n}. {step.text}\n     {op.upper():5s} {describe(el)}"
                  + (f'  ⌨ "{text}"' if text else "") + f"   [{how} {conf:.2f}]")
            try:
                page.type(el, text) if op == "type" else page.click(el)
            except Exception as e:
                print(f"✗  step failed: {e}")
                failed = True
                break
            steps_out.append({"step": step.text, "op": op, "role": el["role"], "name": el["name"],
                              "conf": round(conf, 3), "how": how})

        print(f"\nPage reached: {tab.title()}  ({tab.url})\n\n"
              + ("Acceptance criteria" if ticket.lang == "en" else "Critères de validation"))
        results = []
        for c in ([] if failed else ticket.criteria):
            p_ok = brain.verify(c, page)
            ok = p_ok >= 0.5
            results.append({"criterion": c.text, "noul": round(p_ok, 3), "ok": ok})
            print(f"  {'✓' if ok else '✗'} {c.text}   (JuL {p_ok:.2f})")
        elapsed = time.perf_counter() - t0
        if args.shot:
            tab.screenshot(path=args.shot)
        browser.close()

    passed = not failed and bool(results) and all(r["ok"] for r in results)
    med = statistics.median(brain.ms) if brain.ms else 0
    print(f"\n{'PASS' if passed else 'FAIL'} — {len(steps_out)} steps, {len(results)} criteria, {elapsed:.0f} s")
    print(f"JuL: {brain.calls} decisions, median {med:.0f} ms, 0 tokens generated, $0.00")
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(json.dumps({"ticket": ticket.title, "site": ticket.site, "passed": passed,
                                      "model": brain.client.model, "jul_calls": brain.calls,
                                      "steps": steps_out, "criteria": results}, ensure_ascii=False, indent=2))
    print(f"Trace: {trace_path}")
    return 0 if passed else 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ticket", help="PO ticket in the QA Markdown format")
    ap.add_argument("--replay", action="store_true", help="reuse the elements of the last trace")
    ap.add_argument("--trace", help="trace file (default: runs/<ticket>.json next to this script)")
    ap.add_argument("--cdp", help="drive an already open browser, e.g. http://localhost:9222")
    ap.add_argument("--chrome", help="Chromium executable to launch (default: Playwright's)")
    ap.add_argument("--headed", action="store_true", help="show the browser window")
    ap.add_argument("--shot", help="save a screenshot of the final page")
    args = ap.parse_args()
    args.trace = args.trace or str(Path(__file__).parent / "runs" / (Path(args.ticket).stem + ".json"))
    sys.exit(run(parse(Path(args.ticket).read_text(encoding="utf-8")), args))


if __name__ == "__main__":
    main()
