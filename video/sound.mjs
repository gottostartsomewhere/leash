// Builds the trailer's soundtrack and muxes it onto the picture.
//
//   node video/sound.mjs            everything
//   node video/sound.mjs --vo       just the voice track, for checking
//
// The voiceover was recorded as one continuous read, 2:13 of it, against a
// picture that runs 2:42 with the silences written in. So it is cut apart
// here at word boundaries from the Whisper pass in `_take1.json` and each
// line is placed at the second the script says it starts. That is the only
// way the read and the cut can agree without re-recording to a click.
//
// Every sound effect is synthesised. Nothing is licensed, nothing is
// downloaded, and nothing costs anything.

import { execFileSync } from "node:child_process";
import ffmpeg from "ffmpeg-static";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WORK = path.join(HERE, "sound");
const TAKE = path.join(HERE, "_take1.json");
const SRC = "C:/Users/johnk/Downloads/Record (online-voice-recorder.com).mp3";
const PICTURE = path.join(HERE, "leash-trailer.mp4");
const OUT = path.join(HERE, "leash-trailer-sound.mp4");

const SR = 48000;
const RUNTIME = 162.2; // the picture, 2:42.2

function run(args) {
  execFileSync(ffmpeg, ["-hide_banner", "-loglevel", "error", "-y", ...args], {
    stdio: ["ignore", "ignore", "pipe"],
  });
}

// ---------------------------------------------------------------- the voice

// Each line, as a span of word indices in the transcript and the second the
// script starts it. Word indices rather than timestamps because the words
// are what was actually said: a span that starts on "refused" cannot
// accidentally include the "This is" he put in front of it.
// `at` is NOT the script's cue sheet. The script was timed at 150 words a
// minute and he reads at about 128, so five lines ran straight over the
// next cue and the back half drifted a line behind the picture. These are
// re-spaced against the delivery that exists and the beats it has to hit:
// "live" on the cut out of the animation at 47.9, "model" into the camera
// landing on the byline at 75.4, "catch" on the structuring callout at
// 101.5, "close" inside the closing card, "turn" on the end card.
//
// The gaps look impossibly tight because each clip carries its own
// padding: a listed 0.3s gap is 0.3 plus this clip's 0.30s tail plus the
// next one's 0.18s lead, so three quarters of a second of real silence.
const LINES = [
  { name: "pitch", words: [0, 24], at: 8.0 },
  { name: "act-one", words: [25, 47], at: 17.4 },
  { name: "act-two", words: [48, 72], at: 29.0 },
  { name: "counter", words: [73, 88], at: 42.6 },
  { name: "live", words: [89, 98], at: 48.6 },
  { name: "mandate", words: [99, 108], at: 53.4 },
  { name: "shopping", words: [109, 124], at: 60.8 },
  { name: "model", words: [125, 138], at: 73.6 },
  // Starts on "refused", not on the "This is" he added before it.
  { name: "refusal", words: [141, 153], at: 79.4 },
  { name: "structuring", words: [154, 161], at: 85.2 },
  { name: "split", words: [162, 179], at: 88.6 },
  { name: "addresses", words: [180, 191], at: 95.6 },
  { name: "catch", words: [192, 199], at: 101.5 },
  { name: "money", words: [200, 216], at: 108.2 },
  { name: "books", words: [217, 222], at: 121.0 },
  { name: "revoke", words: [223, 235], at: 129.6 },
  { name: "meaning", words: [236, 254], at: 136.4 },
  { name: "redteam", words: [255, 263], at: 145.0 },
  { name: "numbers", words: [264, 267], at: 149.6 },
  { name: "close", words: [268, 277], at: 154.7 },
  // Stops before "thank you", which is not in the script and not in the cut.
  { name: "turn", words: [278, 284], at: 158.5 },
];

// Breath room around each cut. Enough that a consonant is never clipped off
// the front, short enough that the gated silence either side stays silent.
const LEAD = 0.18;
const TAIL = 0.30;

