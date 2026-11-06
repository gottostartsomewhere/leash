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
  shop: { from: 0, to: 4.6 },
  structuring: { from: 0, to: 4.8 },
  revoke: { from: 0, to: 1.8 },
};

// Captions: what the camera is actually looking at, in words, so the picture
// explains itself instead of waiting for the narration to do it.
//
// `at: "grid"` spans the window the camera held on that target, read from
// the marks the recorder wrote. `from`/`to` are plain segment seconds, for
// the beats that are not a push. Anchoring to marks is what makes a
// re-record safe: a slower catalogue search moves every later beat, and
// hand-counted times would put the text on the wrong frames.
const CAPTIONS = {
  mandate: [
    { from: 0.2, to: "gauge-0.5", title: "One mandate", note: "What this agent is allowed to spend" },
    { at: "gauge", title: "The budget", note: "$500 in total, and what is left of it" },
    { at: "rules", title: "The terms", note: "$100 a purchase, and a pace it cannot beat" },
    { at: "scope", title: "The scope", note: "Named merchants, named categories" },
    { from: "scope/out+0.3", to: "END", title: "Nothing outside this is spendable" },
  ],
  shop: [
    { from: 0.4, to: "look-0.4", title: "Send it shopping", note: "The agent gets a goal, not a budget" },
    { from: "shelf+0.2", to: "product-0.5", title: "It searches a real catalogue", note: "Live products and real merchants, through Channel3" },
    { at: "product", title: "Real listings, real merchants", note: "A live catalogue, not a fixture dressed up as one" },
    { from: "result+0.4", to: "trace-0.5", title: "Now let it spend", note: "Every item checked before any money moves" },
    // Kept short on purpose. This caption runs under a push that fills the
    // right two thirds of the frame with the result panel, and a longer
    // line reaches across into it and lands on the byline it is pointing at.
    { at: "trace", title: "A model chose it", note: "The product, and nothing else" },
    { at: "grid", title: "And the mandate refused it", note: "$190.49, over the $100 ceiling. It came back with $97.99." },
  ],
  structuring: [
    { from: 0.3, to: "second-0.3", title: "$75 to Acme US", note: "Under the $100 ceiling, so it clears" },
    { from: "second+0.4", to: "cluster-0.5", title: "$75 to Acme EU", note: "Also under the ceiling" },
    { at: "cluster", title: "Same merchant, two addresses", note: "75 + 75 = 150, over the limit" },
    { at: "facts", title: "Refused as structuring", note: "The reason is kept, not just the verdict" },
    { from: "filter+0.2", to: "search-0.6", title: "Every decision is queryable", note: "Filtered down to the refusals" },
    { from: "search+0.3", to: "END", title: "And searchable", note: "AG Grid over the live decision log" },
  ],
  payout: [
    { from: 0.3, to: "approve-0.3", title: "Approved, and waiting", note: "Nothing settles without a person saying so" },
    { from: "approve+0.3", to: "grid-0.5", title: "One batch", note: "Sent through PayPal Payouts" },
    { at: "grid", title: "Settled", note: "Each charge carries the PayPal item id that paid it" },
    { at: "gauge", title: "Held becomes settled", note: "$125 moved, $375 still available" },
    { from: "gauge/out+0.3", to: "END", title: "Real payouts, in the PayPal sandbox" },
  ],
  // The one segment cut from a screen recording. Eleven seconds of a
  // different product's UI with nothing saying why it is on screen.
  paypal: [
    { from: 0.3, to: 3.4, plate: true, title: "The other side of it", note: "A PayPal sandbox account, receiving" },
    { from: 4.2, to: 9.0, plate: true, title: "Every payout the agent made", note: "Same amounts, in PayPal's own ledger" },
  ],
  revoke: [
    { from: 0.2, to: "topbar-0.5", title: "Revoke", note: "One click, mid-session" },
    { at: "topbar", title: "The authority is gone", note: "Not paused, not queued. Gone." },
    { from: "ask-again+0.3", to: "grid-0.5", title: "The agent asks again", note: "It does not know anything changed" },
    { at: "grid", title: "Refused, mandate inactive", note: "There is no budget left to argue with" },
    { from: "grid/out+0.3", to: "END", title: "It keeps asking. It keeps getting nothing." },
  ],
};

