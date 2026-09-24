// snapshot.js — atomic DOM snapshot into an indexed action table.
// Runs inside the page via page.evaluate(). No AI here: pure DOM reading.
// Returns { url, page, fingerprint, actions:[{id, op, label, value, kind, sel}] }
// where `op` is the operation the element supports (CLICK / TYPE_TEXT / SELECT),
// `sel` is a stable selector the harness uses to execute, and `kind` mirrors op
// for the executor. The fingerprint changes when the actionable surface changes,
// which the harness uses as a freshness guard.
() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 1 && r.height > 1 &&
           s.visibility !== "hidden" && s.display !== "none" &&
           r.bottom > 0 && r.top < (innerHeight + 400);
  };

  const label = (el) => {
    const byId = el.id && document.querySelector(`label[for="${el.id}"]`);
    if (byId && byId.innerText.trim()) return byId.innerText.trim().slice(0, 60);
    const tag = el.tagName.toLowerCase();
    if (tag === "select") return (el.getAttribute("name") || el.id || "dropdown").slice(0, 60);
    return (
      (el.innerText || "").trim() ||
      el.getAttribute("aria-label") ||
      el.getAttribute("placeholder") ||
      el.name || el.id || tag
    ).slice(0, 60);
  };

  // A stable-ish selector: prefer id, else a data attribute, else nth-of-type path.
  const selector = (el) => {
    if (el.id) return `#${CSS.escape(el.id)}`;
    for (const a of ["data-flight", "name"]) {
      const v = el.getAttribute(a);
      if (v) return `${el.tagName.toLowerCase()}[${a}="${CSS.escape(v)}"]`;
    }
    // fallback: index among same-tag siblings in body
    const same = [...document.querySelectorAll(el.tagName.toLowerCase())];
    return `${el.tagName.toLowerCase()}:nth-of-type(${same.indexOf(el) + 1})`;
  };

  const opFor = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === "select") return "SELECT";
    if (tag === "textarea") return "TYPE_TEXT";
    if (tag === "input") {
      const t = (el.type || "text").toLowerCase();
      if (["text", "search", "email", "tel", "url", "number", "password"].includes(t))
        return "TYPE_TEXT";
      return "CLICK"; // checkbox, radio, button, submit...
    }
    return "CLICK"; // a, button, [role=button], [onclick]
  };

  const sel = 'a, button, input, select, textarea, [role=button], [onclick]';
  const els = [...document.querySelectorAll(sel)].filter(visible).slice(0, 40);

  const actions = els.map((el, i) => ({
    id: String(i),
    op: opFor(el),
    label: label(el),
    value: (el.value || "").slice(0, 40),
    kind: opFor(el).toLowerCase(),
    sel: selector(el),
    options: el.tagName.toLowerCase() === "select"
      ? [...el.options].map(o => o.value).filter(Boolean)
      : undefined,
  }));

  // Fingerprint: what can be acted on + the current page marker.
  const fingerprint = JSON.stringify(
    actions.map(a => [a.op, a.label, a.value, a.sel])
  ) + "|" + (document.body.getAttribute("data-page") || "form");

  return {
    url: location.href,
    page: document.body.getAttribute("data-page") || "form",
    title: document.title,
    fingerprint,
    actions,
  };
}
