import { expect, test } from "@playwright/test";

test("login page exposes the company Microsoft sign-in", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByText("Meeting Intelligence", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in with Microsoft" })).toBeVisible();
  await expect(page.getByText("Only @taxconsulting.co.za accounts are accepted.")).toBeVisible();
});

test("unauthenticated dashboard is protected", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
});

test("Microsoft sign-in starts the real Entra authorization flow", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Sign in with Microsoft" }).click();
  await page.waitForURL((url) => url.hostname === "login.microsoftonline.com", {
    timeout: 30_000,
  });
  expect(new URL(page.url()).hostname).toBe("login.microsoftonline.com");
});
