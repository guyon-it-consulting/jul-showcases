# qa-browser — the Product Manager writes the test, JuL runs it

Your Product Manager writes a test the way they'd describe it to a teammate — plain sentences, in a
ticket. JuL reads it, runs it in a real browser, and tells you whether it passed. That's the whole
idea.

Here's a real one — personalize a flyer on vistaprint.com and get it into the cart:

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

No selectors, no code — just what a person would click and what they'd expect to see. Here's JuL
running it:

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

**JuL is the only brain here.** It picks every element and judges every check — and it never writes
anything: the only text it ever types is what the Product Manager put in quotes. No API key, nothing
generated, $0 a run. So you can run it on every deploy, and nothing in the code is tied to one site.

Notice steps 3 and 10. Vistaprint makes you design the flyer before an "Add to cart" button even
exists, so the test checks *as it goes* — did we reach the template gallery? the final-steps page? —
and stops at the first check that fails. When a checkout funnel breaks, that tells you *where* it
broke, not just *that* it broke.

▶️ **[Watch the screencast (`demo.mp4`)](demo.mp4)** — this exact run on vistaprint.com, recorded
with `python qa-browser/record_run.py`. On an Apple Silicon Mac (MLX, `wemm-4b-4bit`) the whole
personalize-and-add-to-cart run takes about 80 seconds — roughly a third JuL thinking, the rest the
site loading — and every rerun is free.

## Writing a ticket

A few rules, and that's really all:

- **`Site :`** is where JuL starts.
- **One action per numbered line, in your own words** — *click*, *open*, *go to*. There's no fixed
  vocabulary; JuL works out which element on the page you mean.
- **Anything in "quotes" is copied straight from the site** — a button label, a product name, the
  text to type. It's the one thing to get exactly right, and it's exactly what a user sees on screen.
- **Start a line with *If* (or *Si*) and it's optional.** No banner today? JuL skips it instead of
  failing.
- **Start with *Check that* / *Verify that* / *Vérifier que* and it's an assertion** — JuL just
  looks, no click, and the run halts at the first one that fails. (*Check the box "…"*, with no
  *that*, still ticks the box.)

It works in French too — `## Étapes` and `## Critères de validation`. Each bullet under **Acceptance
criteria** is a yes/no question about the final page, and the ticket passes only when every step,
every assertion and every criterion does.

One tip: **make your checks specific.** `a "Flyers" item with quantity 500` is judged far more
reliably than a bare `Flyers`, because the extra detail gives JuL something concrete on the page to
agree with.

## Under the hood

For each step, the harness reads the page's accessibility tree, keeps the ~10 controls whose names
share words with your sentence, and hands them to JuL. JuL makes the call:

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

That's the whole split: the harness does the mechanical work, JuL makes every choice. No CSS
selector, no URL rule, no hand-written list of labels — nothing tied to a particular site.

## Replay for $0

Every run writes a trace (`qa-browser/runs/<ticket>.json`) with the element JuL chose for each step
and its probability for each check. Replaying reuses those elements:

```console
$ python qa-browser/run.py qa-browser/tickets/vistaprint-cart-en.md --replay
```

JuL is only called again for a step whose element has vanished (the site changed) and for the
assertions, which are always re-checked. Rerunning a green test costs nothing.

## Run it

```bash
pip install "jul[mlx]" playwright     # or jul[torch] off Apple Silicon
playwright install chromium
python qa-browser/run.py qa-browser/tickets/vistaprint-cart-en.md --headed
```

On a bot-protected site, point JuL at your own browser instead — it keeps your cookies and the
challenge you already solved by hand:

```bash
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/.qa-agent"
python qa-browser/run.py my-ticket.md --cdp http://localhost:9222
```

The demo flow stops at the cart — nothing is ever ordered.