/** Resolve `at: "<label>"` against the window the camera actually held. */
function resolve(shot, track) {
  const file = path.join(HERE, "reel", shot, "marks.json");
  const marks = fs.existsSync(file)
    ? JSON.parse(fs.readFileSync(file, "utf-8")).marks
    : [];
  const when = (label) => marks.find((m) => m.label === label)?.t;
  const last = marks.length ? Math.max(...marks.map((m) => m.t)) : 0;

  /** A caption edge: a number of seconds, or a mark with an offset.
   *
   *  Every beat in a shot moves when the network does. A warm catalogue
   *  cache took four seconds off the shopping take, and times written as
   *  plain numbers then describe moments that have already gone past. */
  const time = (v) => {
    if (typeof v === "number") return v;
    if (v === "END") return last + 2.5;
    const m = /^(.+?)([+-][\d.]+)$/.exec(v);
    const base = when(m ? m[1] : v);
    if (base === undefined) return undefined;
    return base + (m ? Number(m[2]) : 0);
  };

  return track
    .map((c) => {
      if (!c.at) {
        const from = time(c.from);
        const to = time(c.to);
        if (from === undefined || to === undefined) {
          console.warn(`  ! ${shot}: cannot place "${c.title}", dropped`);
          return null;
        }
        return { ...c, from, to };
      }
      const from = when(c.at);
      const to = when(`${c.at}/out`);
      if (from === undefined || to === undefined) {
        console.warn(`  ! ${shot}: no mark "${c.at}", caption dropped`);
        return null;
      }
      // The mark is written when the push has already settled, and the
      // caption's own fade runs another 0.42s on top of that, so starting
      // it at the mark puts the words on screen well after the camera has
      // stopped. Lead it instead: the fade begins partway through the push
      // and finishes as the camera lands, so the text arrives with it.
      // Out a beat early, so it has cleared before the camera moves again.
      return { ...c, from: Math.max(0, from - 0.45), to: to - 0.15 };
    })
    .filter(Boolean)
    .sort((a, b) => a.from - b.from)
    // Leading a caption into its push can push its start back behind the
    // previous caption's end. One element draws them all, so an overlap
    // means the earlier one wins and the new one is simply never shown
    // until the old window has fully lapsed. Give the outgoing caption
    // just enough room to finish wiping out before the next begins.
    .map((c, i, all) => {
      const next = all[i + 1];
      return next ? { ...c, to: Math.min(c.to, next.from - 0.32) } : c;
    })
    .filter((c) => c.to > c.from);
}

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

for (const [shot, raw] of Object.entries(CAPTIONS)) {
  const name = `caption-${shot}`;
  if (!wanted(shot) && !wanted(name)) continue;
  const track = resolve(shot, raw);
  if (!track.length) continue;

  const dir = path.join(OUT, name);
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { recursive: true });

  // The whole segment, because a caption track changes throughout it.
  const last = Math.round((track[track.length - 1].to + 0.5) * FPS);
  for (let n = 0; n <= last; n += 1) {
    await page.evaluate(
      ([tr, t]) => window.overlay.caption(tr, t),
      [track, n / FPS],
    );
    await page.screenshot({
      path: path.join(dir, `${String(n).padStart(5, "0")}.png`),
      omitBackground: true,
    });
  }

  fs.writeFileSync(
    path.join(dir, "span.json"),
    JSON.stringify({ scene: name, fps: FPS, first: 0, last, from: 0, to: last / FPS }, null, 1),
  );
  console.log(
    `  ${name.padEnd(22)} frames 0-${last}  ${track.length} captions`,
  );
}

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
