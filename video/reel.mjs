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
// The value after --fps is not a shot name. Without --fps, fpsAt + 1 is 0,
// which used to throw away whichever shot was named first.
const only = argv.filter((a, i) => !a.startsWith("--") && (fpsAt === -1 || i !== fpsAt + 1));

if (!Number.isFinite(FPS) || FPS <= 0) {
  console.error("--fps needs a positive number");
  process.exit(1);
}

if (!fs.existsSync(FRAMES)) {
  console.error(`No frames yet. Run: node video/record.mjs`);
  process.exit(1);
}

fs.mkdirSync(REEL, { recursive: true });

/** Stretches of a take to keep, in recorded seconds. Everything else is
 *  dead air: an outside agent connecting over the network, or a camera
 *  move onto something the cut no longer needs. Each cut sits where the
 *  camera is parked and the screen is still, so the join cannot be seen.
 *  Marks are moved with the picture, and a mark inside a removed stretch
 *  is dropped, so captions anchored to it are dropped too, loudly. */
const KEEP = {
  // 4.6 to 9.8 is the agent connecting and searching the live catalogue.
  // Its first move lands at 9.8 and the other three at 13.8, on the
  // screen's next poll, with nothing changing in between or after until
  // the push at 16.8. After 20.4 is a push this cut omits.
  mcp: [[0, 4.6], [9.8, 11.4], [13.5, 15.0], [16.6, 20.4]],
  // 7.4 to 10.8 is a push onto one product card; the shelf already shows it.
  shop: [[0, 7.4], [10.8, Infinity]],
};

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

  // Zero on the clock the marks were written against, not on the first
  // frame that happened to paint after recording began.
  //
  // The screencast only paints when something changes, so a shot that
  // opens on a held still paints nothing until it moves. Zeroing there
  // treats that first move as time zero and shifts the entire shot
  // earlier, pulling every mark out of sync with the picture: the mandate
  // shot opens on a 1.4s hold and was running 1.45s adrift, so its
  // captions landed well after the camera they describe.
  const zero = manifest.t0;
  const recorded = manifest.t1 - manifest.t0;
  const keep = (KEEP[shot] ?? [[0, Infinity]]).map(([a, b]) => [a, Math.min(b, recorded)]);

  /** Where a recorded moment lands in the trimmed reel, or undefined. */
  const place = (t) => {
    let offset = 0;
    for (const [a, b] of keep) {
      if (t >= a && t <= b) return offset + (t - a);
      offset += b - a;
    }
    return undefined;
  };

  // Every output frame is the last real frame painted at the recorded
  // moment it stands for. Walked forward with one cursor, since the kept
  // stretches are in order.
  const at = (t) => {
    while (cursor + 1 < frames.length && frames[cursor + 1].ts - zero <= t) {
      cursor += 1;
    }
    return frames[cursor];
  };
  // Begin on the last frame painted at or before t0, which is the pre-roll
  // frame: that is what the screen actually showed as recording started.
  let cursor = 0;
  while (cursor + 1 < frames.length && frames[cursor + 1].ts <= zero) {
    cursor += 1;
  }
  let copied = 0;
  for (const [a, b] of keep) {
    const count = Math.round((b - a) * FPS);
    for (let k = 0; k < count; k += 1) {
      fs.copyFileSync(
        path.join(src, at(a + k / FPS).file),
        path.join(out, `${String(copied).padStart(5, "0")}.jpg`),
      );
      copied += 1;
    }
  }
  const span = copied / FPS;

  // Marks in frame numbers, which is what an editor actually needs.
  const marks = [];
  for (const m of manifest.marks) {
    const t = place(m.t);
    if (t === undefined) {
      console.log(`  ${shot.padEnd(14)} mark "${m.label}" is in a removed stretch, dropped`);
      continue;
    }
    marks.push({ ...m, t, frame: Math.round(t * FPS) });
  }
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
