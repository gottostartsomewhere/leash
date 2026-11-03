// Renders the callout layer as transparent PNGs, one per frame.
//
//   node video/overlay.mjs            all scenes
//   node video/overlay.mjs shop
//
// Driven by overlays.html's `render(scene, t)` rather than by CSS
// animations, so stepping frame by frame gives the same picture every time.
// assemble.mjs composites these onto the raw app frames before the push, so
// a callout travels with the shot instead of sliding against it.

import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE = "file:///" + path.join(HERE, "overlays.html").replace(/\\/g, "/");
const OUT = path.join(HERE, "overlay");
const FPS = 30;

// Only the stretch where something is moving. Once a callout has landed it
// holds, so assemble.mjs repeats the last frame rather than rendering
// hundreds of identical PNGs.
const SCENES = {
  shop: { from: 3.6, to: 7.6 },
  structuring: { from: 4.6, to: 9.4 },
  revoke: { from: 4.8, to: 6.2 },
};

const only = process.argv.slice(2);
const wanted = (name) => only.length === 0 || only.includes(name);

const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
});
await page.goto(PAGE);
await page.waitForFunction(() => window.overlay);
await page.waitForTimeout(600); // webfonts

console.log(`overlays at ${FPS}fps\n`);

for (const [scene, span] of Object.entries(SCENES)) {
  if (!wanted(scene)) continue;

  const dir = path.join(OUT, scene);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });

  const first = Math.round(span.from * FPS);
  const last = Math.round(span.to * FPS);

  for (let n = first; n <= last; n += 1) {
    await page.evaluate(
      ([s, t]) => window.overlay.render(s, t),
      [scene, n / FPS],
    );
    await page.screenshot({
      path: path.join(dir, `${String(n).padStart(5, "0")}.png`),
      omitBackground: true, // transparent, so ffmpeg can composite it
    });
  }

  fs.writeFileSync(
    path.join(dir, "span.json"),
    JSON.stringify({ scene, fps: FPS, first, last, ...span }, null, 1),
  );
  console.log(
    `  ${scene.padEnd(14)} frames ${first}-${last}  (${span.from}s - ${span.to}s)`,
  );
}

await browser.close();
console.log(`\noverlays in ${OUT}`);
