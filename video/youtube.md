# YouTube upload

The file: `video/leash-trailer-sound.mp4` (Desktop copy "Leash demo v2.mp4"),
2:55, 1920x1080, 30fps, -14.5 LUFS. Devpost requires under three minutes and
a public link. This is the second cut; the first is in `video/v1/`.

## Settings that matter

- **Visibility: Public.** Not unlisted. Devpost's rules ask for a publicly
  viewable video, and an unlisted link is a reason for a judge to stop.
- **Made for kids: No.** YouTube disables several things on videos marked
  for kids, and getting this wrong is annoying to undo.
- **Category:** Science & Technology.
- Leave monetisation and end screens alone. The last five seconds are the
  end card and an end-screen overlay would sit on top of it.

## Title

```
Leash: spending limits for AI agents, with structuring detection and a live red team
```

84 characters. Leads with the name and says what is actually novel rather
than "AI agent payments demo".

## Description

```
Leash is scoped, revocable, auditable spending authority for AI agents, settled over PayPal Payouts.

You write a mandate: a total, a ceiling per purchase, a ceiling per merchant, which categories are in scope, a pace limit, an expiry. Or write it in plain English: a model drafts the terms, and before you sign, the screen shows how it read you, what it can't enforce, the worst an agent could do inside it, and the result of attacking it.

The agent gets a goal, not a budget, and never touches a payment credential. Every purchase runs eleven checks before any money moves, and every decision is recorded with the evidence it was made on. When it's refused, it's told what would have cleared.

The part I care about is structuring detection. Tell an agent "nothing over $100" and a competent one doesn't give up at $150. It splits the purchase: two charges of $75 to what look like two payees, except both addresses belong to the same merchant. Each charge passes on its own. Only the cluster fails.

Two red teams went at it, a strategy search and a model. The model found a real boundary bug: a charge of exactly the cap fell between three checks, each assuming another owned it. That's fixed, with regression tests. 322 attempts across both, zero breaches. You can attack it yourself from the page.

Any agent can be put on it. The mandate is served over MCP, so Claude, ChatGPT or any MCP client connects with one URL and gets held to the same rules. No tool it can call moves money.

Everything in this video is live: real PayPal sandbox payout batches, a real product catalogue through Channel3, and real models drafting, choosing and attacking.

Try it: https://leash-web.onrender.com
Source: https://github.com/gottostartsomewhere/leash

The API runs on a free Render instance and sleeps after fifteen idle minutes, so the first load can take about fifty seconds.

Built for the PayPal AI Hackathon.

00:00 The problem
00:11 How it works
00:38 A mandate written in plain English
01:10 A model goes shopping, and gets refused
01:31 Structuring: two addresses, one merchant
01:47 Attack it yourself
01:58 Your own agent, over MCP
02:10 Settling through PayPal Payouts
02:33 Revoking mid-session
02:45 Close
```

The timestamps are real chapter marks, taken from the cut's segment starts.
YouTube turns them into chapters when the first is `00:00`, there are at
least three, and each is at least ten seconds long. The live landing screen
(0:38 to 0:45) is folded into the plain-English chapter because seven
seconds is too short for one, and the MCP chapter starts at 1:58 rather than
1:57 so "Attack it yourself" clears the ten second minimum.

## Tags

```
AI agents, agent payments, PayPal, PayPal Payouts, structuring detection,
agentic commerce, LLM red team, fintech, spending limits, hackathon
```

## Thumbnail

`video/thumb.jpg`, 2560x1440, 306KB. Rebuild with `node video/thumb.mjs`,
which also writes a PNG and a 1280x720. Upload the JPEG: same resolution,
a sixth of the PNG's weight, and the PNG sits at 1.78MB against a 2MB
ceiling, which is too near the edge for a file you pick once.

The wordmark over three real frames of the app, angled and dimmed. Two
things that were not obvious:

The screenshots had to be **brightened**, not just faded up. The interface
is near-black by design, so dark frames at half opacity over a dark ground
are empty rectangles. They are lifted about two stops and the veil takes
the brightness back out of the middle, where the name sits.

The mark is the app's own, from `App.tsx`: an anchor point, a cord with
slack in it, a collar. Not the favicon's loop-and-handle, which is right at
16px in a browser tab and reads as the symbol for Mars once it is four
inches wide.

Checked at 320x180, which is the size it is chosen at. The wordmark, the
mark and the tagline all survive.

## After it is up

Put the link in `DEVPOST.md` where `[YOUTUBE LINK GOES HERE]` is, and in the
Devpost form's video field. Devpost wants the plain watch URL, not an embed
or a share link with tracking on it: `https://www.youtube.com/watch?v=...`
