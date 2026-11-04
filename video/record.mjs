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
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
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
    const file = `${String(frames.length).padStart(5, "0")}.jpg`;
    fs.writeFileSync(path.join(dir, file), Buffer.from(data, "base64"));
    frames.push({ file, ts: metadata.timestamp });
    cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
  });

  await cdp.send("Page.startScreencast", {
    format: "jpeg",
    quality: 92,
    maxWidth: 3840,
    maxHeight: 2160,
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

async function openApp() {
  const page = await context.newPage();
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
      to(selector, scale = 1.45) {
        const el = document.querySelector(selector);
        if (!el) return false;
        const r = root.getBoundingClientRect();
        const e = el.getBoundingClientRect();
        root.style.transformOrigin =
          `${e.left + e.width / 2 - r.left}px ${e.top + e.height / 2 - r.top}px`;
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

/** Push in on something, hold, come back. */
async function look(page, selector, { scale = 1.45, hold = 1500 } = {}) {
  const found = await page.evaluate(
    ([sel, sc]) => window.film.to(sel, sc),
    [selector, scale],
  );
  if (!found) return false;
  await sleep(620 + hold);
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

const SHOTS = {
  // Longer, busier takes. Camera moves can cover a short shot, but real
  // motion underneath is what stops a segment reading as a still.

  async mandate() {
    await reset();
    const page = await openApp();
    // One spend so the gauge is not sitting at zero.
    await ask(page, { payee: "northwind", category: "office-supplies", amount: "40.00" });
    await sleep(1600);
    await take("mandate", page, async (mark) => {
      mark("wide");
      await sleep(1400);
      await look(page, ".gauge", { scale: 1.9, hold: 1500 });
      mark("terms");
      await look(page, ".rules", { scale: 1.65, hold: 2200 });
      await look(page, ".scope", { scale: 1.9, hold: 1400 });
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
      await look(page, ".product", { scale: 1.7, hold: 1500 });
      await page.locator(".shelf").hover();
      await page.mouse.wheel(900, 0);
      await sleep(1200);

      mark("send");
      await page.getByRole("button", { name: "Send the agent" }).click();
      await page.getByText("What it did").waitFor({ timeout: 90_000 });
      mark("result");
      await sleep(1400);
      await look(page, ".trace", { scale: 1.75, hold: 2200 });
      await look(page, ".ag-center-cols-container", { scale: 1.6, hold: 1600 });
      await sleep(900);
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
      await look(page, ".cluster", { scale: 1.9, hold: 2400 });
      await look(page, ".facts", { scale: 1.6, hold: 1600 });

      // The grid doing grid things, which is also the AG Grid story.
      mark("filter");
      await page.getByRole("button", { name: "Only refusals" }).click();
      await sleep(2800);
      await page.getByRole("button", { name: "Only refusals" }).click();
      await sleep(2000);

      mark("search");
      const find = page.getByLabel("Search the decision log");
      await find.pressSequentially("acme", { delay: 110 });
      await sleep(2400);
      await find.fill("");
      await sleep(2200);
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
      await page.getByText("Settled").first().waitFor({ timeout: 120_000 });
      mark("settled");
      await sleep(1200);
      await look(page, ".ag-center-cols-container", { scale: 1.6, hold: 1700 });
      await look(page, ".gauge", { scale: 1.8, hold: 1500 });
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
      await look(page, ".topbar-right", { scale: 1.9, hold: 1500 });

      // Asking a dead mandate for money, twice, is the point of the beat.
      mark("ask-again");
      await ask(page, { payee: "acme_us", category: "furniture", amount: "20.00" });
      await page.getByText("Mandate inactive").first().waitFor({ timeout: 30_000 });
      mark("refused");
      await sleep(1100);
      await look(page, ".ag-center-cols-container", { scale: 1.7, hold: 1800 });
      await ask(page, { payee: "northwind", category: "office-supplies", amount: "5.00" });
      await sleep(4000);
    });
    await page.close();
  },
};

const CARDS = [
  [0, "problem", 7],
  [1, "lower", 5],
  [2, "statement", 4],
  [3, "tally", 7],
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
