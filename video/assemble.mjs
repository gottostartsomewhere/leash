// Cuts the recorded shots into the finished trailer. Picture only, so a
// voiceover can be laid straight on top.
//
//   node video/record.mjs      capture the shots
//   node video/reel.mjs        resample to 30fps
//   node video/assemble.mjs    cut it together
//
// Segment lengths come from video/script.md, so the picture is already
// paced to the narration rather than needing to be stretched later. Where a
// shot is shorter than its slot, the last frame holds and a slow push keeps
// it alive, which is what an editor would do by hand anyway.

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ffmpeg from "ffmpeg-static";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REEL = path.join(HERE, "reel");
const WORK = path.join(HERE, "work");
const OUT = path.join(HERE, "leash-trailer.mp4");
const DESKTOP = "C:/Users/johnk/Desktop";

const FPS = 30;
const W = 1920;
const H = 1080;

const p = (...bits) => path.join(...bits).replace(/\\/g, "/");

/** A slow push, so a held frame never reads as a freeze. `to` is the zoom at
 *  the end; fx/fy are where it pushes towards, 0..1 of the frame.
 *
 *  Kept small on purpose. Anything past about 1.06 starts cutting the rail
 *  mid-word and clipping the buttons along the bottom, which reads as a
 *  broken crop rather than a camera move. The job here is to stop a held
 *  frame looking frozen, not to reframe the shot. */
const push = (to = 1.05, fx = 0.5, fy = 0.5) => ({ to, fx, fy });

// Lengths from script.md. Total lands just under three minutes, which is
// where judges stop being required to watch.
const SEGMENTS = [
  { name: "problem", kind: "seq", seconds: 18 },
  { name: "mandate", kind: "still", seconds: 20, push: push(1.05, 0.18, 0.42) },
  { name: "shop", kind: "seq", seconds: 30, push: push(1.05, 0.5, 0.68) },
  { name: "statement", kind: "seq", seconds: 4 },
  { name: "structuring", kind: "seq", seconds: 38, push: push(1.06, 0.46, 0.34) },
  { name: "payout", kind: "seq", seconds: 12, push: push(1.04, 0.55, 0.28) },
  {
    name: "paypal",
    kind: "video",
    seconds: 12,
    src: `${DESKTOP}/Recording 2026-11-03 204231.mp4`,
    // Two looks: the balance, then the money arriving.
    cuts: [
      { from: 3.2, length: 6 },
      { from: 14.5, length: 6 },
    ],
  },
  { name: "revoke", kind: "seq", seconds: 16, push: push(1.05, 0.5, 0.3) },
  { name: "tally", kind: "seq", seconds: 7 },
  { name: "closing", kind: "seq", seconds: 8 },
  { name: "endcard", kind: "seq", seconds: 6 },
];

function run(args) {
  execFileSync(ffmpeg, ["-hide_banner", "-loglevel", "error", "-y", ...args], {
    stdio: ["ignore", "ignore", "pipe"],
  });
}

/** zoompan drifts if you let it compute from the frame counter, so the zoom
 *  is driven off elapsed time and clamped at the end value. */
//: The app's own background, so the inset below is invisible as a border.
const GROUND = "0x0b0a09";

//: How far the app sits inside the frame before the push starts. Zooming a
//: full-bleed screenshot always eats the edges, and on this UI that means
//: clipping the rail labels and the buttons along the bottom. Insetting
//: first means the push *ends* exactly full-bleed and nothing is ever cut.
const INSET = 0.94;

function pushFilter(cfg, seconds, inset = false) {
  const fit = inset
    ? `scale=${Math.round(W * INSET)}:${Math.round(H * INSET)},` +
      `pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2:${GROUND}`
    : `scale=${W}:${H}`;

  if (!cfg) return `${fit},setsar=1`;

  // End exactly at full bleed when inset, so the move resolves rather than
  // stopping somewhere arbitrary.
  const to = inset ? 1 / INSET : cfg.to;
  const { fx, fy } = cfg;
  const step = ((to - 1) / (seconds * FPS)).toFixed(7);
  return [
    fit,
    `scale=${W * 2}:${H * 2}`,
    `zoompan=z='min(1+${step}*on,${to})'` +
      `:x='(iw-iw/zoom)*${fx}':y='(ih-ih/zoom)*${fy}'` +
      `:d=1:s=${W}x${H}:fps=${FPS}`,
    "setsar=1",
  ].join(",");
}

