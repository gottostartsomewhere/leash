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

// Full bleed, given the 0.94 inset the app frames sit in (see INSET below,
// declared later because the filter helpers own it).
const FULL = 1.0638;

// Cuts only. Every framing holds dead still between them.
//
// A slow zoom across a static screenshot is the Ken Burns move, and on a UI
// it reads as a cheap commercial: the camera drifting while nothing in the
// picture moves. Software cuts instead, and lets the interface supply the
// motion. So there is no drift anywhere in here, only the moment of the cut.
const SEGMENTS = [
  // Open on the problem, then say what this is before showing any of it.
  // Cutting from a title card straight into a dense grid asks the viewer to
  // work out what they are looking at while it is already moving.
  { name: "problem", kind: "seq", seconds: 7 },
  { name: "lower", kind: "seq", seconds: 5 },
  { name: "premise", kind: "seq", seconds: 8 },

  // Slots now sit about two seconds past the footage, no more. A long held
  // tail is a freeze with a caption on it, and six seconds of that reads as
  // the video having stalled.
  { name: "mandate", kind: "seq", seconds: 13 },
  { name: "shop", kind: "seq", seconds: 21.5, callout: { at: 16.6 } },
  { name: "statement", kind: "seq", seconds: 4 },
  { name: "structuring", kind: "seq", seconds: 24, callout: { at: 19.0 } },
  { name: "payout", kind: "seq", seconds: 15 },
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
  { name: "revoke", kind: "seq", seconds: 16, callout: { at: 12.0 } },
  { name: "tally", kind: "seq", seconds: 9 },
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

/** One rendered overlay directory, if there is one. */
function layerDir(name) {
  const dir = p(HERE, "overlay", name);
  const meta = path.join(dir, "span.json");
  if (!fs.existsSync(meta)) return null;
  const span = JSON.parse(fs.readFileSync(meta, "utf-8"));
  return { dir, ...span, count: span.last - span.first + 1 };
}

/** Every overlay this segment carries, bottom to top.
 *
 *  Two kinds. A callout is a graphic that explains one moment, so it is
 *  anchored to that moment and holds to the end. A caption track names
 *  whatever the camera is looking at and runs the length of the segment, so
 *  it starts at zero. Both composite after the frames are scaled down,
 *  because they are authored at 1920x1080 and the source is 2x that. */
function layersFor(seg) {
  const out = [];

  const caption = layerDir(`caption-${seg.name}`);
  if (caption) out.push({ ...caption, start: 0 });

  const callout = layerDir(seg.name);
  if (callout) {
    const anchor = seg.callout?.at
      ? seg.callout.at
      : seg.callout
        ? markTime(seg.name, seg.callout.after) + (seg.callout.lead ?? 0.6)
        : callout.first / FPS;
    out.push({ ...callout, start: anchor });
  }
  return out;
}

/** Composite a segment's overlay layers onto an already-built clip.
 *
 *  The sequence path folds this into its own filter graph, but a segment
 *  cut from a screen recording arrives as finished video, so it gets the
 *  same treatment in a second pass. */
function withLayers(file, seg) {
  const layers = layersFor(seg);
  if (!layers.length) return { file, layers: 0 };

  const inputs = ["-i", file];
  const steps = [];
  layers.forEach((layer, i) => {
    inputs.push(
      "-framerate", String(FPS),
      "-start_number", String(layer.first),
      "-i", p(layer.dir, "%05d.png"),
    );
    const native = layer.count / FPS;
    const after = Math.max(0, seg.seconds - layer.start - native);
    steps.push(
      `[${i + 1}:v]format=rgba,` +
        (layer.start > 0.01
          ? `tpad=start_mode=add:start_duration=${layer.start.toFixed(2)}:color=black@0,`
          : "") +
        (after > 0.05
          ? `tpad=stop_mode=clone:stop_duration=${after.toFixed(2)},`
          : "") +
        `setsar=1[ov${i}]`,
    );
  });

  let prev = "0:v";
  layers.forEach((_, i) => {
    const label = i === layers.length - 1 ? "v" : `c${i}`;
    steps.push(`[${prev}][ov${i}]overlay=0:0:format=auto[${label}]`);
    prev = label;
  });

  const out = p(WORK, `${seg.name}-capped.mp4`);
  run([
    ...inputs,
    "-filter_complex", steps.join(";"),
    "-map", "[v]",
    "-t", String(seg.seconds),
    ...ENCODE,
    out,
  ]);
  return { file: out, layers: layers.length };
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

  const layers = layersFor(seg);
  if (!layers.length) {
    run([
      "-framerate", String(FPS),
      "-i", p(dir, "%05d.jpg"),
      "-vf", appHold + look,
      "-t", String(seg.seconds),
      ...ENCODE,
      out,
    ]);
    return { out, have, hold, layers: 0 };
  }

  const inputs = ["-framerate", String(FPS), "-i", p(dir, "%05d.jpg")];
  const steps = [];

  layers.forEach((layer, i) => {
    inputs.push(
      "-framerate", String(FPS),
      "-start_number", String(layer.first),
      "-i", p(layer.dir, "%05d.png"),
    );
    // Delay it to its own start, then clone the last frame so it holds
    // instead of vanishing once its own frames run out.
    const native = layer.count / FPS;
    const after = Math.max(0, seg.seconds - layer.start - native);
    steps.push(
      `[${i + 1}:v]format=rgba,` +
        (layer.start > 0.01
          ? `tpad=start_mode=add:start_duration=${layer.start.toFixed(2)}:color=black@0,`
          : "") +
        (after > 0.05
          ? `tpad=stop_mode=clone:stop_duration=${after.toFixed(2)},`
          : "") +
        `setsar=1[ov${i}]`,
    );
  });

  steps.push(`[0:v]${appHold}${look}[app]`);
  let prev = "app";
  layers.forEach((_, i) => {
    const label = i === layers.length - 1 ? "v" : `c${i}`;
    steps.push(`[${prev}][ov${i}]overlay=0:0:format=auto[${label}]`);
    prev = label;
  });

  run([
    ...inputs,
    "-filter_complex", steps.join(";"),
    "-map", "[v]",
    "-t", String(seg.seconds),
    ...ENCODE,
    out,
  ]);
  return { out, have, hold, layers: layers.length };
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
  const capped = withLayers(out, seg);
  return { out: capped.file, have: seg.seconds, hold: 0, layers: capped.layers };
}

/* -- go ----------------------------------------------------------------- */

fs.rmSync(WORK, { recursive: true, force: true });
fs.mkdirSync(WORK, { recursive: true });

console.log(`cutting at ${W}x${H} ${FPS}fps\n`);

const made = [];
let total = 0;
for (const seg of SEGMENTS) {
  const build = seg.kind === "still" ? still : seg.kind === "video" ? clip : sequence;
  const { out, have, hold, layers } = build(seg);
  made.push(out);
  total += seg.seconds;
  const note = hold > 0.05 ? `${have.toFixed(1)}s + ${hold.toFixed(1)}s held` : `${have.toFixed(1)}s`;
  const at = new Date(total * 1000).toISOString().substring(14, 19);
  console.log(`  ${seg.name.padEnd(12)} ${String(seg.seconds).padStart(3)}s  -> ${at}   ${note}${layers ? `  + ${layers} overlay${layers > 1 ? "s" : ""}` : ""}`);
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
