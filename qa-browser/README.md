# qa-browser — the Product Manager writes the test, JuL runs it

A Product Manager writes an acceptance test in plain words (French or English), inside the ticket.
JuL runs it in a real browser and says whether the ticket passes. **JuL is the only model**: it
picks every element and checks every assertion, and it never writes anything. The only text it
types is the text the Product Manager put in quotes. No API key, no token generated, $0 per run, so you can
rerun it on every deploy. Nothing in the code is tied to a site.

The demo ticket personalizes a flyer on **vistaprint.com** — from the product page, through the
design studio, to a cart with the item in it — and checks two things *during* the journey and
three *at the end*:

```console
$ python qa-browser/run.py qa-browser/tickets/vistaprint-cart-en.md --headed

→  1. If a country banner appears, click "Close"
     CLICK button « Close »   [jul 0.89]
→  2. Click "Browse our templates"
     CLICK button « Browse our templates »   [jul 1.00]
✓  3. Check that the "Flyers Templates" page is displayed   (JuL 1.00)
→  4. Open one of the "Flyers templates"
     CLICK link « Flyers templates in olive and olive for business services »   [jul 0.49]
→  5. Click "Edit my design"
     CLICK link « Edit my design »   [jul 1.00]
→  6. Click "Next"
     CLICK button « Next »   [jul 1.00]
→  7. Click "Continue without Back"
     CLICK button « Continue without Back »   [jul 1.00]
→  8. Check the box "I have reviewed and approve my design"
     CLICK checkbox « I have reviewed and approve my design. »   [jul 1.00]
→  9. Click "Continue"
     CLICK button « Continue »   [jul 1.00]
✓ 10. Check that the "Final Steps" page is displayed   (JuL 0.99)
→ 11. Click "Add to cart"
     CLICK button « Add to cart »   [jul 1.00]
→ 12. Click "Continue"
     CLICK link « Continue »   [jul 1.00]
→ 13. Click "Continue to cart"
     CLICK link « Continue to cart »   [jul 1.00]

Page reached: Cart | VistaPrint  (https://www.vistaprint.com/c/)

Acceptance criteria
  ✓ The "My Cart" page is displayed   (JuL 1.00)
  ✓ The cart contains a "Flyers" item with quantity 500   (JuL 0.58)
  ✓ The "Checkout" button is visible   (JuL 1.00)

PASS — 13 steps, 3 criteria, 78 s
JuL: 11 decisions, median 2206 ms, 0 tokens generated, $0.00
```

Note steps 3 and 10: the flow goes through a design editor, and no `Add to cart` exists until the
personalization is done — so the test **asserts along the way** that it reached the templates
gallery and then the final-steps page, and stops at the first assertion that fails. That is how you
tell *where* a checkout funnel broke, not just that it broke.

▶️ **[Watch the screencast: `qa-browser/demo.mp4`](demo.mp4)** — a real run on vistaprint.com,
recorded with `python qa-browser/record_run.py`. Frames are grabbed around each action, so the time
JuL spends deciding is cut; the real decision time is shown in each caption.

Measured on Apple Silicon (MLX, `wemm-4b-4bit`): ~2.2 s per decision (median), a full 13-step
personalize-and-add-to-cart run in ~80 s — about a third of it JuL thinking, the rest the site
loading — every rerun at $0.

## The Product Manager format

```markdown
# Ticket QA-VP-02 — Personalize a flyer and add it to the cart

Site : https://www.vistaprint.com/marketing-materials/flyers

## Steps

1. If a country banner appears, click "Close".
2. Click "Browse our templates".
3. Check that the "Flyers Templates" page is displayed.
4. Open one of the "Flyers templates".
5. Click "Edit my design".
6. Click "Next".
7. Click "Continue without Back".
8. Check the box "I have reviewed and approve my design".
9. Click "Continue".
10. Check that the "Final Steps" page is displayed.
11. Click "Add to cart".
12. Click "Continue".
13. Click "Continue to cart".

## Acceptance criteria

- The "My Cart" page is displayed.
- The cart contains a "Flyers" item with quantity 500.
- The "Checkout" button is visible.
```

The rules, and that's all:

1. **`Site :`** is the starting URL.
2. **One action per numbered step**, in the Product Manager's own words: *click*, *open*, *go to*… There is no
   fixed vocabulary; JuL maps the sentence to an element on the page.
3. **Anything in "quotes" is copied verbatim from the site**: a button label, a product name, or
   the text to type. It is the one thing the Product Manager must get exactly right.
4. **A step starting with *If* / *Si* is optional.** When it does not apply (no banner this time),
   it is skipped instead of failing.
5. **A step starting with *Check that* / *Verify that* / *Vérifier que* is an assertion**, checked
   in place on the current page — no click. The run stops at the first one that fails, so it points
   at the exact step where the journey went wrong. (*Check the box "…"* — no *that* — is still an
   action: JuL ticks the box.)

The same format works in French: `## Étapes` and `## Critères de validation`.

Each bullet under **Acceptance criteria** is a yes/no question about the final page. The ticket
passes when every step, every assertion and every criterion passes. Make assertions **specific** —
`a "Flyers" item with quantity 500` is judged far more reliably than a bare `Flyers`, because the
extra detail is corroborated by what is actually on the page.

## What JuL decides

```
OBSERVE  CDP Accessibility.getFullAXTree   → every named control: role + accessible name
DECIDE   Choice  operation (click / type) + target element, one system_one call per step
                 (an optional step also gets "none of these": JuL can say it does not apply)
ACT      a real mouse click on the node, or type the quoted text + Enter; then wait until the
         site's own requests are done and the page has stopped rendering
ASSERT   a "Check that ..." step, and every acceptance criterion, is a Choice/Noul on the current
         page — its title, heading, matching controls and the text around the words that matter;
         re-read until true within a short window, so late-rendered content is not a false negative
```

The harness only does mechanical work: it reads the accessibility tree and keeps the ~10 controls
whose names share words with the step. The choice among them is JuL's. There is no site-specific
code: no CSS selector, no URL rule, no label list.

## Replay for $0

Every run writes a trace (`qa-browser/runs/<ticket>.json`): for each step, the element JuL chose,
and for each assertion, JuL's probability.

```console
$ python qa-browser/run.py qa-browser/tickets/vistaprint-cart-en.md --replay
```

`--replay` reuses the recorded element whenever it is still on the page. JuL is called again only
for a step whose element has disappeared (the site changed) and for the assertions, which are
always re-checked. Rerunning a test costs nothing.

## Run it

```bash
pip install "jul[mlx]" playwright     # or jul[torch] off Apple Silicon
playwright install chromium
python qa-browser/run.py qa-browser/tickets/vistaprint-cart-en.md --headed
```

On a bot-protected site, drive your own browser instead (it keeps your cookies and passes the
challenge you solved by hand):

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.qa-agent"
python qa-browser/run.py my-ticket.md --cdp http://localhost:9222
```

The demo flow stops at the cart: nothing is ever ordered.
