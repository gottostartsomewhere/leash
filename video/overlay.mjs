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
//
// No caption runs on a push whose subject is a line of the interface that
// already says it ("Attacked before you sign: 230 attempts", the agent's
// moves, the model's byline): a caption there covers the very words it
// would repeat. `side: "right"` is for a push whose subject sits where the
// caption normally goes, in the lower left.
const CAPTIONS = {
  intro: [
    { from: 0.3, to: "rules-0.5", title: "The live demo", note: "Open to anyone, no sign-in" },
    { at: "rules", title: "The rules it can't break", note: "$100 a purchase, $200 a merchant, 6 a minute" },
  ],
  write: [
    { from: 0.4, to: "draft-0.2", title: "Write a mandate in plain English", note: "The way you'd tell a person" },
    { from: "draft+0.2", to: "read-0.5", title: "A model drafts it", note: "It never decides what's allowed" },
    { at: "read", side: "right", title: "What it understood", note: "\"No alcohol\" can't be enforced, so it says so" },
    { at: "exposure", title: "The worst an agent could do inside it", note: "No per-purchase cap, so one buy could take all $150" },
    { from: "sign", to: "live-0.5", title: "Signed", note: "The demo now runs on it" },
    { at: "live", side: "right", title: "Now these are the rules", note: "$150 for the week, $40 a shop, food only" },
  ],
  shop: [
    { from: 0.4, to: "look-0.4", title: "Send it shopping", note: "The agent gets a goal, not a budget" },
    { from: "shelf+0.2", to: "send-0.3", title: "A live catalogue", note: "Real products and merchants, through Channel3" },
    { from: "send+0.3", to: "result-0.2", title: "A model picks, the mandate checks", note: "Every purchase, before any money moves" },
    { from: "result+0.2", to: "trace-0.5", title: "Refused, and told what would clear", note: "So it looked again under $100" },
  ],
  structuring: [
    { from: 0.3, to: "second-0.3", title: "$75 to Acme US", note: "Under the $100 ceiling, so it clears" },
    { from: "second+0.4", to: "cluster-0.5", title: "$75 to Acme EU", note: "Also under the ceiling" },
    { at: "cluster", title: "Same merchant, two addresses", note: "75 + 75 = 150, over the limit" },
    { at: "facts", title: "Refused as structuring", note: "The reason is kept, not just the verdict" },
  ],
  attack: [
    // Right, because the tally counting up sits exactly where a caption goes.
    { from: 0.3, to: "settled-0.2", side: "right", title: "Try to break it", note: "Three hundred attacks on a sandbox copy" },
    { from: "settled+0.1", to: "lanes-0.5", side: "right", title: "None got through", note: "Splitting, address hopping, dripping, spraying" },
    { at: "lanes", title: "Five objectives, all held", note: "The real mandate is never touched" },
  ],
  mcp: [
    { from: 0.3, to: "url-0.5", title: "Bring your own agent", note: "Claude, ChatGPT, any MCP client" },
    { at: "url", title: "One URL", note: "Added as a connector, nothing to install" },
    { from: "agent+0.2", to: "moves-0.5", title: "A real MCP client, live", note: "Its requests land in the same log" },
    { from: "moves/out+0.2", to: "END", title: "Same rules, same refusals", note: "It can ask. It can't move money." },
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
