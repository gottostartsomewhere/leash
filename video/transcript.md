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

## What take 1 actually says

Against the script. Everything not listed matched.

| At | Script | Said | Verdict |
| --- | --- | --- | --- |
| 0:33 | "And when it is refused" | "When it is refused" | fine |
| 0:48 | "Named merchants, named categories" | "name merchants, name categories" | fine |
| 0:51 | "send an agent **at** it" | "send an agent **as** it" | **misread** |
| 0:54 | "**Find** me an office chair" | "...me an office chair" | **word dropped** |
| 0:58 | "**That** is the only decision" | "**This** is the only decision" | fine |
| 1:03 | "Refused on the ceiling" | "**This is** refused on the ceiling" | cut, fixed |
| 1:12 | "**Tell an agent** nothing over a hundred" | "**A teleagent** nothing over a hundred" | **garbled** |
| 1:26 | "refused **as** structuring" | "refused **a** structuring" | fine |
| 1:37 | "Same **amounts**" | "Same **amount**" | fine |
| 1:49 | "**Money** that already moved" | "...that already moved" | **word dropped** |
| 1:57 | "Two red **teams**" | heard as "two red **themes**" | probably the transcript |
| 2:10 | — | "**thank you**" | cut |

Two of those were fixed in the edit by cutting: the "This is" in front of
"refused", and the "thank you" on the end. The rest are in the mix.

## Worth a pickup, in order

Four lines. Each is one sentence, and a re-record of any of them drops
straight into `sound.mjs` without touching anything else.

1. **"Tell an agent nothing over a hundred, and a competent one does not
   give up. It splits the purchase."** The transcript has "a teleagent",
   which is either a genuine stumble or a very fast delivery. This is the
   setup for the whole structuring beat, so it has to be clean.
2. **"Now send an agent at it with a goal and no budget. Find me an office
   chair."** Two faults in one line: "as it" for "at it", and "Find" is
   missing from the front of the second sentence.
3. **"Money that already moved stays moved..."** starts on "that". The word
   "Money" is either unsaid or gated off, and without it the sentence has
   no subject.
4. **"Only the cluster does not. Refused as structuring."** Only if the
   "a" for "as" bothers you on a listen. It is the weakest of the four.

## Delivery notes for a pickup

- You read at about **128 words a minute**, not the 150 the script was
  timed at. The cue sheet in `script.md` is no longer the placement: the
  real placements live in `LINES` in `sound.mjs`, re-spaced against this
  take. **Match the pace of take 1**, not the script's timings.
- Record at the same distance and in the same room as take 1. The gate on
  that recording is what makes the floor so clean.
- Louder would help. Both takes needed more than 20dB of gain.
