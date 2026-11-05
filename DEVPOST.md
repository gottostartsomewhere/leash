# Leash — Devpost submission copy

Paste-ready. Each heading below maps to a field on the Devpost form.

---

## Project name

Leash

## Elevator pitch

*(Devpost caps this around 200 characters.)*

Scoped, revocable, auditable spending authority for AI agents, settled over PayPal Payouts. Every other demo shows you what their agent can buy. This one shows you what it can't.

---

## About the project

### Inspiration

Every agent demo I watched this year ended the same way: the agent buys the thing, everyone claps, nobody asks what happens when it buys the wrong thing. We are about to hand software a payment method and a goal, and the only control most people have designed is a prompt that says "don't spend more than $100."

A prompt is not a control. It is a suggestion to a system that is explicitly optimising around obstacles.

So I built the other half. Leash is the thing that sits between an agent and the money and says no, in writing, with a reason, before anything moves.

### What it does

You write a mandate: a total budget, a ceiling per purchase, a ceiling per merchant, which categories and merchants are in scope, a pace limit, an expiry. The agent gets a goal, not a budget, and it never touches a payment credential.

Every purchase it attempts runs through eleven checks before any money moves. Each one passes, fails, or is marked not applicable, and the result is recorded with the evidence it was decided on. Approved charges settle through PayPal Payouts in a real batch. Refused ones are kept too, because a refusal you cannot read later is not an audit trail.

The feature I actually care about is **structuring detection**.

Tell an agent "nothing over $100" and a competent one does not give up at $150. It splits the purchase. Two charges of $75 to what looks like two different payees, except both addresses belong to the same merchant. Every single charge passes the per-item check. Only the cluster fails.

Leash resolves payees back to their registrable domain, groups charges by merchant inside a sliding window, and refuses the second one with the arithmetic attached: 75 + 75 = 150, over a 100 cap, two charges, 900 second window. You can see exactly why it said no.

Revocation works the way it should. One click kills the mandate mid-session. Every hold that has not settled is dropped and the budget returns. Money that already moved stays moved, because that is the truth, and a tool that pretends otherwise is lying to you. The agent does not know anything changed. It keeps asking. It keeps getting nothing.

### How I built it

**Backend** is FastAPI and Pydantic v2. The decision engine is eleven independent checks over an immutable context, each returning a structured result rather than a boolean, so the UI can render why a thing was refused instead of just that it was.

Money is integer minor units everywhere. The Channel3 catalogue hands back prices as JSON numbers in dollars, so the parse at that boundary uses `json.loads(text, parse_float=Decimal)`, which means a float of 110.99 never exists even briefly. That is not pedantry. It is the single cheapest way to never have a rounding bug in a ledger.

**Payments** are PayPal Payouts v1. Charges settle on PENDING or PROCESSING and reconcile later against item status, and the reconciliation is deliberately asymmetric. If PayPal says the money came back and the ledger thinks it settled, Leash fixes that itself and returns the budget. If PayPal says the money went and the ledger thinks it did not, Leash reports it and changes nothing, because re-committing budget that has since been spent elsewhere could take the mandate past its own limit.

**Catalogue** is Channel3, so the agent shops a live product index rather than a fixture. In the demo it finds a $999 office chair, gets refused at the $100 ceiling, and comes back with a $90.55 one from a different merchant. That whole sequence is real: real search, real refusal, real payout.

**Frontend** is React and AG Grid Community over the live decision log, with filtering and search across every decision the engine has made.

Four seams use a Protocol with two implementations: the payout gateway, the agent brain, the adversary, and the catalogue. Each has a real one and a deterministic offline one. With no credentials the entire app runs offline and all 224 tests pass, which is what made it possible to build the rules properly instead of around an API.

### Challenges I ran into

**Structuring is harder than it sounds.** The naive version groups by payee id and catches nothing, because the whole point is that the addresses differ. Resolving `shop.acme.co.uk` and `pay.acme.com` back to the same merchant means handling compound public suffixes, and getting it wrong in the other direction is worse: merging two genuinely separate merchants would refuse honest purchases.

**A test suite that was quietly lying.** Four tests only passed because nobody on the team had a PayPal key, so the settings fell back to the simulated gateway. They had been green for weeks and would have gone red the moment anyone configured credentials. A hermetic settings fixture fixed it. Separately, migrating to Channel3's real taxonomy exposed three tests named for stock and pacing that were actually passing on a category refusal, so they had been testing nothing at all.

**`env_file=".env"` resolves against the working directory.** Running uvicorn from one directory up silently fell back to the simulated gateway. Silent fallback is the worst possible failure for this: the demo runs, looks perfect, and moves no money. It now resolves from the module path.

**The trailer.** Camera moves are a CSS transform on the app root, which meant the screencast and the recorded marks drifted. One shot opened on a held still and ran a second and a half out of sync, because the frame resampler zeroed on the first frame that painted rather than the clock the marks were written against. Captions now anchor to marks the recorder emits, so a slower catalogue search cannot put the text on the wrong frames.

### Accomplishments that I'm proud of

I pointed a red team at it. Five objectives: beat the per-purchase cap, beat the per-merchant cap, spend past the total, buy outside the categories, spend after revocation. A strategy-search adversary ran **338 attempts** against them.

**Zero breaches.** Nineteen charges were allowed, and every one of them was genuinely inside the mandate. Not one of the five objectives was ever reached.

The whole thing is also really live. Real PayPal sandbox batches, real money moving between sandbox accounts, real products from a real catalogue, deployed and running right now rather than a video of a localhost.

### What I learned

The interesting failures in agent payments are not single transactions. They are patterns across transactions. Any control that only looks at the charge in front of it will miss the attack that matters, because a competent agent will decompose anything you cap into pieces that each clear the cap.

I also learned how much work a good refusal is. Returning `false` is easy. Returning "refused as structuring, here are the two charges, here is the window, here is the arithmetic, here is the largest amount that would have cleared" is most of the engineering, and it is the only version a human can act on.

### What's next for Leash

Mandate delegation, so an agent can issue a narrower mandate to a sub-agent and never a wider one. Webhook-driven reconciliation instead of polling. A hosted policy format so mandates are portable between agent frameworks. And moving from Payouts to a capture-based flow, which gets real authorization holds rather than the ledger holds Leash keeps today.

---

## Built with

```
python  fastapi  pydantic  paypal  paypal-payouts  channel3
react  typescript  vite  ag-grid  render  playwright  ffmpeg
```

## Try it out

- **Live app:** https://leash-web.onrender.com
- **API health:** https://leash-api-sm0h.onrender.com/health
- **Source:** https://github.com/gottostartsomewhere/leash
- **Video:** `[YOUTUBE LINK GOES HERE]`

> The API is on a free Render instance and sleeps after fifteen minutes, so the
> first request can take about fifty seconds to wake it. Everything after that
> is instant.

### What to try, in order

1. Hit **Run scenario** for the whole sequence end to end.
2. Open **Send it shopping**, type "office chair", and hit **Send the agent**. Watch it get refused at the ceiling and come back with something it is allowed to buy.
3. Open **Ask for one thing** and send $75 to `acme_us`, then $75 to `acme_eu`. Both are under the $100 cap. The second one is refused as structuring.
4. Hit **Revoke**, then try to spend anything at all.
