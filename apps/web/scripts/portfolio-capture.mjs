// Capture portfolio screenshots and run responsive/console checks against the
// live HTTPS deployment and the loopback management UIs.
//
// Required env: RESOLVE_WEB_URL, RESOLVE_DEMO_EMAIL, RESOLVE_DEMO_PASSWORD,
// N8N_OWNER_EMAIL, N8N_OWNER_PASSWORD, GRAFANA_ADMIN_USER, GRAFANA_PASSWORD,
// PORTFOLIO_IDS (JSON with case_id, invoice_id, document_id).

import { chromium } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

const BASE = process.env.RESOLVE_WEB_URL ?? "https://localhost:8180";
const OUT = path.resolve(process.cwd(), "../../portfolio/screenshots");
const QA = path.resolve(process.cwd(), "../../portfolio/qa");
const IDS = JSON.parse(process.env.PORTFOLIO_IDS ?? "{}");
const consoleErrors = [];
const externalErrors = [];
const uxResults = [];

await mkdir(OUT, { recursive: true });
await mkdir(QA, { recursive: true });

const browser = await chromium.launch({ channel: "chrome", headless: true });

function attachErrorCapture(page, label) {
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(`${label}: ${message.text().slice(0, 300)}`);
  });
  page.on("pageerror", (error) => consoleErrors.push(`${label}: pageerror ${String(error).slice(0, 300)}`));
}

function attachExternalCapture(page, label) {
  page.on("console", (message) => {
    if (message.type() === "error") externalErrors.push(`${label}: ${message.text().slice(0, 200)}`);
  });
}

async function signIn(page) {
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Work email").fill(process.env.RESOLVE_DEMO_EMAIL);
  await page.getByLabel("Password", { exact: true }).fill(process.env.RESOLVE_DEMO_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByRole("heading", { name: "Command Center" }).waitFor({ timeout: 30000 });
}

const desktop = await browser.newContext({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1 });
const page = await desktop.newPage();
attachErrorCapture(page, "app");

await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(800);
await page.screenshot({ path: path.join(OUT, "01-login.png"), fullPage: true });

await signIn(page);
await page.waitForTimeout(2500);
await page.screenshot({ path: path.join(OUT, "02-dashboard.png"), fullPage: true });

const shots = [
  ["03-invoices.png", "/invoices"],
  ["06-exceptions.png", "/exceptions"],
  ["07-case-management.png", IDS.case_id ? `/cases/${IDS.case_id}` : "/cases"],
  ["09-approvals.png", "/approvals"],
  ["10-analytics.png", "/analytics"],
  ["11-audit.png", "/audit"],
];
for (const [file, route] of shots) {
  await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2200);
  await page.screenshot({ path: path.join(OUT, file), fullPage: true });
}

if (IDS.invoice_id) {
  await page.goto(`${BASE}/invoices/${IDS.invoice_id}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2200);
  await page.screenshot({ path: path.join(OUT, "04-invoice-detail.png"), fullPage: true });
}

if (IDS.document_id) {
  await page.goto(`${BASE}/documents/${IDS.document_id}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2600);
  await page.screenshot({ path: path.join(OUT, "05-document-review.png"), fullPage: true });
}

