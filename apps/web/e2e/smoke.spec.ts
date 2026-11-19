import { expect, test, type Page } from "@playwright/test";

const email = process.env.RESOLVE_DEMO_EMAIL ?? "admin@example.com";
const password = process.env.RESOLVE_DEMO_PASSWORD ?? "";
if (!password) {
  throw new Error("RESOLVE_DEMO_PASSWORD is required; read var/secrets/demo-credentials.txt");
}

async function signIn(page: Page) {
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Command Center" })).toBeVisible({ timeout: 20_000 });
}

test("login reaches the command center with live metrics", async ({ page }) => {
  await signIn(page);
  await expect(page.getByText("Total exceptions")).toBeVisible();
  await expect(page.getByText("Open cases")).toBeVisible();
  await expect(page.getByText("Exception trend")).toBeVisible();
});

test("exception queue supports filtering and opening evidence", async ({ page }) => {
  await signIn(page);
  await page.getByRole("link", { name: "Exception Queue" }).click();
  await expect(page.getByRole("heading", { name: "Exception Queue" })).toBeVisible();
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await page.locator("tbody tr").first().click();
  await expect(page.getByText("Severity").first()).toBeVisible();
  await expect(page.getByText("Evidence").first()).toBeVisible();
});

test("case workspace runs an investigation with validated evidence", async ({ page }) => {
  await signIn(page);
  await page.getByRole("link", { name: "Cases" }).click();
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await page.locator("tbody tr").first().click();
  await expect(page.getByRole("tab", { name: /AI Investigation/ })).toBeVisible();
  await page.getByRole("tab", { name: /AI Investigation/ }).click();
  await page.getByRole("button", { name: "Run investigation" }).click();
  await expect(page.locator("p.eyebrow").filter({ hasText: /^Evidence$/ })).toBeVisible({ timeout: 25_000 });
  await expect(page.getByText(/validated/).first()).toBeVisible({ timeout: 15_000 });
});

test("document review exposes extracted fields and source text", async ({ page }) => {
  await signIn(page);
  await page.getByRole("link", { name: "Documents" }).click();
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await page.locator("tbody tr").first().click();
  await expect(page.getByText("Source document")).toBeVisible();
});

test("approval center shows pending decisions", async ({ page }) => {
  await signIn(page);
  await page.getByRole("link", { name: "Approval Center" }).click();
  await expect(page.getByRole("heading", { name: "Approval Center" })).toBeVisible();
});

test("Thai locale and dark theme persist", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "EN", exact: true }).click();
  await page.getByText("ไทย").click();
  await expect(page.getByRole("link", { name: "คิวข้อยกเว้น" })).toBeVisible();
  await page.getByRole("button", { name: "ธีม" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});
