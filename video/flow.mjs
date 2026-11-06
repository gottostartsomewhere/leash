// Renders the flow animation to frames, one timestamp at a time.
//
//   node video/flow.mjs              the whole thing
//   node video/flow.mjs 12 18        just that stretch, for checking a beat
//
// Stepped rather than screencast. A screencast only delivers a frame when
// the page paints, which is fine for an interface being driven and useless
// for an animation that holds: the holds arrive as nothing at all and the
// resampler has to invent them. Stepping asks for an exact timestamp and
// gets exactly that picture, so a four second hold is four seconds of
// identical frames and a fast move keeps every one of its own.
//
// Output lands in video/reel/flow at a constant 30fps, which is already
// what assemble.mjs wants, so reel.mjs never sees it.

import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE = "file:///" + path.join(HERE, "flow.html").replace(/\\/g, "/");
const OUT = path.join(HERE, "reel", "flow");
const FPS = 30;

const argv = process.argv.slice(2).map(Number).filter((n) => !Number.isNaN(n));
const [FROM, TO] = argv.length === 2 ? argv : [null, null];

const browser = await chromium.launch({
  channel: "chrome",
  args: ["--hide-scrollbars", "--force-color-profile=srgb"],
});
// Rendered at 2x and delivered at 1080p, so hairlines and mono digits stay
// crisp after the downscale. Nothing here is ever pushed into, so there is
// no reason to carry the larger frame any further than this.
const page = await browser.newPage({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 2,
});
await page.goto(PAGE);
await page.waitForFunction(() => window.flow);
await page.evaluate(() => document.fonts.ready);
await page.waitForTimeout(500);

const width = await page.evaluate(() => window.flow.measure());
const duration = await page.evaluate(() => window.flow.DURATION);

const first = FROM === null ? 0 : Math.round(FROM * FPS);
const last = TO === null ? Math.round(duration * FPS) - 1 : Math.round(TO * FPS);

if (FROM === null) fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT, { recursive: true });

console.log(
  `flow: ${duration}s at ${FPS}fps, token ${Math.round(width)}px wide\n` +
    `frames ${first}-${last}\n`,
);

const started = Date.now();
for (let n = first; n <= last; n += 1) {
  await page.evaluate((t) => window.flow.render(t), n / FPS);
  await page.screenshot({
    path: path.join(OUT, `${String(n).padStart(5, "0")}.jpg`),
    type: "jpeg",
    quality: 92,
  });
  if ((n - first) % 120 === 0 && n > first) {
    const done = n - first + 1;
    const rate = done / ((Date.now() - started) / 1000);
    process.stdout.write(
      `  ${String(n).padStart(5)} / ${last}   ${rate.toFixed(1)} fps\n`,
    );
  }
}

await browser.close();
console.log(`\n${last - first + 1} frames in ${OUT}`);
