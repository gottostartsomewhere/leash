// Records every shot of the demo as timestamped 1080p frames.
//
//   uvicorn leash.api:app --reload        (port 8000)
//   npm --prefix web run dev              (port 5173)
//   node video/record.mjs                 (all shots)
//   node video/record.mjs shop revoke     (just those)
//
// Title cards come from titles.html. App shots drive the real build against
// the real API, resetting the demo first, so what lands in the video is the
// thing actually working rather than a mock of it.
//
// Each shot writes frames/<name>/00000.jpg… plus a manifest carrying frame
// timestamps and labelled marks, so the edit knows where each beat lands
// instead of being scrubbed for by hand.

import { chromium } from "playwright-core";
import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const TITLES = "file:///" + path.join(HERE, "titles.html").replace(/\\/g, "/");
// localhost rather than 127.0.0.1: Vite binds to the IPv6 loopback, and the
// numeric v4 address is refused.
const APP = process.env.LEASH_WEB ?? "http://localhost:5173";
const API = process.env.LEASH_API ?? "http://127.0.0.1:8000";

// Laid out at 1536 wide and rendered into a 1920 frame. The grid is dense,
// and text that is comfortable on a desktop is unreadable on a phone, which
// is where half of any demo video gets watched.
const ZOOM = 1.25;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const only = process.argv.slice(2);

async function reset() {
  const r = await fetch(`${API}/demo/reset`, { method: "POST" });
  if (!r.ok) throw new Error(`reset failed: ${r.status}`);
}

const browser = await chromium.launch({
  channel: "chrome",
  args: ["--hide-scrollbars", "--force-color-profile=srgb"],
});
// Captured at 2x so a push-in has real pixels to show. Zooming a 1920
// source past about 1.2 goes soft, and the shots here push to 2.1.
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 2,
});

/** Screencast every painted frame while `fn` runs. */
/** Empty a shot directory. Windows holds directory handles for a moment
 *  after a process reads them, so removing the whole thing can fail with
 *  EBUSY while the files inside delete perfectly well. */
