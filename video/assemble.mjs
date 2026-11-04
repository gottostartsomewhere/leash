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

// App shots are captured at 2x so push-ins stay sharp.
const SRC_W = W * 2;
const SRC_H = H * 2;

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
// A cut is two keyframes a frame apart; a push is two keyframes a beat
// apart. Each long shot is now a sequence of framings rather than one slow
// glide, because a glide across thirty seconds reads as a still that drifts.
const cut = (at, z, fx, fy) => [
  { at: at - 0.034, z: "PREV", fx: "PREV", fy: "PREV" },
  { at, z, fx, fy },
];

const SEGMENTS = [
  { name: "problem", kind: "seq", seconds: 7 },
  {
    name: "mandate",
    kind: "still",
    seconds: 13,
    camera: [
      { at: 0, z: 1.14, fx: 0.5, fy: 0.5 },
      { at: 2.2, z: 1.06, fx: 0.5, fy: 0.5 },
      ...cut(2.4, 2.3, 0.08, 0.2),
      { at: 4.4, z: 2.24, fx: 0.08, fy: 0.22 },
      ...cut(4.6, 2.1, 0.09, 0.52),
      { at: 7.6, z: 2.0, fx: 0.09, fy: 0.6 },
      ...cut(7.8, 2.4, 0.1, 0.86),
      { at: 9.6, z: 2.34, fx: 0.1, fy: 0.88 },
      ...cut(9.8, 1.04, 0.5, 0.5),
      { at: 13, z: 1.12, fx: 0.5, fy: 0.48 },
    ],
  },
  {
    name: "shop",
    kind: "seq",
    seconds: 25,
    callout: { at: 19.4 },
    camera: [
      { at: 0, z: 1.08, fx: 0.5, fy: 0.78 },   // typing
      { at: 2.6, z: 1.14, fx: 0.5, fy: 0.8 },
      ...cut(5.4, 1.75, 0.3, 0.92),            // the shelf of real products
      { at: 7.4, z: 1.68, fx: 0.45, fy: 0.92 },
      ...cut(7.6, 1.9, 0.72, 0.92),
      { at: 9.4, z: 1.84, fx: 0.76, fy: 0.92 },
      ...cut(9.6, 1.06, 0.5, 0.62),            // out while it thinks
      { at: 12.0, z: 1.12, fx: 0.5, fy: 0.6 },
      ...cut(12.2, 2.3, 0.5, 0.97),            // the trace
      { at: 14.2, z: 2.22, fx: 0.52, fy: 0.97 },
      ...cut(14.4, 2.5, 0.12, 0.96),           // REFUSED
      { at: 15.9, z: 2.44, fx: 0.14, fy: 0.96 },
      ...cut(16.1, 2.5, 0.12, 1.0),            // BOUGHT
      { at: 17.5, z: 2.44, fx: 0.14, fy: 1.0 },
      ...cut(17.7, 2.2, 0.62, 0.12),           // the grid rows
      { at: 19.1, z: 2.12, fx: 0.62, fy: 0.12 },
      ...cut(19.3, 1.02, 0.5, 0.5),
      { at: 25, z: 1.1, fx: 0.5, fy: 0.46 },
    ],
  },
  { name: "statement", kind: "seq", seconds: 4 },
  {
    name: "structuring",
    kind: "seq",
    seconds: 30,
    callout: { at: 20.6 },
    camera: [
      { at: 0, z: 1.06, fx: 0.5, fy: 0.42 },
      { at: 3.2, z: 1.12, fx: 0.5, fy: 0.42 },
      ...cut(3.6, 2.35, 0.56, 0.12),           // the two rows
      { at: 5.4, z: 2.28, fx: 0.58, fy: 0.12 },
      ...cut(5.6, 2.2, 0.4, 0.3),              // the cluster bars
      { at: 7.4, z: 2.1, fx: 0.42, fy: 0.31 },
      ...cut(7.6, 2.6, 0.5, 0.36),             // the cap line
      { at: 8.3, z: 2.54, fx: 0.52, fy: 0.36 },
      ...cut(8.5, 1.04, 0.5, 0.4),             // out for the filter
      { at: 11.0, z: 1.1, fx: 0.5, fy: 0.4 },
      ...cut(11.2, 2.3, 0.35, 0.47),           // the evidence numbers
      { at: 13.1, z: 2.22, fx: 0.37, fy: 0.47 },
      ...cut(13.3, 1.04, 0.5, 0.35),           // out for the search
      { at: 16.0, z: 1.1, fx: 0.5, fy: 0.35 },
      ...cut(16.2, 2.45, 0.76, 0.47),          // checks run
      { at: 18.0, z: 2.38, fx: 0.78, fy: 0.47 },
      ...cut(18.2, 2.2, 0.2, 0.2),             // the held gauge
      { at: 20.3, z: 2.12, fx: 0.2, fy: 0.22 },
      ...cut(20.5, 1.02, 0.5, 0.5),
      { at: 30, z: 1.12, fx: 0.5, fy: 0.54 },
    ],
  },
  {
    name: "payout",
    kind: "seq",
    seconds: 12,
    camera: [
      { at: 0, z: 1.9, fx: 0.16, fy: 0.14 },   // ticking them off
      { at: 3.2, z: 1.8, fx: 0.2, fy: 0.16 },
      ...cut(3.4, 2.4, 0.88, 0.14),            // the money column flashing
      { at: 5.6, z: 2.3, fx: 0.88, fy: 0.16 },
      ...cut(5.8, 2.2, 0.1, 0.2),              // the gauge
      { at: 8.0, z: 2.12, fx: 0.1, fy: 0.22 },
      ...cut(8.2, 1.04, 0.5, 0.4),
      { at: 12, z: 1.12, fx: 0.5, fy: 0.4 },
    ],
  },
  {
    name: "paypal",
    kind: "video",
    seconds: 11,
    src: `${DESKTOP}/Recording 2026-11-03 204231.mp4`,
    cuts: [
      { from: 3.4, length: 5 },
      { from: 14.8, length: 6 },
    ],
  },
  {
    name: "revoke",
    kind: "seq",
    seconds: 16,
    callout: { at: 11.6 },
    camera: [
      { at: 0, z: 1.06, fx: 0.5, fy: 0.3 },
      ...cut(0.6, 2.4, 0.92, 0.07),            // status flips
      { at: 2.4, z: 2.3, fx: 0.92, fy: 0.09 },
      ...cut(2.6, 2.3, 0.86, 0.18),            // holds released
      { at: 4.2, z: 2.22, fx: 0.86, fy: 0.2 },
      ...cut(4.5, 2.4, 0.5, 0.26),             // Mandate inactive
      { at: 6.4, z: 2.32, fx: 0.52, fy: 0.26 },
      ...cut(6.6, 1.06, 0.5, 0.36),            // out
      { at: 9.0, z: 1.12, fx: 0.5, fy: 0.36 },
      ...cut(9.2, 2.3, 0.5, 0.3),              // refused again
      { at: 11.4, z: 2.22, fx: 0.5, fy: 0.3 },
      ...cut(11.5, 1.02, 0.5, 0.42),           // wide for the stamp
      { at: 16, z: 1.1, fx: 0.5, fy: 0.42 },
    ],
  },
  { name: "tally", kind: "seq", seconds: 6 },
  { name: "closing", kind: "seq", seconds: 6 },
  { name: "endcard", kind: "seq", seconds: 5 },
];

