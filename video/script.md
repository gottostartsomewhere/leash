# Leash · voiceover script

Written against the cut that exists: **`video/leash-trailer.mp4`, 2:42.**

**Do not change a segment length after recording.** Everything below is
timed to the picture, and moving a slot by two seconds slides every cue
after it.

## How to read this

- Times are where you **start** the line, not where it ends.
- Word counts are there so you know whether you are rushing. Roughly
  **150 words a minute** is a normal speaking pace; this script runs at
  about **110**, which leaves room to breathe and to stop.
- **The silences are written in and they are not padding.** The picture is
  doing the work in those gaps.

## The one rule

**Never read what is already on screen.** The cards and the animation
captions carry the *mechanics*. Your job is the *argument*. There is one
deliberate exception, the last two lines, where saying it with the card is
the point.

---

## 0:00 · the problem card · 7s

The card writes itself: *the agent books the flight, orders the parts, pays
the invoice, and if it gets it wrong.* Reading that aloud would be reading
the screen.

> *(silent, let it land)*

---

## 0:08 · title, into the animation · ~10s · 24 words

Start just as the Leash wordmark settles. Flat delivery. This is the whole
pitch and it should sound like an observation, not a slogan.

> Every agent demo ends the same way. The agent buys the thing, everyone
> claps, and nobody asks what happens when it buys the wrong thing.

---

## 0:20 · the animation, act one · ~9s · 23 words

The track and the eleven checks are on screen now.

> Leash is the part that says no. You write a mandate. A total, a ceiling
> per purchase, which merchants, which categories, how fast.

---

## 0:31 · the animation, act two · ~10s · 25 words

The token is running at the wall.

> The agent gets a goal, not a budget. It never touches a payment
> credential. Every purchase it tries runs eleven checks before any money
> moves.

---

## 0:42 · the counter-offer · ~5s · 14 words

> And when it is refused, it is not just blocked. It is told what would
> have cleared.

> *(then stop, let acts three and four play out on their own)*

---

## 0:49 · the live app · ~4s · 11 words

Hard cut from animation to the real thing. Mark the change in your voice.

> That is the idea. This is it running, for real.

---

## 0:54 · the mandate · ~5s · 13 words

> One mandate. Five hundred dollars. A hundred a purchase. Named merchants,
> named categories.

---

## 1:01 · shopping · ~7s · 19 words

The shelf is sliding in under you. Real products, real merchants.

> Now send an agent at it with a goal and no budget. Find me an office
> chair.

---

## 1:12 · the model picks · ~5s · 14 words

The camera is about to push onto the byline. **Say this into the push**, so
the words land as the name does.

> A model chooses the product. That is the only decision it gets to make.

---

## 1:18 · the refusal · ~8s · 22 words

The callout is counting up while you say it. Name the numbers, do not read
them off.

> It picked a hundred and ninety dollar chair. Refused at the hundred
> dollar ceiling, told what would clear, and it came back inside.

---

## 1:23 · structuring · ~3s · 7 words

Slow down here. This is the beat the whole submission rests on.

> Now the part I actually care about.

---

## 1:28 · the split · ~7s · 18 words

> Tell an agent nothing over a hundred, and a competent one does not give
> up. It splits the purchase.

---

## 1:36 · two addresses · ~8s · 21 words

> Seventy five to Acme US. Seventy five to Acme EU. Two addresses, one
> merchant. Each charge clears the cap on its own.

---

## 1:45 · the catch · ~5s · 11 words

Land this one hard, then nothing.

> Only the cluster does not. Refused as structuring, with the arithmetic
> attached.

---

## 1:52 · the money · ~7s · 17 words

> Approved spend settles through PayPal Payouts. Real batches, real money,
> a sandbox account on the other side.

---

## 2:02 · PayPal's own ledger · ~3s · 6 words

> Same amounts, in PayPal's own books.

---

## 2:10 · revoke · ~6s · 14 words

> And it comes off. One click, mid session. Every hold that has not settled
> is dropped.

---

## 2:17 · what revocation actually means · ~8s · 23 words

> Money that already moved stays moved, because that is the truth. The agent
> does not know anything changed. It keeps asking. It keeps getting nothing.

---

## 2:25 · the red team · ~5s · 12 words

> We pointed two red teams at it. One of them was a model.

---

## 2:30 · the numbers · ~4s · 10 words

The card is showing 5 / 322 / 0 while you say this. You are naming them,
not reading them.

> Three hundred and twenty two attempts, five objectives, zero breaches.

---

## 2:33 · the close · ~4s · 10 words

**The exception to the rule.** The card says these words and so do you.
Say them with it, not over it.

> Every other demo shows you what their agent can buy.

---

## 2:37 · the turn · ~3s · 8 words

> This one shows you what it cannot.

> *(out, let the end card hold)*

---

## Numbers, so none of them drift

Everything the voice says has to match what is on screen.

| Where | Figure | Source |
| --- | --- | --- |
| mandate | $500 total, $100 a purchase | the demo mandate in `leash/store.py` |
| shop | $190.49 refused, $97.99 bought | the live run in the footage |
| structuring | $75 + $75 to two Acme addresses | the live run |
| red team | 5 objectives, 322 attempts, 0 breaches | 316 strategy + 6 model, both artifacts |

Two sets of numbers died along the way and are still quotable by accident:

- **Not 338 attempts, not 319 refused.** Those were the totals before the
  boundary bug was fixed. The strategy run is 316 and 297 now, and the card
  in the video says 322, which is both adversaries together.
- **Not a $999 chair.** That was the ranking fallback picking the top of the
  shelf, back when the agent had no model in it. The model picks the
  $190.49 one and the chair it settles on is $97.99. The $999 chair is
  still visible on the shelf, which is why the wrong number is easy to say.

## Recording notes

- One take per section is fine. They are cut to timecode, not performed
  continuously, so a fluff only costs you that section.
- Record dry and close. No music, no room. The picture has no audio at all,
  so the voice sits on a silent bed and anything in the room will be heard.
- Lower than feels natural. The material is dry on purpose, and selling it
  harder makes it sound less true.
- Total spoken: about **300 words over 2:42**, which is unhurried. If you
  are running out of breath, you are going too fast, not too long.
