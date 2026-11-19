// Capture product screenshots from a running local stack.
// Usage: node scripts/capture.mjs   (API on :8000, Vite on :5173)
import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const BASE = process.env.RESOLVE_WEB_URL ?? "http://localhost:5173";
const PASSWORD = process.env.RESOLVE_DEMO_PASSWORD ?? "";
if (!PASSWORD) {
  throw new Error("Set RESOLVE_DEMO_PASSWORD (see var/secrets/demo-credentials.txt)");
}
const OUT = path.resolve(process.cwd(), "../../docs/screenshots");

const routes = [
  ["dashboard", "/"],
  ["exceptions", "/exceptions"],
  ["cases", "/cases"],
  ["documents", "/documents"],
  ["invoices", "/invoices"],
  ["vendors", "/vendors"],
  ["purchase-orders", "/purchase-orders"],
  ["approvals", "/approvals"],
  ["integrations", "/integrations"],
  ["workflows", "/workflows"],
  ["evaluation", "/evaluation"],
  ["analytics", "/analytics"],
  ["audit", "/audit"],
  ["settings", "/settings"],
];

await mkdir(OUT, { recursive: true });

const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
const page = await context.newPage();
const errors = [];
page.on("console", (message) => {
  if (message.type() === "error") errors.push(message.text());
});
page.on("pageerror", (error) => errors.push(String(error)));

await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
await page.screenshot({ path: path.join(OUT, "01-login.png"), fullPage: true });

await page.fill('input[type="email"]', "admin@example.com");
await page.fill('input[type="password"]', PASSWORD);
await page.click('button[type="submit"]');
await page.waitForURL(`${BASE}/`, { timeout: 20000 }).catch(() => {});
await page.waitForTimeout(2500);

let index = 2;
for (const [name, route] of routes) {
  await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1800);
  await page.screenshot({ path: path.join(OUT, `${String(index).padStart(2, "0")}-${name}.png`), fullPage: true });
  index += 1;
}

// Case workspace: open the first case and capture the investigation tab.
await page.goto(`${BASE}/cases`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(1200);
const firstCase = page.locator("tbody tr").first();
if (await firstCase.count()) {
  await firstCase.click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(OUT, "20-case-workspace.png"), fullPage: true });
  const investigationTab = page.getByRole("tab", { name: /investigation/i });
  if (await investigationTab.count()) {
    await investigationTab.click();
    await page.waitForTimeout(800);
    const runButton = page.getByRole("button", { name: /run investigation/i });
    if (await runButton.count()) {
      await runButton.click();
      await page.getByText("Evidence", { exact: true }).first().waitFor({ timeout: 20000 }).catch(() => {});
      await page.waitForTimeout(1200);
    }
    await page.screenshot({ path: path.join(OUT, "21-case-investigation.png"), fullPage: true });
  }
}

// Document review page.
await page.goto(`${BASE}/documents`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(1200);
const firstDocument = page.locator("tbody tr").first();
if (await firstDocument.count()) {
  await firstDocument.click();
  await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(OUT, "22-document-review.png"), fullPage: true });
}

// Dark theme dashboard.
await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
await page.evaluate(() => {
  localStorage.setItem("resolve-theme", "dark");
  document.documentElement.setAttribute("data-theme", "dark");
});
await page.reload({ waitUntil: "domcontentloaded" });
await page.waitForTimeout(1500);
await page.screenshot({ path: path.join(OUT, "23-dashboard-dark.png"), fullPage: true });

await browser.close();
if (errors.length) {
  console.log("Console errors:\n" + errors.join("\n"));
  process.exitCode = 1;
} else {
  console.log("Screenshots captured without console errors.");
}
