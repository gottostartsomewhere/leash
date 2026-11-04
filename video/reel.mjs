// Turns recorded frames into constant-rate sequences an editor can import.
//
//   node video/reel.mjs           all shots at 30fps
//   node video/reel.mjs --fps 60
//   node video/reel.mjs shop
//
// The screencast only paints when something changes, so a six second hold
// might be two frames and a button press might be forty. Dropped straight
// into an editor as an image sequence, that plays at wildly the wrong speed.
//
// This resamples against the manifest timestamps: every output frame is the
// last real frame painted at that moment. Holds become repeated frames,
// motion keeps every frame it had, and the clip runs at exactly the length
// it was recorded at.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRAMES = path.join(HERE, "frames");
const REEL = path.join(HERE, "reel");

const argv = process.argv.slice(2);
const fpsAt = argv.indexOf("--fps");
const FPS = fpsAt === -1 ? 30 : Number(argv[fpsAt + 1]);
const only = argv.filter((a, i) => !a.startsWith("--") && i !== fpsAt + 1);

if (!Number.isFinite(FPS) || FPS <= 0) {
  console.error("--fps needs a positive number");
  process.exit(1);
}

if (!fs.existsSync(FRAMES)) {
  console.error(`No frames yet. Run: node video/record.mjs`);
  process.exit(1);
}

fs.mkdirSync(REEL, { recursive: true });

const shots = fs
  .readdirSync(FRAMES)
  .filter((name) => fs.existsSync(path.join(FRAMES, name, "manifest.json")))
  .filter((name) => only.length === 0 || only.includes(name));

const stills = fs
  .readdirSync(FRAMES)
  .filter((name) => fs.existsSync(path.join(FRAMES, name, "still.png")))
  .filter((name) => only.length === 0 || only.includes(name));

console.log(`${FPS}fps\n`);

for (const shot of shots) {
  const src = path.join(FRAMES, shot);
  const manifest = JSON.parse(
    fs.readFileSync(path.join(src, "manifest.json"), "utf-8"),
  );
  const frames = manifest.frames;
  if (!frames.length) {
    console.log(`  ${shot.padEnd(14)} no frames, skipped`);
    continue;
  }

  const out = path.join(REEL, shot);
  fs.rmSync(out, { recursive: true, force: true });
  fs.mkdirSync(out, { recursive: true });

  // Zero on the frame where the action started, not on the first frame
  // captured: everything before that is screencast pre-roll.
  const begin = Math.min(manifest.startIndex ?? 0, frames.length - 1);
  const zero = frames[begin].ts;
  const span = manifest.t1 - manifest.t0;
  const total = Math.max(1, Math.round(span * FPS));

  let cursor = begin;
  let copied = 0;
  for (let n = 0; n < total; n += 1) {
    const at = n / FPS;
    while (cursor + 1 < frames.length && frames[cursor + 1].ts - zero <= at) {
      cursor += 1;
    }
    fs.copyFileSync(
      path.join(src, frames[cursor].file),
      path.join(out, `${String(n).padStart(5, "0")}.jpg`),
    );
    copied += 1;
  }

  // Marks in frame numbers, which is what an editor actually needs.
  const marks = manifest.marks.map((m) => ({
    ...m,
    frame: Math.round(m.t * FPS),
  }));
  fs.writeFileSync(
    path.join(out, "marks.json"),
    JSON.stringify({ shot, fps: FPS, frames: copied, seconds: span, marks }, null, 1),
  );

  const where = marks.map((m) => `${m.label}@${m.frame}`).join(" ");
  console.log(
    `  ${shot.padEnd(14)} ${String(copied).padStart(4)} frames  ${span.toFixed(1)}s` +
      (where ? `  ${where}` : ""),
  );
}

for (const shot of stills) {
  const out = path.join(REEL, shot);
  fs.mkdirSync(out, { recursive: true });
  fs.copyFileSync(
    path.join(FRAMES, shot, "still.png"),
    path.join(out, "still.png"),
  );
  console.log(`  ${shot.padEnd(14)} still.png`);
}

console.log(`\nreel in ${REEL}`);
console.log("Import each folder as an image sequence at " + FPS + "fps.");
