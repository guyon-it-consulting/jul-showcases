# qa-browser — the PO writes the test, JuL runs it

A Product Owner writes an acceptance test in plain French, inside the ticket. JuL runs it in a
real browser and says whether the ticket passes. **JuL is the only model**: it picks every element
and checks every criterion, and it never writes anything. The only text it types is the text the
PO put in quotes. No API key, no token generated, $0 per run, so you can rerun it on every
deploy.

```console
$ python qa-browser/run.py qa-browser/tickets/truffaut-arrosoir.md

→  1. Si une bannière cookies s'affiche, cliquer "Accepter et fermer"
     CLICK button « Accepter et fermer »   [jul 1.00]
→  2. Rechercher "arrosoir luxe"
     TYPE  search / input field « Je cherche une plante, un conseil... »  ⌨ "arrosoir luxe"   [jul 1.00]
→  3. Ouvrir le produit "Arrosoir luxe : 15L"
     CLICK link « Arrosoir luxe : 15L … 19,99€ »   [jul 1.00]
→  4. Cliquer "Ajouter au panier"
     CLICK button « Ajouter au panier »   [jul 0.99]
→  5. Ouvrir "Mon panier"
     CLICK link « Mon panier »   [jul 1.00]
→  6. Cliquer "Voir votre panier"
     CLICK link « Voir votre panier »   [jul 1.00]

Critères de validation
  ✓ La page "Mon panier" est affichée   (JuL 0.96)
  ✓ Le panier contient "Arrosoir luxe : 15L"   (JuL 0.94)
  ✓ Le bouton "Valider ma commande" est visible   (JuL 0.99)

PASS — 6 steps, 3 criteria
JuL: 9 decisions, 0 tokens generated, $0.00
```

▶️ **[Watch the screencast: `qa-browser/demo_truffaut.mp4`](demo_truffaut.mp4)**: a real run on
truffaut.com, recorded with `record_run.py`. Frames are grabbed around each action, so the time
JuL spends deciding is cut; the real decision time is shown in each caption.

Measured on a CPU-only Linux box (8 cores, PyTorch, `wemm-4b-4bit`): ~20 s per decision, 5.5 min
for the first run, 1.5 min for `--replay` (3 decisions instead of 9). Expect far less on Apple
Silicon with MLX; not measured yet.

## The PO format

```markdown
# Ticket QA-101 — Ajouter un arrosoir au panier depuis la recherche

Site : https://www.truffaut.com/

## Étapes

1. Si une bannière cookies s'affiche, cliquer "Accepter et fermer".
2. Rechercher "arrosoir luxe".
3. Ouvrir le produit "Arrosoir luxe : 15L".
4. Cliquer "Ajouter au panier".
5. Ouvrir "Mon panier".
6. Cliquer "Voir votre panier".

## Critères de validation

- La page "Mon panier" est affichée.
- Le panier contient "Arrosoir luxe : 15L".
- Le bouton "Valider ma commande" est visible.
```

Four rules, and that's all:

1. **`Site :`** is the starting URL.
2. **One action per numbered step**, in the PO's own words: *cliquer*, *rechercher*, *ouvrir*,
   *aller à*… There is no fixed vocabulary; JuL maps the sentence to an element on the page.
3. **Anything in "quotes" is copied verbatim from the site**: a button label, a product name, or
   the text to type. It is the one thing the PO must get exactly right, and it is exactly what
   they see on the screen.
4. **A step starting with *Si* is optional.** When it does not apply (no cookie banner this
   time), it is skipped instead of failing.

Each bullet under **Critères de validation** is a yes/no question about the final page. The ticket
passes when every criterion passes.

## What JuL decides

```
OBSERVE  CDP Accessibility.getFullAXTree   → every named control: role + accessible name
DECIDE   Choice  operation (click / type) + target element, one system_one call per step
         Noul    optional step: is this element really the one the step talks about?
ACT      click the node, or type the quoted text + Enter
VERIFY   Noul    per criterion, on the title, main heading, matching controls and page text
```

The harness only does mechanical work: it reads the accessibility tree and keeps the ~10 controls
whose names share words with the step. The choice among them is JuL's.

## Replay for $0

Every run writes a trace (`qa-browser/runs/<ticket>.json`): for each step, the element JuL chose
(role + accessible name), and for each criterion, JuL's probability.

```console
$ python qa-browser/run.py qa-browser/tickets/truffaut-arrosoir.md --replay
```

`--replay` reuses the recorded element whenever it is still on the page. JuL is called again only
for a step whose element has disappeared (the site changed) and for the criteria, which are always
checked again. Rerunning a test costs nothing, not even the decisions that are already known.

## Run it

```bash
pip install "jul[torch]" playwright     # or jul[mlx] on Apple Silicon
playwright install chromium
python qa-browser/run.py qa-browser/tickets/truffaut-arrosoir.md --headed
```

On a bot-protected site, drive your own browser instead (it keeps your cookies and passes the
challenge you solved by hand):

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.qa-agent"
python qa-browser/run.py my-ticket.md --cdp http://localhost:9222
```

The demo site is **truffaut.com**, a real French garden store. The flow stops at the cart:
nothing is ever ordered.
