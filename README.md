# Leash

Scoped, revocable, auditable spending authority for AI agents, settled over PayPal Payouts.

Hand an agent a wallet with rules. Every attempt to spend is evaluated before any
money moves, an allow places a hold rather than a payment, and a human approves
the batch that actually settles.

The interesting part is not what the agent buys. It is what it cannot.

## Why

If you want an AI to spend on your behalf you currently have two options, both
bad: give it your card and hope, or approve every click and get no value from
having an agent at all. What is missing is the primitive in between, a spending
authority that is scoped, revocable and auditable, and that holds even when the
agent actively works around it.

## The checks

Eleven, run in the order a person would ask the questions. Every one runs even
after another has failed, because a decision that names all three reasons is
worth more than one that names the first.

| Check | What it stops |
| --- | --- |
| `mandate_inactive` | Spending on a revoked authority |
| `currency_mismatch` | Comparing amounts that have no common meaning |
| `outside_window` | Spending before it opens or after it closes |
| `payee_not_allowed` | Paying someone off the list |
| `category_not_allowed` | Scope drift, buying outside the remit |
| `per_item_limit` | A single charge over the cap |
| `structuring` | A cap evaded by splitting rather than broken |
| `per_payee_limit` | Too much to one counterparty |
| `insufficient_budget` | Spending past the total, holds included |
| `velocity` | Too many charges, or too much, too fast |
| `concentration` | The whole book quietly ending up with one payee |

### Structuring is the one that matters

An agent told "nothing over $100" and asked for a $120 item will discover,
entirely on its own, that two charges of $60 both pass. Each is legitimate
under the per-item check. Only the cluster is not.

So the cap is enforced against recent charges to the same counterparty, not
against the charge in isolation, and counterparty means the merchant rather
than the receiver address. One merchant with a US and an EU address is still
one merchant.

Structuring also outranks the cap it evades in the severity ordering. A charge
over the limit is a mistake. Two charges engineered to sit under it is intent,
and the reason a human reads should say so.

## Design notes

- **Amounts are integer minor units** with the currency attached. No float ever
  touches money, and adding INR to USD raises rather than producing a number
  that looks fine.
- **`evaluate` is pure.** Same mandate, same attempt, same history, same verdict,
  with no processor and no model in the loop. That is what makes it testable
  against an adversary rather than demoable against a script.
- **Authorization and capture are separate.** An allow places a hold that counts
  against every later check until it settles or releases, so two attempts
  evaluated a millisecond apart cannot both see the full balance.
- **The full trace is the output**, not just the verdict. Passed checks carry
  their numbers too, which is what makes the audit view worth looking at.
- **`max_allowable`** turns "blocked" into "blocked, but $40 would have cleared".
  The difference between a wall and a boundary.
- **Revocation** drops pending holds and leaves settled money alone. It stops
  what has not happened; it does not claw back what has.
- **Settling is provisional, and reconciliation is how it stops being.** A
  processor accepts a batch and answers `PENDING` long before it knows whether
  each item will land, and we settle on that, because the instruction really
  has gone. But an item can become `RETURNED` an hour later and nothing comes
  back to say so. `POST /payouts/{id}/reconcile` re-reads the batch and moves
  the ledger to match. Without it the grid would keep claiming a payment
  succeeded while the money sat back in the sender's account, which is exactly
  the failure this project argues against: recording what we intended rather
  than what happened.

  The two directions are not symmetric. If the processor says the money came
  back and we think it settled, that is fixed automatically and the budget
  returns. If the processor says the money went and we think it did not, that
  is **reported and not fixed**, because re-committing budget that may since
  have been spent elsewhere could push the mandate past its own limit. A
  person has to look at that one.

## Running it

```bash
pip install -e ".[dev]"
pytest
python scripts/walkthrough.py
uvicorn leash.api:app --reload
```

`scripts/walkthrough.py` drives the whole scenario in process and narrates it.
No server and no credentials needed.

### The screen

```bash
uvicorn leash.api:app --reload     # terminal one
npm --prefix web install           # terminal two
npm --prefix web run dev
```

Then open <http://localhost:5173>. Vite proxies `/api` to port 8000, so the
browser only ever talks to one origin.

**Run scenario** resets the demo and plays eleven spends: six clear, five are
refused, and the fifth attempt is a 150 purchase split into two 75 charges
across Acme's two receiver addresses. That row opens itself, because it is the
one worth looking at.

Notes on the grid, since it is doing real work:

- The **evidence band** under a refusal is an AG Grid full-width row, not a
  tooltip. For a structuring catch it draws the cluster: each charge that was
  fine on its own, and the cap line that only the total crosses.
- The band **measures itself** and tells the grid its height, so it reflows
  correctly at any window width instead of being clipped to an estimate.
- Only live holds are selectable, so the grid itself says what is actionable.
- Settling **flashes the cell** that changed, so the moment money moves is
  visible rather than inferred.