const ENCODE = [
  "-c:v", "libx264",
  "-preset", "medium",
  "-crf", "18",
  "-pix_fmt", "yuv420p",
  "-r", String(FPS),
];

function sequence(seg) {
  const dir = p(REEL, seg.name);
  const frames = fs.readdirSync(dir).filter((f) => f.endsWith(".jpg")).length;
  if (!frames) throw new Error(`${seg.name}: no frames, run reel.mjs`);
  const have = frames / FPS;
  const hold = Math.max(0, seg.seconds - have);
  const out = p(WORK, `${seg.name}.mp4`);

  const filters = [];
  if (hold > 0.05) filters.push(`tpad=stop_mode=clone:stop_duration=${hold.toFixed(2)}`);
  filters.push(pushFilter(seg.push, seg.seconds, Boolean(seg.push)));

  run([
    "-framerate", String(FPS),
    "-i", p(dir, "%05d.jpg"),
    "-vf", filters.join(","),
    "-t", String(seg.seconds),
    ...ENCODE,
    out,
  ]);
  return { out, have, hold };
}

function still(seg) {
  const file = p(REEL, seg.name, "still.png");
  const out = p(WORK, `${seg.name}.mp4`);
  run([
    "-loop", "1",
    "-framerate", String(FPS),
    "-i", file,
    "-vf", pushFilter(seg.push, seg.seconds, Boolean(seg.push)),
    "-t", String(seg.seconds),
    ...ENCODE,
    out,
  ]);
  return { out, have: 0, hold: seg.seconds };
}

/** The screen recording is 1918x868, which is not 16:9. Filling the frame
 *  height and cropping the right-hand side loses nothing: the balance and
 *  the activity list both sit left of centre. */
function clip(seg) {
  const parts = [];
  seg.cuts.forEach((cut, i) => {
    const out = p(WORK, `${seg.name}-${i}.mp4`);
    run([
      "-ss", String(cut.from),
      "-t", String(cut.length),
      "-i", seg.src,
      "-vf",
      `scale=-2:${H},crop=${W}:${H}:(iw-${W})/3:0,setsar=1,fps=${FPS}`,
      ...ENCODE,
      out,
    ]);
    parts.push(out);
  });

  const out = p(WORK, `${seg.name}.mp4`);
  const list = p(WORK, `${seg.name}.txt`);
  fs.writeFileSync(list, parts.map((f) => `file '${f}'`).join("\n"));
  run(["-f", "concat", "-safe", "0", "-i", list, "-c", "copy", out]);
  return { out, have: seg.seconds, hold: 0 };
}

/* -- go ----------------------------------------------------------------- */

fs.rmSync(WORK, { recursive: true, force: true });
fs.mkdirSync(WORK, { recursive: true });

console.log(`cutting at ${W}x${H} ${FPS}fps\n`);

const made = [];
let total = 0;
for (const seg of SEGMENTS) {
  const build = seg.kind === "still" ? still : seg.kind === "video" ? clip : sequence;
  const { out, have, hold } = build(seg);
  made.push(out);
  total += seg.seconds;
  const note = hold > 0.05 ? `${have.toFixed(1)}s + ${hold.toFixed(1)}s held` : `${have.toFixed(1)}s`;
  const at = new Date(total * 1000).toISOString().substring(14, 19);
  console.log(`  ${seg.name.padEnd(12)} ${String(seg.seconds).padStart(3)}s  -> ${at}   ${note}`);
}

const list = p(WORK, "all.txt");
fs.writeFileSync(list, made.map((f) => `file '${f}'`).join("\n"));

// A silent stereo track, so the file is well formed for anything that
// expects audio when the voiceover is laid on.
run([
  "-f", "concat", "-safe", "0", "-i", list,
  "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
  "-c:v", "copy",
  "-c:a", "aac", "-b:a", "128k",
  "-shortest",
  "-movflags", "+faststart",
  p(OUT),
]);

const mb = (fs.statSync(OUT).size / 1024 / 1024).toFixed(1);
const mins = Math.floor(total / 60);
console.log(
  `\n${path.basename(OUT)}  ${mins}:${String(total % 60).padStart(2, "0")}  ${mb}MB`,
);
console.log(OUT);