function cutVoice() {
  const words = JSON.parse(fs.readFileSync(TAKE, "utf-8")).words;
  const clips = [];

  console.log("voice\n");
  for (const [i, line] of LINES.entries()) {
    const [a, b] = line.words;
    const from = Math.max(0, words[a].start - LEAD);
    const to = words[b].end + TAIL;
    const dur = to - from;
    const next = LINES[i + 1];
    const room = next ? next.at - line.at : RUNTIME - line.at;
    const slack = room - dur;

    const file = path.join(WORK, `vo-${String(i).padStart(2, "0")}-${line.name}.wav`);
    run([
      "-ss", from.toFixed(3), "-t", dur.toFixed(3), "-i", SRC,
      "-ar", String(SR), "-ac", "1",
      // 25ms either end, so a cut never lands as a click.
      "-af", `afade=t=in:st=0:d=0.025,afade=t=out:st=${(dur - 0.025).toFixed(3)}:d=0.025`,
      file,
    ]);
    clips.push({ ...line, file, dur });

    const flag = slack < 0 ? "  OVERRUNS" : slack < 0.4 ? "  tight" : "";
    console.log(
      `  ${line.name.padEnd(12)} ${fmt(line.at)}  ${dur.toFixed(2)}s` +
        `  slack ${slack.toFixed(2)}s${flag}`,
    );
  }
  return clips;
}

function fmt(t) {
  const m = Math.floor(t / 60);
  return `${m}:${(t - m * 60).toFixed(1).padStart(4, "0")}`;
}

function buildVoice(clips) {
  const inputs = clips.flatMap((c) => ["-i", c.file]);
  const delays = clips
    .map((c, n) => `[${n}:a]adelay=${Math.round(c.at * 1000)}:all=1[v${n}]`)
    .join(";");
  const mix = clips.map((_, n) => `[v${n}]`).join("");
  run([
    ...inputs,
    "-filter_complex",
    `${delays};${mix}amix=inputs=${clips.length}:normalize=0:dropout_transition=0[raw];` +
      // The read was quiet and a little boxy. Roll off everything under the
      // voice, take the mud out at 300, lift the consonants, then even it
      // out. loudnorm last, so the compressor is not fighting it.
      `[raw]highpass=f=85,equalizer=f=300:t=q:w=1.2:g=-2.5,` +
      `equalizer=f=3400:t=q:w=1.4:g=2.5,` +
      `acompressor=threshold=-20dB:ratio=3:attack=8:release=180:makeup=2,` +
      `loudnorm=I=-16:TP=-1.5:LRA=9,apad[out]`,
    "-map", "[out]", "-t", String(RUNTIME), "-ar", String(SR), "-ac", "1",
    path.join(WORK, "voice.wav"),
  ]);
}

// ------------------------------------------------------------------ the bed

/** One synthesised element, rendered once and placed many times. */
function element(name, filter, dur) {
  const file = path.join(WORK, `sfx-${name}.wav`);
  run([
    "-f", "lavfi", "-i", `${filter}:d=${dur}:s=${SR}`,
    "-ar", String(SR), "-ac", "1", file,
  ]);
  return file;
}

function makeElements() {
  const out = {};

  // A hit. Two sines an octave apart with a fast exponential decay, which is
  // a drum rather than a beep because the decay is what the ear reads.
  out.impact = element(
    "impact",
    "aevalsrc='(0.9*sin(2*PI*52*t)+0.35*sin(2*PI*104*t))*exp(-4.5*t)'",
    1.4,
  );

  // The same thing an octave down and slower, for the two cuts that are
  // supposed to land like a door closing.
  out.sub = element(
    "sub",
    "aevalsrc='(0.95*sin(2*PI*38*t)+0.25*sin(2*PI*76*t))*exp(-2.2*t)'",
    2.2,
  );

  // A riser. The frequency ramps quadratically so it accelerates into the
  // cut instead of arriving at a constant rate, and the amplitude comes up
  // with it. Quiet, because it is a lead-in and not an event.
  out.riser = element(
    "riser",
    "aevalsrc='0.5*sin(2*PI*(180*t+1400*t*t))*pow(t/1.1,2.2)'",
    1.1,
  );

  // A tick. The checks firing, and the smallest thing in the mix.
  out.tick = element(
    "tick",
    "aevalsrc='0.6*sin(2*PI*2100*t)*exp(-60*t)'",
    0.09,
  );

  // A soft mark, for a camera landing. Rounder than the tick and lower.
  out.land = element(
    "land",
    "aevalsrc='0.5*sin(2*PI*520*t)*exp(-11*t)'",
    0.5,
  );

  return out;
}