function fresh(dir) {
  try {
    fs.rmSync(dir, { recursive: true, force: true });
  } catch {
    for (const f of fs.readdirSync(dir)) {
      try {
        fs.unlinkSync(path.join(dir, f));
      } catch {
        /* a locked frame is not worth failing the run over */
      }
    }
  }
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

/** A single crisp PNG. A still page paints almost nothing, so screencasting
 *  one yields two frames and a misleading manifest. */
async function still(name, page) {
  const dir = fresh(path.join(HERE, "frames", name));
  const file = path.join(dir, "still.png");
  await page.screenshot({ path: file });
  console.log(`  ${name.padEnd(14)} still.png`);
}

async function take(name, page, fn) {
  const dir = fresh(path.join(HERE, "frames", name));

  const cdp = await context.newCDPSession(page);
  const frames = [];
  const marks = [];

  cdp.on("Page.screencastFrame", async ({ data, metadata, sessionId }) => {
    // Ack before writing, not after. Chrome will not send the next frame
    // until this one is acknowledged, so holding the ack behind a
    // multi-megabyte synchronous write throttles the capture exactly when
    // the page is busiest: during a camera move. That dropped every push
    // from the footage and turned a 620ms move into an instant jump.
    cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
    const file = `${String(frames.length).padStart(5, "0")}.jpg`;
    frames.push({ file, ts: metadata.timestamp });
    fs.writeFileSync(path.join(dir, file), Buffer.from(data, "base64"));
  });

  // Capture at delivery size. The 2x source existed so ffmpeg had real
  // pixels to push into, and the camera has since moved into the page, so
  // every one of those frames was being scaled straight back down to 1080p
  // at four times the bytes. The page still *renders* at 2x
  // (deviceScaleFactor), so text stays crisp; only the transport shrinks.
  await cdp.send("Page.startScreencast", {
    format: "jpeg",
    quality: 92,
    maxWidth: 1920,
    maxHeight: 1080,
  });
  await sleep(400);

  // The screencast settles before the action starts, so the first frames
  // are pre-roll. Remember where the action actually begins, otherwise
  // every shot is resampled a few hundred milliseconds early and the marks
  // no longer line up with the picture.
  const startIndex = frames.length;
  const t0 = Date.now() / 1000;
  const mark = (label) => marks.push({ label, t: Date.now() / 1000 - t0 });
  await fn(mark);
  const t1 = Date.now() / 1000;

  await cdp.send("Page.stopScreencast");
  await sleep(250);
  fs.writeFileSync(
    path.join(dir, "manifest.json"),
    JSON.stringify({ shot: name, t0, t1, startIndex, frames, marks }, null, 1),
  );
  console.log(
    `  ${name.padEnd(14)} ${(t1 - t0).toFixed(1)}s  ${String(frames.length).padStart(4)} frames` +
      (marks.length
        ? `  ${marks.map((m) => `${m.label}@${m.t.toFixed(1)}`).join(" ")}`
        : ""),
  );
  await cdp.detach();
}

/* -- title cards -------------------------------------------------------- */

async function card(index, name, seconds) {
  const page = await context.newPage();
  await page.goto(TITLES);
  await page.waitForFunction(() => window.leash);
  await sleep(500); // let the webfonts land before the first painted frame
  await take(name, page, async () => {
    await page.evaluate((i) => window.leash.play(i), index);
    await sleep(seconds * 1000);
  });
  await page.close();
}

/* -- the app ------------------------------------------------------------ */

/** The app, with its first-visit intro folded or showing.
 *
 *  Folded for every shot but the arrival: the intro is what a judge reads
 *  first, and in the middle of the film it is a band of chrome pushing the
 *  thing being demonstrated down the screen. Set before the page loads, so
 *  no frame ever catches it folding. */
async function openApp({ folded = true } = {}) {
  const page = await context.newPage();
  await page.addInitScript((fold) => {
    try {
      if (fold) localStorage.setItem("leash.intro.folded", "1");
      else localStorage.removeItem("leash.intro.folded");
    } catch {
      /* storage blocked: the app shows the intro, which is the safe default */
    }
  }, folded);
  await page.goto(APP);
  await page.addStyleTag({ content: `html { zoom: ${ZOOM} }` });
  // The rail only renders once the mandate has loaded.
  await page.getByText("Total authority").waitFor({ timeout: 60_000 });

  // Camera moves happen in the page, the way the Recon promo did them: a
  // short CSS transform on the app root, origin set to whatever is being
  // talked about. GPU-composited so it is subpixel smooth, fast enough to
  // read as a cut-in rather than a drift, and the interface stays live
  // underneath instead of being a still that gets panned across.
  await page.addStyleTag({
    content: `#root { transition: transform 620ms cubic-bezier(.65,0,.35,1);
                       will-change: transform; }`,
  });
  await page.evaluate(() => {
    const root = document.getElementById("root");
    window.film = {
      /** Bring the subject on screen before the camera is pointed at it.
       *
       *  Scaling cannot reach what is below the fold: the shopping result
       *  renders under the shelf and sits past the bottom of the window, so
       *  framing it produced a push onto empty space while the caption
       *  described rows nobody could see. Only scrolls when it has to, so
       *  the shots whose subject is already visible are unchanged. */
      reveal(selector) {
        const el = document.querySelector(selector);
        if (!el) return false;
        // Unconditionally, because being inside the window is not the same
        // as being visible: the shopping panel is its own 228px scroll box
        // and clips its result, so the subject can sit at a perfectly
        // reasonable viewport position and still be behind an overflow
        // edge. scrollIntoView walks every scrollable ancestor; a subject
        // that is already where it should be does not move.
        el.scrollIntoView({ block: "center", behavior: "smooth" });
        return true;
      },

      /** Park the camera and settle the layout, with no animation.
       *
       *  Measuring while a previous push is still unwinding reads the old
       *  framing and computes the next one from it, which lands the shot
       *  somewhere neither move intended. */
      park() {
        const prev = root.style.transition;
        root.style.transition = "none";
        root.style.transform = "none";
        void root.offsetWidth;
        root.style.transition = prev;
        void root.offsetWidth;
      },

      to(selector, scale = 1.45) {
        const el = document.querySelector(selector);
        if (!el) return false;
        this.park();

        // Everything here is in viewport coordinates, not the root's own
        // box. Once a shot scrolls (the shopping result makes the page
        // taller than the window) the root is bigger than what the camera
        // can see, and clamping against it frames a region that is off
        // screen: the push landed on empty space while the caption
        // described rows nobody could see.
        const W = window.innerWidth;
        const H = window.innerHeight;
        const e = el.getBoundingClientRect();
        const vw = W / scale;
        const vh = H / scale;

        // Which slice of the window survives the scale: centred on the
        // subject where it can be, pulled inside the window where it
        // cannot, so an edge never comes into frame.
        // Centre on the part of the subject that is actually on screen. A
        // subject wider or taller than the window has a true centre that
        // may be well outside it, and aiming there frames empty space.
        const cx = (Math.max(e.left, 0) + Math.min(e.right, W)) / 2;
        const cy = (Math.max(e.top, 0) + Math.min(e.bottom, H)) / 2;
        const left = Math.min(Math.max(cx - vw / 2, 0), W - vw);
        const top = Math.min(Math.max(cy - vh / 2, 0), H - vh);

        // transform-origin is relative to the root's own border box, so
        // convert out of viewport space on the way in.
        const k = 1 - 1 / scale;
        const r = root.getBoundingClientRect();
        root.style.transformOrigin =
          `${left / k - r.left}px ${top / k - r.top}px`;
        root.style.transform = `scale(${scale})`;
        return true;
      },

      out() {
        root.style.transform = "none";
      },
    };
  });

  await sleep(700);
  return page;
}

/** Push in on something, hold, come back.
 *
 *  Marks the window where the camera is settled on the target, as
 *  `<label>` and `<label>/out`. The caption layer anchors to those, so a
 *  re-record with a different network wait still lands its text on the
 *  right frames instead of needing the times counted out by hand. */
async function look(page, mark, selector, label, { scale = 1.45, hold = 1500 } = {}) {
  const found = await page.evaluate(
    ([sel]) => window.film.reveal(sel),
    [selector],
  );
  if (!found) return false;
  await sleep(620); // let any scroll land before the geometry is measured
  await page.evaluate(([sel, sc]) => window.film.to(sel, sc), [selector, scale]);
  await sleep(620);
  mark(label);
  await sleep(hold);
  mark(`${label}/out`);
  await page.evaluate(() => window.film.out());
  await sleep(700);
  return true;
}

async function ask(page, { payee, category, amount }) {
  await page.getByRole("tab", { name: "Ask for one thing" }).click();
  await page.locator("select").first().selectOption(payee);
  await page.locator("select").nth(1).selectOption(category);
  const box = page.getByLabel("Amount in major units");
  await box.fill(amount);
  await page.getByRole("button", { name: "Ask to spend" }).click();
}

/** The sentence typed on camera. Drafted three times against the real model
 *  before it was chosen: $150, $40 a shop, food, a week, and "no alcohol"
 *  under not-enforced, every time. */
const GROCERIES =
  "Groceries only. $150 for the week, never more than $40 at any one shop, and no alcohol.";

const SHOTS = {
  // Longer, busier takes. Camera moves can cover a short shot, but real
  // motion underneath is what stops a segment reading as a still.

  /** What a judge sees first, then the terms that headline is about. */
  async intro() {
    await reset();
    const page = await openApp({ folded: false });
    await page.locator(".intro h1").waitFor();
    await take("intro", page, async (mark) => {
      mark("arrive");
      await sleep(2800);
      await look(page, mark, ".rules", "rules", { scale: 1.6, hold: 2000 });
      await sleep(400);
    });
    await page.close();
  },

  /** Plain English in, a draft the engine has checked and attacked out. */
  async write() {
    await reset();
    const page = await openApp();
    await take("write", page, async (mark) => {
      await page.getByRole("tab", { name: "Write a mandate" }).click();
      await sleep(800);
      const box = page.getByLabel("What the agent may spend, in plain English");
      await box.fill("");
      mark("typing");
      await box.pressSequentially(GROCERIES, { delay: 30 });
      await sleep(500);
      mark("draft");
      await page.getByRole("button", { name: "Draft it" }).click();
      await page.locator(".draft").waitFor({ timeout: 90_000 });
      mark("drafted");
      await sleep(900);
      // The two columns together are wider than any push can hold, so each
      // gets its own: what it read (with "no alcohol" not enforced), then
      // the worst an agent could do inside it.
      await look(page, mark, ".draft-cols > div:first-child", "read", { scale: 1.6, hold: 2600 });
      await look(page, mark, ".exposure", "exposure", { scale: 1.6, hold: 2000 });
      await look(page, mark, ".attacked", "attacked", { scale: 1.8, hold: 1500 });
      mark("sign");
      await page.getByRole("button", { name: "Sign it and use it" }).click();
      await page.locator(".signed").waitFor({ timeout: 30_000 });
      mark("signed");
      await sleep(900);
      // The payoff: the rail is now the mandate that was just written.
      await look(page, mark, ".rules", "live", { scale: 1.5, hold: 2200 });
      await sleep(300);
    });
    await page.close();
  },

  /** Three hundred attacks on a sandbox copy, replayed. */
  async attack() {
    await reset();
    const page = await openApp();
    await take("attack", page, async (mark) => {
      await page.getByRole("tab", { name: "Try to break it" }).click();
      await sleep(900);
      mark("fire");
      await page.getByRole("button", { name: "Run 300 attacks" }).click();
      await page.locator(".attack-verdict.settled").waitFor({ timeout: 30_000 });
      mark("settled");
      await sleep(800);
      // Aimed at the words beside the count, not the panel: the panel is as
      // wide as the window, and a push on it cut the lane names off. From
      // here the count, the verdict and the lanes' names share the frame.
      await look(page, mark, ".tally-of", "lanes", { scale: 1.8, hold: 2400 });
      await sleep(400);
    });
    await page.close();
  },

  /** An agent that is not ours, over MCP, landing on the screen live. */
  async mcp() {
    await reset();
    const page = await openApp();
    await take("mcp", page, async (mark) => {
      await page.getByRole("tab", { name: "Connect your agent" }).click();
      await sleep(900);
      await look(page, mark, ".copyable", "url", { scale: 1.8, hold: 1400 });
      // The real client, over the real protocol, while the screen watches.
      // Nothing tells the screen it happened; it notices on its own poll.
      mark("agent");
      const agent = spawn("python", ["scripts/agent_probe.py", `${API}/mcp`], {
        cwd: ROOT,
        env: { ...process.env, PYTHONPATH: "." },
        stdio: "ignore",
      });
      const finished = new Promise((r) => agent.on("exit", r));
      await page.locator(".their-moves li").first().waitFor({ timeout: 60_000 });
      mark("first-move");
      await Promise.race([finished, sleep(60_000)]);
      // The screen polls every four seconds, so one full poll after the
      // agent hangs up is enough for its last move to land.
      await sleep(4300);
      mark("landed");
      await look(page, mark, ".their-moves", "moves", { scale: 1.7, hold: 2800 });
      await sleep(400);
      agent.kill();
    });
    await page.close();
  },

  async mandate() {
    await reset();
    const page = await openApp();
    // One spend so the gauge is not sitting at zero.
    await ask(page, { payee: "northwind", category: "office-supplies", amount: "40.00" });
    await sleep(1600);
    await take("mandate", page, async (mark) => {
      mark("wide");
      await sleep(1400);
      await look(page, mark, ".gauge", "gauge", { scale: 1.9, hold: 1500 });
      mark("terms");
      await look(page, mark, ".rules", "rules", { scale: 1.65, hold: 2200 });
      await look(page, mark, ".scope", "scope", { scale: 1.9, hold: 1400 });
      await sleep(800);
    });
    await page.close();
  },

  async shop() {
    await reset();
    const page = await openApp();
    await take("shop", page, async (mark) => {
      await page.getByRole("tab", { name: "Send it shopping" }).click();
      await sleep(900);
      const box = page.getByLabel("What the agent should buy");
      await box.fill("");
      mark("typing");
      await box.pressSequentially("office chair", { delay: 90 });
      await sleep(600);

      // Show the shelf first: real products sliding in is the best motion
      // in the whole app and it was going unused.
      mark("look");
      await page.getByRole("button", { name: "Look first" }).click();
      await page.locator(".product").first().waitFor({ timeout: 90_000 });
      mark("shelf");
      await sleep(1200);
      await look(page, mark, ".product", "product", { scale: 2.0, hold: 1500 });
      // Scroll the shelf inside its own box. (It used to widen the whole
      // page instead, until the layout grid got minmax(0, 1fr) columns.)
      await page.evaluate(() => {
        const shelf = document.querySelector(".shelf");
        if (shelf) shelf.scrollBy({ left: 900, behavior: "smooth" });
      });
      await sleep(1200);

      mark("send");
      await page.getByRole("button", { name: "Send the agent" }).click();
      await page.getByText("What it did").waitFor({ timeout: 90_000 });
      mark("result");
      await sleep(1100);
      // Push onto the byline rather than holding the whole frame.
      //
      // `Chose` is the last row of the result: who picked the product, and
      // the reason they gave. It is the only place in the cut where the
      // model is shown rather than claimed, and at full frame it is twelve
      // pixels of grey at the bottom edge. At this scale the two rows it
      // sits under come into frame with it, so the refusal and the thing
      // that caused it are read in one shot.
      //
      // Framed on the model's name rather than on `.chose` itself. The row
      // runs the full width of the result, 2387px of it, so its centre is
      // a point in the middle of empty table and a push aimed there lands
      // on the shelf. The name is a span of a couple of hundred pixels and
      // has a centre worth pointing a camera at; the reason it gave sits
      // immediately to its right and comes along at this scale.
      await look(page, mark, ".chose-who", "trace", { scale: 1.7, hold: 1400 });
      mark("grid");
      await sleep(1800);
      mark("grid/out");
      await sleep(600);
    });
    await page.close();
  },

  async structuring() {
    await reset();
    const page = await openApp();
    await take("structuring", page, async (mark) => {
      mark("first");
      await ask(page, { payee: "acme_us", category: "furniture", amount: "75.00" });
      await sleep(3000);
      mark("second");
      await ask(page, { payee: "acme_eu", category: "furniture", amount: "75.00" });
      await page.getByText("Structuring").first().waitFor({ timeout: 30_000 });
      mark("caught");
      await sleep(1300);
      await look(page, mark, ".cluster", "cluster", { scale: 1.9, hold: 2400 });
      await look(page, mark, ".facts", "facts", { scale: 1.6, hold: 1600 });

      // The grid doing grid things, which is also the AG Grid story.
      mark("filter");
      await page.getByRole("button", { name: "Only refusals" }).click();
      await sleep(2200);
      await page.getByRole("button", { name: "Only refusals" }).click();
      await sleep(1200);
    });
    await page.close();
  },

  async payout() {
    await reset();
    const page = await openApp();
    for (const spend of [
      { payee: "northwind", category: "office-supplies", amount: "40.00" },
      { payee: "globex", category: "furniture", amount: "60.00" },
      { payee: "initech", category: "office-supplies", amount: "25.00" },
    ]) {
      await ask(page, spend);
      await sleep(900);
    }
    await sleep(1200);

    await take("payout", page, async (mark) => {
      // Selected one at a time, so the count and the total climb on camera.
      const boxes = page.locator('.ag-row input[type="checkbox"]');
      const n = await boxes.count();
      mark("select");
      for (let i = 0; i < n; i += 1) {
        await boxes.nth(i).click({ timeout: 5000 }).catch(() => {});
        await sleep(700);
      }
      await sleep(1200);
      mark("approve");
      await page.getByRole("button", { name: "Approve and pay out" }).click();
      // The rail has a "Settled" stat label, so match the grid cell
      // instead: otherwise this resolves on the click and the shot runs
      // on before PayPal has answered.
      await page.locator(".ag-row").getByText("Settled").first()
        .waitFor({ timeout: 120_000 });
      mark("settled");
      await sleep(1200);
      await look(page, mark, ".ag-header", "grid", { scale: 1.6, hold: 1700 });
      await look(page, mark, ".gauge", "gauge", { scale: 1.8, hold: 1500 });
    });
    await page.close();
  },

  async revoke() {
    await reset();
    const page = await openApp();
    for (const spend of [
      { payee: "northwind", category: "office-supplies", amount: "40.00" },
      { payee: "globex", category: "furniture", amount: "60.00" },
      { payee: "initech", category: "office-supplies", amount: "25.00" },
    ]) {
      await ask(page, spend);
      await sleep(900);
    }
    await sleep(1400);

    await take("revoke", page, async (mark) => {
      mark("revoke");
      await page.getByRole("button", { name: "Revoke", exact: true }).click();
      await page.getByText("Revoked", { exact: true }).first().waitFor({ timeout: 30_000 });
      mark("dropped");
      await sleep(1100);
      await look(page, mark, ".status", "topbar", { scale: 2.4, hold: 1500 });

      // Asking a dead mandate for money, twice, is the point of the beat.
      mark("ask-again");
      await ask(page, { payee: "acme_us", category: "furniture", amount: "20.00" });
      await page.getByText("Mandate inactive").first().waitFor({ timeout: 30_000 });
      mark("refused");
      await sleep(1100);
      await look(page, mark, ".ag-header", "grid", { scale: 1.7, hold: 1800 });
      await ask(page, { payee: "northwind", category: "office-supplies", amount: "5.00" });
      await sleep(1500);
    });
    await page.close();
  },
};

const CARDS = [
  [0, "problem", 7],
  [1, "lower", 5],
  [6, "premise", 8],
  [2, "statement", 4],
  [3, "tally", 10],
  [4, "closing", 8],
  [5, "endcard", 6],
];

const wanted = (name) => only.length === 0 || only.includes(name);

console.log(`app ${APP}  api ${API}  zoom ${ZOOM}\n`);

// Only the app shots need a server. Re-recording a title card should not
// require the whole stack to be up.
const needsApp = Object.keys(SHOTS).some(wanted);
if (needsApp) try {
  const health = await fetch(`${API}/health`).then((r) => r.json());
  console.log(`gateway ${health.gateway}, catalog ${health.catalog}\n`);
} catch {
  console.error(`Cannot reach the API at ${API}. Start it first.`);
  process.exit(1);
}

console.log("cards");
for (const [i, name, secs] of CARDS) {
  if (wanted(name)) await card(i, name, secs);
}

console.log("\napp");
for (const [name, run] of Object.entries(SHOTS)) {
  if (wanted(name)) await run();
}

await browser.close();
console.log(`\nframes in ${path.join(HERE, "frames")}`);
