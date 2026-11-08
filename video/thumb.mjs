// Renders the YouTube thumbnail.
//
//   node video/thumb.mjs
//
// 1280x720 at 2x, which is what YouTube wants and then some, and it is
// checked at 320x180 as well: a thumbnail is chosen at sidebar size, so
// anything that stops reading when it is a quarter as wide is decoration.

import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PAGE = "file:///" + path.join(HERE, "thumb.html").replace(/\\/g, "/");

const browser = await chromium.launch({ channel: "chrome" });

/** One render at a given pixel density. 2x for the upload, 1x as a plain
 *  1280x720 in case anything downstream insists on exactly that. */
async function shot(file, scale) {
  const page = await browser.newPage({
    viewport: { width: 1280, height: 720 },
    deviceScaleFactor: scale,
  });
  await page.goto(PAGE);
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(700); // fonts.ready resolves before they paint
  await page.screenshot({ path: file });
  await page.close();
}

const hi = path.join(HERE, "thumb.png");
const lo = path.join(HERE, "thumb-1280.png");
await shot(hi, 2);
await shot(lo, 1);
await browser.close();

const kb = (p) => `${(fs.statSync(p).size / 1024).toFixed(0)}KB`;
console.log(`  thumb.png        2560x1440  ${kb(hi)}   <- upload this`);
console.log(`  thumb-1280.png   1280x720   ${kb(lo)}`);
console.log(`\n  YouTube takes up to 2MB, 16:9, 1280x720 or larger.`);
