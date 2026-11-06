# Voiceover takes · transcript and verdict

Two takes, both read continuously rather than to the cue sheet. Transcribed
with Whisper large-v3 through Groq's free tier, word-level timestamps, which
is also what `sound.mjs` cuts against.

| | take 1 | take 2 |
| --- | --- | --- |
| file | `Record (online-voice-recorder.com).mp3` | `...(1).mp3` |
| length | 2:13.03 | 2:15.46 |
| integrated | -38.0 LUFS | -35.1 LUFS |
| true peak | -14.0 dBTP | -10.1 dBTP |
| loudness range | 5.8 LU | 7.7 LU |
| **noise floor** | **-94.8 dB** | **-58.4 dB** |

## Take 1 wins, and it is not close

**The noise floor decides it.** 36 decibels between them. Both takes are far
too quiet and have to come up by about 22dB to be usable, and that gain
lands on the room as much as on the voice. Take 1's floor goes to -73dB,
which nobody will ever hear. Take 2's goes to -36dB, which is audible hiss
between every line of a trailer whose picture has no sound of its own to
hide it. That floor is not fixable after the fact without a denoiser
chewing on the consonants.

Take 2 is the better *performance*: 7.7 LU of range against 5.8 means more
light and shade, and it is the more confident read. It is also the take
that breaks the closing line.

**Take 2 says "every other demo shows you what their agent can't buy."**
The line is "what their agent **can** buy", and the whole ending is the
contrast between *can* and *cannot*. With "can't" in the first half the
turn says nothing. It then follows with "what **he** cannot". Those two
together would have been the last thing a judge heard.

Take 1 reads that line correctly.

## Transcribing it twice changed the verdict

The assembled voice track was transcribed a second time and diffed, word by
word, against the words the edit claims to carry. 285 expected, 285 heard,
and that pass cleared three of the faults the first transcript reported.

- **"Find" is there.** "Find me an office chair" is complete. The first pass
  dropped the word; the second heard it.
- **"Money" is there.** "Money that already moved stays moved" has its
  subject. Same story.
- **"named merchants, named categories"** is what he says. The first pass
  heard "name" twice.

Three faults that only ever existed in the transcript. Worth knowing before
re-recording anything on a machine's say-so.

## What take 1 actually says

Against the script, after both passes. Everything not listed matched.

| At | Script | Said | Verdict |
| --- | --- | --- | --- |
| 0:33 | "And when it is refused" | "When it is refused" | fine |
| 0:51 | "send an agent **at** it" | "send an agent **as** it" | **misread** |
| 0:58 | "**That** is the only decision" | "**This** is the only decision" | fine |
| 1:03 | "Refused on the ceiling" | "**This is** refused on the ceiling" | kept, see below |
| 1:12 | "**Tell an agent** nothing over a hundred" | "**A teleagent** nothing over a hundred" | **check this one** |
| 1:26 | "refused **as** structuring" | "refused **a** structuring" | fine |
| 1:37 | "Same **amounts**" | "Same **amount**" | fine |
| 2:10 | — | "**thank you**" | cut |

## Two cuts the edit could not make

Both of these were tried and both took a word with them, because he runs
straight through those two joins with no pause anywhere in them. There is
no silence to put a boundary in, so the cut landed inside a syllable.

- **"This is" in front of "refused" is kept.** Cutting it returned "is
  ruffed" from the check transcript. The sentence is no worse for carrying
  it.
- **The closing couplet is one clip.** "...what their agent can buy. This
  one shows you what it cannot." was delivered as one thought with no
  pause, and splitting it deleted the "This". It now plays as one line,
  placed so the turn lands as the end card arrives, which is where it
  wanted to be anyway.

## Worth a pickup

Down to two, in order. Either drops straight into `sound.mjs` without
touching anything else.

1. **"Tell an agent nothing over a hundred, and a competent one does not
   give up. It splits the purchase."** Both transcription passes heard "a
   teleagent", which is either a real stumble or just a very fast delivery
   that Whisper cannot resolve. **Listen to this one before deciding**, at
   1:12 in the mix. It is the setup for the whole structuring beat.
2. **"Now send an agent at it with a goal and no budget."** Both passes
   heard "as it". Same caveat: listen first.

Nothing else is worth your time. The two dropped words turned out not to be
dropped.

## Delivery notes, if you do record a pickup

- You read at about **128 words a minute**, not the 150 the script was
  timed at. The cue sheet in `script.md` is no longer the placement: the
  real placements live in `LINES` in `sound.mjs`, re-spaced against this
  take. **Match the pace of take 1**, not the script's timings.
- Record at the same distance and in the same room as take 1. The gate on
  that recording is what makes the floor so clean, and it is also what
  gives `sound.mjs` a real silence to put every cut inside.
- Louder would help. Both takes needed more than 20dB of gain.

## How the edit is checked

`node video/sound.mjs` prints, per line, the silence actually kept at each
boundary. Both numbers should be around 0.25 and 0.34. A line reading
`NO SILENCE, padded blindly` has no gap to cut in and will take a syllable
of its neighbour with it.

For the real check, encode `sound/voice.wav` to mp3, transcribe it, and
diff it against the spans in `LINES`. Checking cut quality against Whisper's
own word times does not work: it pads each word's end out to wherever the
next one starts, so "fast." is reported ending at 21.14 when the sound
stops at 19.81.
