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

import { execFileSync, spawnSync } from "node:child_process";
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

/** Run ffmpeg for what it prints rather than for what it writes.
 *
 *  spawnSync, not execFileSync: ffmpeg's filters report on stderr and
 *  execFileSync hands back stdout, so this read as a file with no silence
 *  in it at all and every cut quietly fell back to blind padding. */
function capture(args) {
  const r = spawnSync(ffmpeg, ["-hide_banner", "-y", ...args], {
    encoding: "utf-8",
    maxBuffer: 1 << 26,
  });
  return `${r.stdout ?? ""}\n${r.stderr ?? ""}`;
}

/** Every stretch of real silence in the take.
 *
 *  The browser recorder gated this take hard, which is why its noise floor
 *  is 36dB under the other one, and it means there is true silence between
 *  almost every word. That is a gift for cutting: a boundary placed inside
 *  one of these can neither clip the word before it nor let the word after
 *  it bleed in, because there is nothing there to bleed. */
function silences() {
  // -45dB and 30ms, not -50 and 100ms.
  //
  // At the coarse setting six of the twenty one boundaries had no silence
  // within reach at all, because he ran those sentences together without
  // pausing, and each of them fell back to blind padding and took the
  // first syllable of the next line with it. Those are exactly the cuts
  // that sounded wrong. A 30ms dip is not a pause but it is somewhere to
  // put a boundary, and `snap` still prefers the longest silence it can
  // find, so a real sentence break wins wherever there is one.
  const out = capture([
    "-i", SRC, "-af", "silencedetect=noise=-45dB:d=0.03", "-f", "null", "-",
  ]);
  const spans = [];
  let start = null;
  for (const line of out.split(/\r?\n/)) {
    const a = /silence_start:\s*([\d.]+)/.exec(line);
    const b = /silence_end:\s*([\d.]+)/.exec(line);
    if (a) start = Number(a[1]);
    if (b && start !== null) {
      spans.push({ start, end: Number(b[1]) });
      start = null;
    }
  }
  return spans;
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
  // Keeps the "This is" he added in front of "refused".
  //
  // Cutting it off meant starting the clip inside a word: he runs "make.
  // This is refused" together with no pause anywhere in it, so there was
  // no silence to put a boundary in and the cut landed mid-syllable. It
  // came back from the check transcript as "is ruffed". There is a real
  // pause before "This", the sentence is no worse for carrying it, and a
  // clean cut beats a tidier script.
  { name: "refusal", words: [139, 153], at: 79.4 },
  { name: "structuring", words: [154, 161], at: 85.2 },
  { name: "split", words: [162, 179], at: 88.8 },
  { name: "addresses", words: [180, 191], at: 95.6 },
  { name: "catch", words: [192, 199], at: 101.9 },
  { name: "money", words: [200, 216], at: 108.2 },
  { name: "books", words: [217, 222], at: 121.0 },
  { name: "revoke", words: [223, 235], at: 129.6 },
  { name: "meaning", words: [236, 254], at: 136.4 },
  { name: "redteam", words: [255, 263], at: 145.3 },
  // Hard on the heels of the red team line, by request, and he is
  // right: "two red teams, one of them a model" and the count are one
  // sentence with a comma in it, and a second of air between them made
  // the number sound like a new topic. 147.9 puts 0.07s between the
  // last word of one and the first of the next, which is a breath
  // rather than a pause. It also fixes the sync: the tally card is
  // gone at 2:32 and the old placement ran the count past it.
  { name: "numbers", words: [264, 267], at: 147.9 },
  // The closing couplet, as one clip, and still stopping before the "thank
  // you" that is not in the script and not in the cut.
  //
  // "...what their agent can buy. This one shows you what it cannot." runs
  // continuously with no pause between the halves, so splitting them meant
  // cutting inside "This", and the word simply vanished: the check
  // transcript heard "buy. one shows you what it cannot." It is one
  // thought and he delivered it as one, so it is one clip now. Placed so
  // the turn lands as the end card arrives, which is where it belongs.
  // 151.75 so the first word lands exactly on 2:32, which is where the
  // closing card arrives: the clip carries a quarter second of silence
  // in front of "Every", so the placement sits that much earlier than
  // the time you hear.
  { name: "close", words: [268, 284], at: 151.75 },
];

// How much silence to keep either side of a line, at most. Taken out of a
// real silence rather than added blindly: a fixed tail on a continuous read
// reaches into the next word, which is why the first mix had the next line
// bleeding faintly into the end of the one before it.
const LEAD = 0.25;
const TAIL = 0.34;

/** Put a cut inside the silence next to a word, never next to the word.
 *
 *  `dir` -1 looks backwards from the start of a line, +1 forwards from its
 *  end. Takes at most 70% of whatever silence it finds, so the boundary
 *  always has real silence on both sides of it even if Whisper's idea of
 *  where the word begins is off by a tenth of a second. */
/** Distance from an instant to a silence, counting nought if it is inside. */
function reach(t, g) {
  if (t >= g.start && t <= g.end) return 0;
  return Math.min(Math.abs(g.start - t), Math.abs(g.end - t));
}