- This is **AG Grid Community**, with no licence key. An Enterprise trial taken
  out during a build expires before anyone judges it, and a demo that degrades
  on a date is not a demo.

The console at the bottom has two modes.

**Ask for one thing** sends a single spend by hand. It stays usable after
revocation on purpose: asking a dead mandate for money and watching it refuse
is the proof, and a greyed-out button is not.

**Send it shopping** is the catalogue. Type what the agent should buy, and
either look at the shelf first or send it. The panel then draws what it did,
and the middle line is the whole argument:

```
REFUSED   Mesh task chair, adjustable arms    acme.com   150.00
          100.00 would have cleared, so it looked again under that
BOUGHT    Mesh task chair, fixed arms         acme.com    88.00
```

The agent never sees the mandate. It only ever learns what a refusal tells
it, which is the position a real agent is in.

### PayPal

With no credentials set the app runs on a simulated gateway that is
deterministic and offline, which is what makes everything above developable and
testable without a sandbox. Set these to use the real Payouts API:

```bash
LEASH_PAYPAL_CLIENT_ID=...
LEASH_PAYPAL_SECRET=...
LEASH_PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
LEASH_DEMO_RECEIVER_EMAIL=your-sandbox-personal@example.com
```

`LEASH_DEMO_RECEIVER_EMAIL` points every seeded payee at one address, so a
single variable makes the demo pay into a real sandbox personal account.

### Deploying it

Two free Render services, defined in [`render.yaml`](render.yaml), with the
steps in [`DEPLOY.md`](DEPLOY.md). The screen is a static site so it never
sleeps, and the API is a web service that does, which the screen knows how to
wait for. The API has to be a long-lived process rather than a serverless
function, because the whole ledger lives in memory.

### Channel3

```bash
LEASH_CHANNEL3_API_KEY=...
```

Without it the agent shops a fixed catalogue that needs no network, and every
test passes either way. With it the agent shops real products at real prices
from real merchants, which earns its place for two reasons rather than one:

- **Merchants are counterparties.** A product usually carries offers from
  several domains, so the agent genuinely chooses who to pay. And merchants
  really do sell under more than one hostname, so grouping `store.nike.com`
  with `nike.com` stops being a scenario built to be caught and starts being
  the thing the per-counterparty cap and the structuring window are actually
  for.
- **A refusal becomes the next search.** Told that 150 is over the cap but
  100 would clear, the agent does not haggle over the same product. It goes
  back to the shop with 100 as a price ceiling and buys something that fits.
  `max_allowable` stops being a number in a log.

The mandate is scoped in **Channel3's own taxonomy** rather than in slugs I
invented. Channel3 classifies against the Google Product Taxonomy, so an
office chair is `furniture`, a ream of paper is `office-supplies`, a monitor
is `electronics` and a desk lamp is `home-garden`. Scoping the demo mandate
to `{furniture, office-supplies}` is therefore a procurement rule someone
would actually write, not a demo contrivance, and it behaves the same whether
a key is set or not: the offline catalogue uses the same roots. There is a
test that fails if those two ever drift apart, because if they did, every
product would read as out of scope and the engine would look broken while
working perfectly.

Against the live catalogue the headline beat looks like this: asked for an
office chair, the agent finds a Bdi Circa at 999.00 from 2modern.com, is
refused by the 100.00 per-item cap, searches again with 100.00 as a ceiling,
and buys an Ergonomic Mesh Office Chair at 74.99 from costway.com.

One detail worth naming, because it cuts against this project's first rule.
Channel3 returns prices as JSON numbers in dollars and cents, and no float is
allowed to touch an amount here. So the response is parsed with
`parse_float=Decimal` and reaches `Money.from_major` as a `Decimal`. A float
of `110.99` never exists, not even for an instant. `tests/test_catalog.py`
pins that with the awkward values.

## API

| Method | Path | |
| --- | --- | --- |
| `POST` | `/mandates` | Open a spending authority |
| `POST` | `/mandates/{id}/attempts` | The agent asks to spend |
| `POST` | `/mandates/{id}/payouts` | Approve held charges, one PayPal batch |
| `POST` | `/mandates/{id}/revoke` | Pull the mandate, drop the holds |
| `POST` | `/charges/{id}/release` | Decline one hold |
| `GET` | `/catalog/search` | What the agent can see in the shop |
| `POST` | `/mandates/{id}/shop` | Send the agent shopping against this mandate |
| `GET` | `/mandates/{id}` | Balances plus the terms the authority actually grants |
| `GET` | `/mandates/{id}/decisions` | Every decision with its full trace |
| `GET` | `/payouts/{batch_id}` | Batch status from the processor |
| `POST` | `/payouts/{batch_id}/reconcile` | Re-read a batch and correct the ledger |
| `POST` | `/payouts/reconcile` | The same, across every batch sent |
| `POST` | `/demo/reset` | Rebuild the seeded scenario |
