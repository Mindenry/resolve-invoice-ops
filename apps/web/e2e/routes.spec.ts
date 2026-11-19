import { expect, test, type Page } from "@playwright/test";

const email = process.env.RESOLVE_DEMO_EMAIL ?? "admin@example.com";
const password = process.env.RESOLVE_DEMO_PASSWORD ?? "";
if (!password) {
  throw new Error("RESOLVE_DEMO_PASSWORD is required; read var/secrets/demo-credentials.txt");
}

async function signIn(page: Page, user = email) {
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  await page.getByLabel("Work email").fill(user);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Command Center" })).toBeVisible({ timeout: 20_000 });
}

const ROUTES: Array<[string, string]> = [
  ["Command Center", "/"],
  ["Exception Queue", "/exceptions"],
  ["Cases", "/cases"],
  ["Documents", "/documents"],
  ["Invoices", "/invoices"],
  ["Vendors", "/vendors"],
  ["Purchase Orders", "/purchase-orders"],
  ["Approval Center", "/approvals"],
  ["Integration Hub", "/integrations"],
  ["Workflows", "/workflows"],
  ["AI Evaluation", "/evaluation"],
  ["Analytics", "/analytics"],
  ["Audit Logs", "/audit"],
  ["Settings", "/settings"],
];

test("every navigation item opens a real, error-free page", async ({ page }) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(String(error)));

  await signIn(page);

  for (const [label, path] of ROUTES) {
    const link = page.locator("aside nav").getByRole("link", { name: label, exact: true });
    await expect(link, `sidebar link ${label}`).toBeVisible();
    await link.click();
    await expect(page).toHaveURL(path === "/" ? /\/$/ : new RegExp(`${path.replace("/", "\\/")}$`));
    await expect(page.getByRole("heading").first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Something went wrong")).toHaveCount(0);
  }

  expect(consoleErrors, consoleErrors.join("\n")).toEqual([]);
});

test("case list pagination loads the next page of real records", async ({ page }) => {
  await signIn(page);
  await page.locator("aside nav").getByRole("link", { name: "Cases", exact: true }).click();
  await expect(page.locator("tbody tr").first()).toBeVisible();

  const next = page.getByRole("button", { name: "Next page" });
  await expect(next).toBeVisible();
  if (await next.isDisabled()) {
    test.skip(true, "Demo data fits on a single page");
  }
  await next.click();
  await expect(page.getByText(/^2 \/ \d+$/)).toBeVisible({ timeout: 10_000 });
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await page.getByRole("button", { name: "Previous page" }).click();
  await expect(page.getByText(/^1 \/ \d+$/)).toBeVisible();
});

test("viewer role gets read-only settings", async ({ page }) => {
  await signIn(page, "viewer@example.com");
  await page.locator("aside nav").getByRole("link", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();

  const save = page.getByRole("button", { name: "Save" }).first();
  await expect(save).toBeDisabled();
  const nameInput = page.getByLabel("Name").first();
  await expect(nameInput).toBeDisabled();
});

test("a failing API renders the error state and can retry", async ({ page }) => {
  await page.route("**/api/v1/analytics/overview*", async (route) => {
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ error: { code: "internal_error", message: "Simulated outage" } }),
    });
  });

  await signIn(page);
  await expect(page.getByText("Something went wrong")).toBeVisible({ timeout: 20_000 });
  await page.unroute("**/api/v1/analytics/overview*");
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("Total exceptions")).toBeVisible({ timeout: 20_000 });
});
