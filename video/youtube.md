# YouTube upload

The file: `video/leash-trailer-sound.mp4`, 2:42, 1920x1080, 30fps,
-14.0 LUFS. Devpost requires under three minutes and a public link.

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
Leash: a spending limit for AI agents, with structuring detection
```

Under 100 characters, leads with the name, and says the thing that is
actually novel rather than "AI agent payments demo".

## Description

```
Leash is scoped, revocable, auditable spending authority for AI agents,
settled over PayPal Payouts.

You write a mandate: a total, a ceiling per purchase, a ceiling per
merchant, which categories and merchants are in scope, a pace limit, an
expiry. The agent gets a goal, not a budget, and it never touches a payment
credential. Every purchase it attempts runs eleven checks before any money
moves, and every decision is recorded with the evidence it was made on.

The part I care about is structuring detection. Tell an agent "nothing over
$100" and a competent one does not give up at $150, it splits the purchase:
two charges of $75 to what look like two different payees, except both
addresses belong to the same merchant. Every individual charge passes. Only
the cluster fails.

An LLM red team found a real boundary bug in those checks, a charge of
exactly the cap falling between two of them, each assuming the other owned
it. That is fixed, with regression tests. 322 attempts across both red
teams, zero breaches.

Everything in this video is live: real PayPal sandbox payout batches, a real
product catalogue through Channel3, and a model choosing what to buy.

Try it:     https://leash-web.onrender.com
Source:     https://github.com/gottostartsomewhere/leash

The API runs on a free Render instance and sleeps after fifteen idle
minutes, so the first load can take about fifty seconds to wake it.

Built for the PayPal AI Hackathon.

00:00  The problem
00:11  How it works
00:48  The mandate
01:00  A model goes shopping, and gets refused
01:22  Structuring: two addresses, one merchant
01:46  Settling through PayPal Payouts
02:09  Revoking mid-session
02:24  The red team
02:31  Close
```

The timestamps are real chapter marks. YouTube turns them into chapters
automatically when the first one is `00:00` and there are at least three,
each at least ten seconds apart. Chapters help a judge skip to structuring,
which is the thing worth seeing.

## Tags

```
AI agents, agent payments, PayPal, PayPal Payouts, structuring detection,
agentic commerce, LLM red team, fintech, spending limits, hackathon
```

## Thumbnail

YouTube will offer three frames from the video. Take the one with the
decision grid on it if offered, or upload a still: the frame around 1:19 has
the refusal, the counter-offer and the model's own reasoning all legible in
one shot, which is the whole project in one picture.

Pull one with:

```bash
video/node_modules/ffmpeg-static/ffmpeg.exe -ss 79 -i video/leash-trailer-sound.mp4 -frames:v 1 video/thumb.png
```

## After it is up

Put the link in `DEVPOST.md` where `[YOUTUBE LINK GOES HERE]` is, and in the
Devpost form's video field. Devpost wants the plain watch URL, not an embed
or a share link with tracking on it: `https://www.youtube.com/watch?v=...`
