# Leash — demo video script

**Target 2:58.** Judges are not required to watch past three minutes, so
nothing after 2:58 exists. Every second before it has to earn its place.

**The one idea the video has to land:** everyone is building agents that can
spend. Nobody is building the part that says no. That sentence is the whole
pitch and the structuring catch is the proof.

**Principle for the graphics.** The app is already designed. Motion graphics
frame and emphasise it, they do not compete with it. No separate animated
scenes that look like a different product. The only pure-graphics moment is
the opening, because there is nothing to show yet.

Match the app exactly:

| | |
| --- | --- |
| Ground | `#0b0a09` |
| Ink | `#ece7e1` |
| Amber, a rule fired | `#dfa33c` |
| Red, critical | `#e2553d` |
| Green, settled | `#7fa37a` |
| UI type | Archivo |
| Numbers and rule names | JetBrains Mono, tabular |

No music with a licence you cannot prove. The rules say so explicitly, and a
silent cut is better than a disqualified one.

---

## 0:00 – 0:18 · The problem

**Visual.** Black. Nothing on screen yet.

Type-on, one line at a time, JetBrains Mono, centred, ink on ground. Each
line lands on a beat with the voice. Previous lines dim to `#6a635c` as the
next arrives.

```
    the agent books the flight
    the agent orders the parts
    the agent pays the invoice
```

Then all three dim at once and a fourth line types in amber:

```
    and if it gets it wrong
```

Hold one beat. Cut.

**Voice.**

> Every agent demo this year ends the same way. The agent buys something, and
> everyone claps.
>
> Nobody shows you the other half. What happens when it shouldn't have.

---

## 0:18 – 0:38 · What it is

**Visual.** Hard cut to the live app, already loaded, log empty. Let the
screen sit for a second before anything moves. It should look like an
instrument, not a website.

Slow push in on the **Terms** panel in the left rail. As the voice names each
one, draw a thin amber underline under that row, left to right, 200ms:

- Total authority 500.00
- Any one purchase 100.00
- Any one counterparty 200.00
- Pace per 1m

Lower third, bottom left, Archivo: **Leash — spending authority for AI agents**

**Voice.**

> This is Leash. You give an agent a budget with real terms attached. Five
> hundred total. Nothing over a hundred in one purchase. Two hundred maximum
> to any one merchant. Six purchases a minute.
>
> Then it goes shopping, and every single thing it tries gets judged against
> those terms before any money moves.

---

## 0:38 – 1:12 · It gets told no, and does something about it

**Visual.** Switch to **Send it shopping**. Type `office chair`. Click **Send
the agent**.

Let the real result land. Then freeze and overlay.

Three callouts, appearing in sequence, each a hairline box in the app's own
border colour with a mono label:

1. Ring the refused row. Label, amber: `999.00 — over the 100 cap`
2. Ring the turn line. Label, ink: `100.00 would have cleared`
3. Ring the bought row. Label, green: `74.99 — bought instead`

Then a connecting line animates 1 → 2 → 3, so the eye follows the decision.

**Voice.**

> Here it is shopping a real catalogue. It finds a chair it likes, nine
> hundred and ninety nine dollars, from a real merchant.
>
> That is over the cap, so it gets refused. But look at what the refusal
> tells it. Not just no. A hundred dollars would have gone through.
>
> So the agent searches again under a hundred, and buys a different chair for
> seventy four ninety nine. A refusal it can actually act on, instead of a
> wall.

---

## 1:12 – 1:58 · The one that matters

**Visual.** Switch to **Ask for one thing**. This has to be slow and
deliberate. It is the centre of the video.

Send `75.00` to `acme_us`. It clears. Ring it green, label `75.00 — fine`.

Send `75.00` to `acme_eu`. The row lands red and opens itself.

Now hold on the evidence band and let the cluster chart breathe. Push in
slowly. As the voice gets to the cap line, animate a red dashed vertical line
drawing downward through all three bars, then pulse once.