// Where each one goes, in finished-timeline seconds. The picture's own
// boundaries, taken from assemble.mjs after the crossfades: a riser leads
// into a cut, the hit lands on it.
const HITS = [
  // the problem card, and the wordmark it resolves into
  { el: "riser", at: 5.5, gain: 0.5 },
  { el: "impact", at: 6.6, gain: 0.8 },
  // into the animation
  { el: "riser", at: 10.1, gain: 0.45 },
  { el: "impact", at: 11.2, gain: 0.6 },
  // the mandate being written, and the token setting off
  { el: "land", at: 20.2, gain: 0.5 },
  { el: "land", at: 31.2, gain: 0.5 },
  // the eleven checks, as the token runs the wall
  ...Array.from({ length: 11 }, (_, n) => ({
    el: "tick",
    at: 32.6 + n * 0.46,
    gain: 0.34,
  })),
  // refused, and the counter-offer
  { el: "impact", at: 41.6, gain: 0.7 },
  { el: "land", at: 45.2, gain: 0.45 },
  // hard cut out of the animation into the live app
  { el: "riser", at: 46.8, gain: 0.6 },
  { el: "sub", at: 47.9, gain: 0.95 },
  // the mandate panel, each push
  { el: "land", at: 50.5, gain: 0.4 },
  { el: "land", at: 53.0, gain: 0.4 },
  { el: "land", at: 56.5, gain: 0.4 },
  // into the shop
  { el: "impact", at: 59.9, gain: 0.55 },
  { el: "land", at: 65.2, gain: 0.4 }, // the shelf
  { el: "tick", at: 68.7, gain: 0.5 }, // send the agent
  // the camera landing on the model's name, then the callout opening
  { el: "land", at: 75.4, gain: 0.6 },
  { el: "tick", at: 77.7, gain: 0.45 },
  // into structuring, which is the beat the whole thing rests on
  { el: "riser", at: 81.4, gain: 0.6 },
  { el: "impact", at: 82.5, gain: 0.85 },
  { el: "tick", at: 85.6, gain: 0.45 }, // the second charge
  { el: "land", at: 87.8, gain: 0.5 }, // the cluster
  // caught
  { el: "sub", at: 101.5, gain: 0.9 },
  // the money moving
  { el: "impact", at: 106.1, gain: 0.5 },
  { el: "land", at: 109.5, gain: 0.45 },
  { el: "land", at: 117.1, gain: 0.45 },
  // PayPal's own books
  { el: "land", at: 120.7, gain: 0.5 },
  // revoke
  { el: "riser", at: 128.2, gain: 0.55 },
  { el: "sub", at: 129.3, gain: 1.0 },
  { el: "land", at: 134.0, gain: 0.4 },
  // the tally counting up
  { el: "riser", at: 142.9, gain: 0.5 },
  { el: "impact", at: 144.0, gain: 0.7 },
  // the close
  { el: "impact", at: 151.6, gain: 0.65 },
  { el: "sub", at: 157.2, gain: 0.85 },
];

