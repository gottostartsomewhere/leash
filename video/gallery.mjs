// Captures the Devpost gallery from the running app.
//
//   uvicorn leash.api:app --port 8000     (with credentials, for the live catalogue and model)
//   npm --prefix web run dev
//   node video/gallery.mjs
//
// Every image is the real screen in a real state, driven the way a judge
// would drive it, so the gallery cannot drift from what the link shows.
// The outside-agent shot runs scripts/agent_probe.py over MCP while the
// screen is open, and waits for the screen to notice on its own.

import { chromium } from "playwright-core";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, "..");
const OUT = path.join(ROOT, "devpost");
const APP = process.env.LEASH_WEB ?? "http://localhost:5173";
const API = process.env.LEASH_API ?? "http://127.0.0.1:8000";
const FOLD = "leash.intro.folded";

const reset = () => fetch(`${API}/demo/reset`, { method: "POST" });

async function open(browser, { folded }) {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  await page.addInitScript(
    ([key, on]) => {
      try {
        if (on) localStorage.setItem(key, "1");
        else localStorage.removeItem(key);
      } catch {
        /* storage blocked: the default is fine */
      }
    },
    [FOLD, folded],
  );
  await page.goto(APP);
  await page.locator(".wordmark").waitFor();
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(600);
  return page;
}

async function shot(page, name) {
  const file = path.join(OUT, name);
  await page.screenshot({ path: file, type: "jpeg", quality: 90 });
  console.log(`  ${name.padEnd(22)} ${(fs.statSync(file).size / 1024).toFixed(0)}KB`);
}

const browser = await chromium.launch({ channel: "chrome" });
console.log(`capturing ${APP} against ${API}\n`);

// 1. A first visit: what is at stake, and three ways in.
await reset();
let page = await open(browser, { folded: false });
await page.locator(".intro h1").waitFor();
await shot(page, "2-intro.jpg");
await page.close();

// 2. A model picks, the mandate refuses, the agent comes back inside it.
await reset();
page = await open(browser, { folded: true });
await page.getByRole("tab", { name: "Send it shopping" }).click();
const box = page.getByLabel("What the agent should buy");
await box.fill("office chair");
await page.getByRole("button", { name: "Send the agent" }).click();
await page.getByText("What it did").waitFor({ timeout: 120_000 });
await page.waitForTimeout(1200);
await page.evaluate(() =>
  document.querySelector(".chose")?.scrollIntoView({ block: "center" }),
);
await page.waitForTimeout(400);
await shot(page, "3-model-refused.jpg");
await page.close();

// 3. Three hundred attacks, replayed, none through.
await reset();
page = await open(browser, { folded: true });
await page.getByRole("tab", { name: "Try to break it" }).click();
await page.getByRole("button", { name: "Run 300 attacks" }).click();
await page.locator(".attack-verdict.settled").waitFor({ timeout: 30_000 });
await page.waitForTimeout(500);
await shot(page, "4-attack.jpg");
await page.close();

// 4. An outside agent on a Leash: its moves arrive without a reload.
await reset();
page = await open(browser, { folded: true });
await page.getByRole("tab", { name: "Connect your agent" }).click();
execFileSync("python", ["scripts/agent_probe.py", `${API}/mcp`], {
  cwd: ROOT,
  env: { ...process.env, PYTHONPATH: "." },
  stdio: "ignore",
});
await page.locator(".their-moves li").nth(3).waitFor({ timeout: 20_000 });
await page.locator(".ag-root .via-mcp").first().waitFor();
await page.waitForTimeout(800);
await shot(page, "5-any-agent.jpg");
await page.close();

await browser.close();
await reset();
console.log(`\nin ${OUT}, demo reset`);