// `cut` leaves PREV markers so a framing holds right up to the cut; resolve
// them against whatever the previous keyframe actually was.
for (const seg of SEGMENTS) {
  if (!seg.camera) continue;
  seg.camera.forEach((k, i) => {
    for (const key of ["z", "fx", "fy"]) {
      if (k[key] === "PREV") k[key] = seg.camera[i - 1][key];
    }
  });
}

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

/** Build a piecewise-linear ffmpeg expression over output frame number from
 *  keyframes [{at, v}], so the camera can actually move between positions
 *  rather than drift in one direction for the whole shot. */
function keyed(frames, fps = FPS) {
  if (frames.length === 1) return String(frames[0].v);
  let expr = String(frames[frames.length - 1].v);
  for (let i = frames.length - 2; i >= 0; i -= 1) {
    const a = frames[i];
    const b = frames[i + 1];
    const fa = Math.round(a.at * fps);
    const fb = Math.round(b.at * fps);
    const span = Math.max(1, fb - fa);
    // Smoothstep between the two, so a move eases in and out of its hold.
    const u = `clip((on-${fa})/${span},0,1)`;
    const s = `(${u}*${u}*(3-2*${u}))`;
    expr = `if(lt(on,${fb}), ${a.v}+(${b.v}-${a.v})*${s}, ${expr})`;
  }
  return expr;
}

/** A shot with real moves: a list of {at, z, fx, fy} the camera travels
 *  between. Beats the single slow drift, which on a 38 second slot is
 *  indistinguishable from a still. */
function cameraFilter(moves, inset = true) {
  const fit = inset
    ? `scale=${Math.round(SRC_W * INSET)}:${Math.round(SRC_H * INSET)},` +
      `pad=${SRC_W}:${SRC_H}:(ow-iw)/2:(oh-ih)/2:${GROUND}`
    : `scale=${SRC_W}:${SRC_H}`;
  const z = keyed(moves.map((m) => ({ at: m.at, v: m.z })));
  const x = keyed(moves.map((m) => ({ at: m.at, v: m.fx })));
  const y = keyed(moves.map((m) => ({ at: m.at, v: m.fy })));
  return [
    fit,
    `zoompan=z='${z}':x='(iw-iw/zoom)*(${x})':y='(ih-ih/zoom)*(${y})'` +
      `:d=1:s=${W}x${H}:fps=${FPS}`,
    "setsar=1",
  ].join(",");
}

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