function buildEffects(els) {
  const names = [...new Set(HITS.map((h) => h.el))];
  const inputs = names.flatMap((n) => ["-i", els[n]]);

  // A bed under all of it: brown noise with everything above 150Hz taken
  // off, so it reads as room rather than as a sound. Without it the gaps
  // between lines are digital silence, and digital silence sounds broken.
  inputs.push("-f", "lavfi", "-i", `anoisesrc=c=brown:a=0.9:d=${RUNTIME}:r=${SR}`);
  const bedIn = names.length;

  // Each element is used more than once, so every placement needs its own
  // copy of it. asplit on the input, one output per use of that element.
  const splits = names.map((n, i) => {
    const uses = HITS.filter((h) => h.el === n).length;
    return `[${i}:a]asplit=${uses}${HITS.reduce(
      (acc, h, j) => (h.el === n ? acc + `[s${j}]` : acc),
      "",
    )}`;
  });
  const placed = HITS.map(
    (h, i) =>
      `[s${i}]adelay=${Math.round(h.at * 1000)}:all=1,volume=${h.gain}[h${i}]`,
  );

  const mix = HITS.map((_, i) => `[h${i}]`).join("");
  run([
    ...inputs,
    "-filter_complex",
    `${splits.join(";")};${placed.join(";")};` +
      `${mix}amix=inputs=${HITS.length}:normalize=0:dropout_transition=0[hits];` +
      `[${bedIn}:a]lowpass=f=150,volume=0.10[bed];` +
      `[hits][bed]amix=inputs=2:normalize=0[out]`,
    "-map", "[out]", "-t", String(RUNTIME), "-ar", String(SR), "-ac", "1",
    path.join(WORK, "effects.wav"),
  ]);
  console.log(`\neffects    ${HITS.length} placements, ${names.length} elements`);
}

// ------------------------------------------------------------------- mixing

function mix() {
  // The effects duck under the voice rather than being mixed quietly and
  // left there. A bed loud enough to hear between lines is too loud under
  // one, and riding it by hand means it is wrong at every other cue.
  run([
    "-i", path.join(WORK, "voice.wav"),
    "-i", path.join(WORK, "effects.wav"),
    "-filter_complex",
      `[0:a]asplit=2[vo][key];` +
      `[1:a][key]sidechaincompress=threshold=0.05:ratio=6:attack=12:release=420[ducked];` +
      `[vo][ducked]amix=inputs=2:normalize=0:weights=1 0.62[sum];` +
      // -13 to land at about -14 LUFS. Single-pass loudnorm undershoots by
      // a little over a decibel here, and -14 is what YouTube normalises
      // to: it turns loud uploads down and leaves quiet ones alone, so a
      // -16 master just plays quieter than everything around it.
      // Single-pass loudnorm lands about two decibels under whatever it is
      // asked for in this chain, so the last move is a measured trim rather
      // than a target. -14 LUFS is what YouTube normalises to: it turns
      // loud uploads down and leaves quiet ones alone, so a -16 master
      // simply plays quieter than everything around it. True peak sits at
      // -4.2 before the trim, so there is room for it.
      `[sum]alimiter=limit=0.92:attack=5:release=60,loudnorm=I=-13:TP=-1.5:LRA=10,` +
      `volume=1.9dB[out]`,
    "-map", "[out]", "-t", String(RUNTIME), "-ar", String(SR), "-ac", "2",
    path.join(WORK, "mix.wav"),
  ]);
}

function mux() {
  run([
    "-i", PICTURE,
    "-i", path.join(WORK, "mix.wav"),
    "-map", "0:v:0", "-map", "1:a:0",
    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
    OUT,
  ]);
}

// --------------------------------------------------------------------- main

fs.mkdirSync(WORK, { recursive: true });
const voiceOnly = process.argv.includes("--vo");

const clips = cutVoice();
buildVoice(clips);

if (!voiceOnly) {
  const els = makeElements();
  buildEffects(els);
  mix();
  mux();
  const mb = (fs.statSync(OUT).size / 1e6).toFixed(1);
  console.log(`\n${path.basename(OUT)}  ${mb}MB`);
} else {
  console.log(`\nvoice only: ${path.join(WORK, "voice.wav")}`);
}