if (IDS.case_id) {
  await page.goto(`${BASE}/cases/${IDS.case_id}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1800);
  const tab = page.getByRole("tab", { name: /investigation/i });
  if (await tab.count()) {
    await tab.first().click();
    await page.waitForTimeout(2600);
    await page.screenshot({ path: path.join(OUT, "08-ai-investigation.png"), fullPage: true });
  }
}

// Responsive + console checks at three viewports.
for (const [name, viewport] of [
  ["desktop", { width: 1440, height: 900 }],
  ["tablet", { width: 834, height: 1112 }],
  ["mobile", { width: 390, height: 844 }],
]) {
  const context = await browser.newContext({ viewport });
  const p = await context.newPage();
  attachErrorCapture(p, name);
  await signIn(p);
  for (const route of ["/", "/invoices", "/exceptions", "/cases", "/documents", "/approvals", "/analytics", "/settings"]) {
    await p.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded" });
    await p.waitForTimeout(900);
    const overflow = await p.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    uxResults.push({ viewport: name, route, overflow, ok: overflow <= 2 });
  }
  await context.close();
}

await desktop.close();

// ---------------------------------------------------------------- n8n
let n8nStatus = "ok";
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  const p = await context.newPage();
  attachExternalCapture(p, "n8n");
  await p.goto("http://127.0.0.1:5679", { waitUntil: "domcontentloaded" });
  await p.waitForTimeout(2000);
  const emailInput = p.locator('input[type="email"], input[placeholder*="Email" i]').first();
  if (await emailInput.count()) {
    await emailInput.fill(process.env.N8N_OWNER_EMAIL);
    await p.locator('input[type="password"]').first().fill(process.env.N8N_OWNER_PASSWORD);
    await p.getByRole("button", { name: /sign in|log in|continue/i }).first().click();
    await p.waitForTimeout(4000);
  }
  await p.goto("http://127.0.0.1:5679/home/workflows", { waitUntil: "domcontentloaded" });
  await p.waitForTimeout(3000);
  await p.screenshot({ path: path.join(OUT, "12-n8n-workflows.png"), fullPage: true });
  const workflow = p.getByText("RESOLVE A - New exception and case notification").first();
  if (await workflow.count()) {
    await workflow.click();
    await p.waitForTimeout(3500);
    await p.screenshot({ path: path.join(OUT, "12b-n8n-workflow-canvas.png"), fullPage: true });
  }
  await context.close();
} catch (error) {
  n8nStatus = `failed: ${String(error).slice(0, 200)}`;
}

// ------------------------------------------------------------- grafana
let grafanaStatus = "ok";
try {
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const p = await context.newPage();
  await p.goto("http://127.0.0.1:3101/login", { waitUntil: "domcontentloaded" });
  await p.waitForTimeout(2000);
  const user = p.locator('input[name="user"]').first();
  if (await user.count()) {
    await user.fill(process.env.GRAFANA_ADMIN_USER ?? "admin");
    await p.locator('input[name="password"]').first().fill(process.env.GRAFANA_PASSWORD);
    await p.getByRole("button", { name: /log in/i }).first().click();
    await p.waitForTimeout(3000);
  }
  for (const [file, uid] of [
    ["13-grafana-overview.png", "resolve-overview"],
    ["14-grafana-business.png", "resolve-business"],
    ["15-grafana-ai.png", "resolve-ai-documents"],
  ]) {
    await p.goto(`http://127.0.0.1:3101/d/${uid}?kiosk`, { waitUntil: "domcontentloaded" });
    await p.waitForTimeout(4500);
    await p.screenshot({ path: path.join(OUT, file), fullPage: true });
  }
  await context.close();
} catch (error) {
  grafanaStatus = `failed: ${String(error).slice(0, 200)}`;
}

await browser.close();

const failures = uxResults.filter((r) => !r.ok);
const report = [
  "# Portfolio capture QA",
  "",
  `- App: ${BASE}`,
  `- Viewports tested: desktop 1440x900, tablet 834x1112, mobile 390x844`,
  `- Routes per viewport: 8`,
  `- Horizontal overflow failures: ${failures.length}`,
  `- App console/page errors captured: ${consoleErrors.length}`,
  `- External UI console messages (n8n/grafana, non-blocking): ${externalErrors.length}`,
  `- n8n capture: ${n8nStatus}`,
  `- Grafana capture: ${grafanaStatus}`,
  "",
  "## Overflow results",
  "",
  "| Viewport | Route | Overflow px | Status |",
  "| --- | --- | --- | --- |",
  ...uxResults.map((r) => `| ${r.viewport} | ${r.route} | ${r.overflow} | ${r.ok ? "PASS" : "FAIL"} |`),
  "",
  "## Console errors",
  "",
  consoleErrors.length ? consoleErrors.map((e) => `- ${e}`).join("\n") : "None captured.",
  "",
  "## External UI console messages",
  "",
  externalErrors.length ? externalErrors.map((e) => `- ${e}`).join("\n") : "None captured.",
  "",
].join("\n");

await writeFile(path.join(QA, "UX_REPORT.md"), report, "utf-8");
console.log(`screenshots -> ${OUT}`);
console.log(`overflow failures: ${failures.length}, console errors: ${consoleErrors.length}`);
console.log(`n8n: ${n8nStatus}; grafana: ${grafanaStatus}`);
process.exit(failures.length || consoleErrors.length ? 1 : 0);