Label the two prior bars in mono: `under the cap` / `under the cap`
Label the total bar in red: `150.00 — over`

Full-width card, held for two seconds, Archivo, ink on ground:

```
      Two addresses. One merchant.
```

**Voice.**

> Now watch this. Seventy five dollars to Acme. Fine, it clears.
>
> Another seventy five to Acme, but to their second receiver address. Each
> charge is under the hundred dollar cap. Checked on its own, each one
> passes.
>
> Leash blocks it anyway.
>
> Because it is not checking charges, it is checking the merchant behind
> them. Two addresses, one counterparty, a hundred and fifty dollars inside
> fifteen minutes. That is a purchase that was split to get under a limit.
>
> It is called structuring, it is a real pattern in financial crime, and an
> agent told nothing over a hundred will work it out on its own.

---

## 1:58 – 2:22 · The money is real

**Visual.** Select the held rows. Click **Approve and pay out**.

As rows flash to `Settled`, a counter in the corner rolls up in mono.

Then cut to **sandbox.paypal.com**, logged in, Activity list visible. Push in
on the incoming payments. Overlay in green: `PayPal Payouts · sandbox`

Do not linger. Four seconds on the balance is enough to prove it.

**Voice.**

> Nothing has actually moved yet. Everything so far is a hold, which is why
> two purchases a millisecond apart can't both spend the same budget.
>
> A human approves, and it goes out as one PayPal Payouts batch. That is a
> real sandbox account receiving real payouts.
>
> And if an item comes back later, reconciliation corrects the ledger, so it
> records what happened rather than what we intended.

---

## 2:22 – 2:38 · The leash comes off

**Visual.** Click **Revoke**. Status flips to red across the top bar and the
rail. Held rows drop to `Released`.

Then ask for one more spend. The row lands critical red.

Zoom the rule chip: `Mandate inactive`

**Voice.**

> And you can take it all back. Revoking drops every hold that hasn't
> settled. Money that already moved stays moved, because that is the truth.
>
> Ask it for anything after that, and it just says no.

---

## 2:38 – 2:58 · The evidence, and the line

**Visual.** Cut to terminal, the red team output. Let the real numbers sit on
screen. Highlight the last line.

```
5 objectives, 338 attempts, 319 refused. Mandate HELD.
```

Then to black. The closing line types on in ink, one clause at a time:

```
    Every other demo shows you
    what their agent can buy.
```

Beat. Then in amber:

```
    This one shows you what it can't.
```

Hold two seconds. End card: **leash-web.onrender.com**

**Voice.**

> I pointed an adversary at it. Three hundred and thirty eight attempts to
> get around the rules, across five different objectives. Splitting
> purchases, hopping addresses, waiting out windows. It never got through
> once.
>
> Every other demo shows you what their agent can buy. This one shows you
> what it can't.

---

## Capture checklist

Record these before you edit anything. Clean takes, no cursor wandering.

- [ ] App loaded, log empty, mandate at 500.00
- [ ] Shop: `office chair`, full re-shop result
- [ ] Ask: `75.00` acme_us, then `75.00` acme_eu, band open
- [ ] Evidence band, close, cluster chart filling frame
- [ ] Select holds, approve, rows flashing to Settled
- [ ] sandbox.paypal.com Activity with payments visible
- [ ] Revoke, then one refused attempt after it
- [ ] Terminal: `python scripts/redteam.py`

**Reset between takes.** The Reset button in the rail, or
`POST /demo/reset`. A dirty ledger will give you different numbers than this
script says.

**One trap.** Run the scenario at human speed and the pace limit never fires,
because it needs six holds inside sixty seconds. If you want that beat, click
fast or cut the pause out.

---

## If you need to cut for time

In this order:

1. The reconciliation sentence at 2:15. It is the most sophisticated thing in
   the project and the least visual.
2. The pace limit, if you added it.
3. Tighten the opening to two lines instead of three.

**Never cut** the structuring beat or the closing line. Without those it is
just another agent demo, and there will be four hundred of those.