/** When a labelled beat actually happened in a capture. */
function markTime(shot, label) {
  const file = path.join(REEL, shot, "marks.json");
  if (!fs.existsSync(file)) return 0;
  const { marks } = JSON.parse(fs.readFileSync(file, "utf-8"));
  return marks.find((m) => m.label === label)?.t ?? 0;
}

/** The callout layer for a segment, if overlay.mjs rendered one. */
function overlayFor(name) {
  const dir = p(HERE, "overlay", name);
  const meta = path.join(dir, "span.json");
  if (!fs.existsSync(meta)) return null;
  const span = JSON.parse(fs.readFileSync(meta, "utf-8"));
  return { dir, ...span, count: span.last - span.first + 1 };
}

function sequence(seg) {
  const dir = p(REEL, seg.name);
  const frames = fs.readdirSync(dir).filter((f) => f.endsWith(".jpg")).length;
  if (!frames) throw new Error(`${seg.name}: no frames, run reel.mjs`);
  const have = frames / FPS;
  const hold = Math.max(0, seg.seconds - have);
  const out = p(WORK, `${seg.name}.mp4`);
  const look = seg.camera
    ? cameraFilter(seg.camera)
    : pushFilter(seg.push, seg.seconds, Boolean(seg.push));
  const appHold =
    hold > 0.05 ? `tpad=stop_mode=clone:stop_duration=${hold.toFixed(2)},` : "";

  const callout = overlayFor(seg.name);
  if (!callout) {
    run([
      "-framerate", String(FPS),
      "-i", p(dir, "%05d.jpg"),
      "-vf", appHold + look,
      "-t", String(seg.seconds),
      ...ENCODE,
      out,
    ]);
    return { out, have, hold, callout: false };
  }

  // The callout is composited onto the raw frames *before* the push, so it
  // travels with the shot. It fades in at its own time and then holds for
  // the rest of the segment.
  // An absolute time when the camera tours first, otherwise anchored to the
  // beat the recorder marked.
  const anchor = seg.callout?.at
    ? seg.callout.at
    : seg.callout
      ? markTime(seg.name, seg.callout.after) + (seg.callout.lead ?? 0.6)
      : callout.first / FPS;
  const start = anchor.toFixed(2);
  const native = callout.count / FPS;
  const after = Math.max(0, seg.seconds - anchor - native);

  const chain =
    `[1:v]format=rgba,` +
    `tpad=start_mode=add:start_duration=${start}:color=black@0,` +
    (after > 0.05 ? `tpad=stop_mode=clone:stop_duration=${after.toFixed(2)},` : "") +
    `setsar=1[ov];` +
    `[0:v]${appHold}${look}[app];` +
    `[app][ov]overlay=0:0:format=auto[v]`;

  run([
    "-framerate", String(FPS),
    "-i", p(dir, "%05d.jpg"),
    "-framerate", String(FPS),
    "-start_number", String(callout.first),
    "-i", p(callout.dir, "%05d.png"),
    "-filter_complex", chain,
    "-map", "[v]",
    "-t", String(seg.seconds),
    ...ENCODE,
    out,
  ]);
  return { out, have, hold, callout: true };
}

function still(seg) {
  const file = p(REEL, seg.name, "still.png");
  const out = p(WORK, `${seg.name}.mp4`);
  run([
    "-loop", "1",
    "-framerate", String(FPS),
    "-i", file,
    "-vf", seg.camera ? cameraFilter(seg.camera) : pushFilter(seg.push, seg.seconds, Boolean(seg.push)),
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
  const { out, have, hold, callout } = build(seg);
  made.push(out);
  total += seg.seconds;
  const note = hold > 0.05 ? `${have.toFixed(1)}s + ${hold.toFixed(1)}s held` : `${have.toFixed(1)}s`;
  const at = new Date(total * 1000).toISOString().substring(14, 19);
  console.log(`  ${seg.name.padEnd(12)} ${String(seg.seconds).padStart(3)}s  -> ${at}   ${note}${callout ? "  + callout" : ""}`);
}

// Hard cuts everywhere read as a slideshow. A short dip through the ground
// colour gives each section a beat to land on, and costs a third of a second.
const DIP = 0.34;

function stitch(clips) {
  const inputs = clips.flatMap((f) => ["-i", f]);
  const steps = [];
  let prev = "0:v";
  for (let i = 1; i < clips.length; i += 1) {
    const at = SEGMENTS.slice(0, i).reduce((n, s) => n + s.seconds, 0) - DIP * i;
    const label = i === clips.length - 1 ? "v" : `x${i}`;
    steps.push(
      `[${prev}][${i}:v]xfade=transition=fade:duration=${DIP}:offset=${at.toFixed(3)}[${label}]`,
    );
    prev = label;
  }
  const out = p(WORK, "stitched.mp4");
  run([
    ...inputs,
    "-filter_complex", steps.join(";"),
    "-map", "[v]",
    ...ENCODE,
    out,
  ]);
  return out;
}

console.log("\nstitching with dips...");
const stitched = stitch(made);

const list = p(WORK, "all.txt");
fs.writeFileSync(list, [`file '${stitched}'`].join("\n"));

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