function snap(t, dir, gaps, limit) {
  // Gaps that CONTAIN the timestamp, not just gaps that start near it.
  //
  // Whisper pads each word's end out to wherever the next word begins, so
  // the end of a line is reported in the middle of the pause after it
  // rather than at the sound: "fast." is marked ending at 21.14 when the
  // audio stops at 19.81 and the silence runs 19.81 to 21.19. Measuring
  // from the gap's start put that silence 1.33s away and out of range, so
  // four boundaries found nothing and fell back to blind padding, which is
  // precisely where the next line was bleeding in.
  const near = gaps.filter((g) => reach(t, g) <= 0.7);
  if (!near.length) return { cut: t + dir * limit * 0.5, gap: null };
  // The longest one within reach. A sentence break is a longer silence than
  // the gaps between words inside it, so length is what tells them apart.
  const best = near.reduce((a, b) =>
    b.end - b.start > a.end - a.start ? b : a,
  );
  const room = Math.min(limit, (best.end - best.start) * 0.7);
  return { cut: dir < 0 ? best.end - room : best.start + room, gap: best };
}

function cutVoice() {
  const words = JSON.parse(fs.readFileSync(TAKE, "utf-8")).words;
  const gaps = silences();
  const clips = [];

  console.log(`voice   ${gaps.length} silences found\n`);
  for (const [i, line] of LINES.entries()) {
    const [a, b] = line.words;
    const head = snap(words[a].start, -1, gaps, LEAD);
    const foot = snap(words[b].end, +1, gaps, TAIL);
    const from = Math.max(0, head.cut);
    const to = foot.cut;
    const dur = to - from;

    // Fade across the silence that was kept, not across the word. 25ms was
    // enough to stop a click and not nearly enough to stop the edit sounding
    // like one: the gate drops the floor to nothing between lines, so a
    // short fade is the noise floor itself appearing and vanishing. A long
    // one over silence is inaudible, and the line then starts on its own
    // onset instead of partway up a ramp.
    // Measured off the silence, not off Whisper's word times, which are
    // padded and routinely put the "end" of a line a second after the
    // sound stopped. The fade in finishes as the speech starts; the fade
    // out begins the instant it stops.
    const quietIn = head.gap ? head.gap.end - from : 0.03;
    const quietOut = foot.gap ? to - foot.gap.start : 0.03;
    const lead = Math.max(0.02, Math.min(quietIn, 0.14));
    const tail = Math.max(0.03, Math.min(quietOut, 0.26));

    const file = path.join(WORK, `vo-${String(i).padStart(2, "0")}-${line.name}.wav`);
    run([
      "-ss", from.toFixed(3), "-t", dur.toFixed(3), "-i", SRC,
      "-ar", String(SR), "-ac", "1",
      "-af",
      `afade=t=in:st=0:d=${lead.toFixed(3)}:curve=qsin,` +
        `afade=t=out:st=${(dur - tail).toFixed(3)}:d=${tail.toFixed(3)}:curve=qsin`,
      file,
    ]);
    clips.push({ ...line, file, dur, lead, tail, quietIn, quietOut, head, foot });
  }

  // Reported as the gap between the last word of one line and the first
  // word of the next, not as the gap between the clips.
  //
  // Clips are allowed to overlap, and one pair deliberately does: each
  // carries a quarter second of silence at the head and a third at the
  // tail, so two clips can sit over each other by half a second with
  // nothing but room tone in the overlap. Measuring clip against clip
  // called that an overrun when the words were still 70ms apart.
  for (const [i, c] of clips.entries()) {
    const n = clips[i + 1];
    // quietIn/quietOut, not lead/tail: those two are the fade lengths and
    // are capped well below the silence they run over, so using them put
    // the first word a tenth of a second earlier than it really is.
    const speechEnds = c.at + c.dur - c.quietOut;
    const nextBegins = n ? n.at + n.quietIn : RUNTIME;
    const gap = nextBegins - speechEnds;
    const bad =
      gap < 0
        ? "  WORDS COLLIDE"
        : !c.head.gap || !c.foot.gap
          ? "  NO SILENCE, padded blindly"
          : "";
    console.log(
      `  ${c.name.padEnd(12)} ${fmt(c.at)}  ${c.dur.toFixed(2)}s` +
        `  gap to next ${gap.toFixed(2)}` +
        `  quiet ${c.quietIn.toFixed(2)}/${c.quietOut.toFixed(2)}${bad}`,
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

/** One synthesised element, rendered once and placed many times.
 *
 *  `source` is a complete lavfi source including its own duration, because
 *  the oscillator and the noise generator spell their arguments
 *  differently. `chain` is an optional filter pass over it. */
function element(name, source, chain) {
  const file = path.join(WORK, `sfx-${name}.wav`);
  const args = ["-f", "lavfi", "-i", source];
  if (chain) args.push("-af", chain);
  args.push("-ar", String(SR), "-ac", "1", file);
  run(args);
  return file;
}

function makeElements() {
  const out = {};

  // A hit. Two sines an octave apart with a fast exponential decay, which is
  // a drum rather than a beep because the decay is what the ear reads.
  out.impact = element(
    "impact",
    `aevalsrc='(0.9*sin(2*PI*52*t)+0.35*sin(2*PI*104*t))*exp(-4.5*t)':d=1.4:s=${SR}`,
  );

  // The same thing an octave down and slower, for the two cuts that are
  // supposed to land like a door closing.
  out.sub = element(
    "sub",
    `aevalsrc='(0.95*sin(2*PI*38*t)+0.25*sin(2*PI*76*t))*exp(-2.2*t)':d=2.2:s=${SR}`,
  );

  // A riser, made of air rather than of pitch.
  //
  // The first one swept a sine from 180Hz to 3kHz, which is the textbook
  // way to build a whistle: one moving partial with nothing around it, so
  // the ear locks onto it as a note and follows it all the way up. Six of
  // those in two and a half minutes is somebody whistling at you.
  // Band-limited noise has no partial to follow, so a rising envelope on
  // it reads as something approaching instead of something singing. The
  // band is deliberately narrow at the top: above about 7kHz it starts to
  // hiss, and the whole point is that it should not draw attention.
  out.riser = element(
    "riser",
    `anoisesrc=c=white:a=0.9:d=1.1:r=${SR}`,
    "highpass=f=620,lowpass=f=6800," +
      "volume='pow(min(t/1.0,1),2.6)':eval=frame," +
      "afade=t=out:st=0.92:d=0.18",
  );

  // A tick. The checks firing, and the smallest thing in the mix. A pitch
  // is fine here because it lasts 16ms: too short to be heard as a note.
  out.tick = element(
    "tick",
    `aevalsrc='0.6*sin(2*PI*2100*t)*exp(-60*t)':d=0.09:s=${SR}`,
  );

  // A soft mark, for a camera landing. Rounder than the tick and lower.
  out.land = element(
    "land",
    `aevalsrc='0.5*sin(2*PI*520*t)*exp(-11*t)':d=0.5:s=${SR}`,
  );

  return out;
}

// Where each one goes, in finished-timeline seconds. The picture's own
// boundaries, taken from assemble.mjs after the crossfades: a riser leads
// into a cut, the hit lands on it.
const HITS = [
  // the problem card, and the wordmark it resolves into
  { el: "riser", at: 5.5, gain: 0.36 },
  { el: "impact", at: 6.6, gain: 0.8 },
  // into the animation
  { el: "riser", at: 10.1, gain: 0.32 },
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
  { el: "riser", at: 46.8, gain: 0.44 },
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
  { el: "riser", at: 81.4, gain: 0.44 },
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
  { el: "riser", at: 128.2, gain: 0.40 },
  { el: "sub", at: 129.3, gain: 1.0 },
  { el: "land", at: 134.0, gain: 0.4 },
  // the tally counting up
  { el: "riser", at: 142.9, gain: 0.36 },
  { el: "impact", at: 144.0, gain: 0.7 },
  // the close
  { el: "impact", at: 151.6, gain: 0.65 },
  { el: "sub", at: 157.2, gain: 0.85 },
];

function buildEffects(els) {
  const names = [...new Set(HITS.map((h) => h.el))];
  const inputs = names.flatMap((n) => ["-i", els[n]]);


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
      `${mix}amix=inputs=${HITS.length}:normalize=0:dropout_transition=0[out]`,
    "-map", "[out]", "-t", String(RUNTIME), "-ar", String(SR), "-ac", "1",
    path.join(WORK, "effects.wav"),
  ]);

  // Room, as its own track, because it must not duck.
  //
  // The take was gated, so between lines there is not a quiet room, there
  // is nothing at all. That is what makes an entry sound like a switch
  // being thrown rather than someone starting to speak. A continuous bed
  // under the whole thing gives the ear something that does not stop, and
  // it has to be continuous: ducked with the hits it disappears under
  // every line and reappears after it, which is the same fault again,
  // slower. Brown noise with everything above 120Hz taken off, low enough
  // to be felt rather than heard, with its own ends faded so the file does
  // not start and finish on a step.
  run([
    "-f", "lavfi", "-i", `anoisesrc=c=brown:a=0.9:d=${RUNTIME}:r=${SR}`,
    "-af",
      `lowpass=f=120,volume=0.085,` +
      `afade=t=in:st=0:d=1.2,afade=t=out:st=${RUNTIME - 2.5}:d=2.5`,
    "-ar", String(SR), "-ac", "1", path.join(WORK, "room.wav"),
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
    "-i", path.join(WORK, "room.wav"),
    "-filter_complex",
      `[0:a]asplit=2[vo][key];` +
      `[1:a][key]sidechaincompress=threshold=0.05:ratio=6:attack=12:release=420[ducked];` +
      // Room goes in flat. It is the one thing in the mix that must not
      // move, because the whole point of it is that it never stops.
      `[vo][ducked][2:a]amix=inputs=3:normalize=0:weights=1 0.62 1[sum];` +
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
