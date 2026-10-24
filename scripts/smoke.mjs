import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const modulePath = process.env.PLAYWRIGHT_MODULE;
const { chromium } = await import(
  modulePath ? pathToFileURL(modulePath).href : "playwright"
);
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined,
});
const page = await browser.newPage({ viewport: { width: 1536, height: 1024 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const base = process.env.LOOKOUT_URL || "http://127.0.0.1:5173";
await mkdir("test-results", { recursive: true });
try {
  await page.goto(base, { waitUntil: "networkidle" });
  await page.evaluate(() => fetch("/api/session/reset", { method: "POST" }));
  await page.getByText("Things are chilling", { exact: true }).waitFor();
  assert.equal(await page.locator(".sidebar").count(), 0);
  await page.getByRole("combobox", { name: "Select camera" }).selectOption("1");
  await page.getByText("No video source connected").waitFor();
  await page.getByRole("combobox", { name: "Select camera" }).selectOption("0");
  await page.screenshot({ path: "test-results/desktop.png", fullPage: true });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
    "Desktop must not overflow horizontally",
  );

  await page.getByRole("button", { name: "Pause playback", exact:true }).click();
  await page
    .getByRole("slider", { name: "Video playback position" })
    .fill("30");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: /Doorway crossing/ }).click();
  await page
    .getByRole("button", { name: "Acknowledge", exact: true })
    .first()
    .waitFor();
  await page.screenshot({ path: "test-results/incident.png", fullPage: true });
  await page
    .getByRole("button", { name: "Acknowledge", exact: true })
    .first()
    .click();
  await page
    .getByRole("button", { name: "Resolve incident", exact: true })
    .click();

  await page.locator(".trace-status.resolved").waitFor();
  const marker = page.getByRole("button", {
    name: /Jump to Restricted-area activity at 00:30/,
  });
  await marker.waitFor();
  await marker.click();
  assert.equal(
    Number(
      await page
        .getByRole("slider", { name: "Video playback position" })
        .inputValue(),
    ),
    30,
  );
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("heading", { name: "Workspace settings" }).waitFor();
  await page
    .getByRole("button", { name: "Manage source", exact: true })
    .click();
  await page.getByRole("dialog", { name: "Connect video source" }).waitFor();
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.getByRole("button", { name: "Monitoring", exact: true }).click();
  await page.getByRole("button", { name: "Save changes" }).click();
  await page.getByRole("button", { name: "Monitor", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "test-results/mobile.png", fullPage: true });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
    "Mobile must not overflow horizontally",
  );
  const resolvedId = await page.evaluate(async () => {
    const s = await (await fetch("/api/state")).json();
    return s.incidents.find((i) => i.status === "resolved")?.id;
  });
  await page.goto(`${base}/respond/${resolvedId}`, {
    waitUntil: "networkidle",
  });
  await page
    .getByText("Incident resolved. Thank you for responding.")
    .waitFor();
  assert.equal(
    await page
      .getByRole("button", { name: "Mark resolved", exact: true })
      .count(),
    0,
  );
  const distressId = await page.evaluate(async () => {
    const s = await (
      await fetch("/api/demo/scenario", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario: "distress" }),
      })
    ).json();
    return s.incidents.find((i) => i.kind === "distress" && i.status === "open")
      ?.id;
  });
  await page.goto(`${base}/respond/${distressId}`, {
    waitUntil: "networkidle",
  });
  await page
    .getByRole("button", { name: "I cannot respond", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Backup responder requested", exact: true })
    .waitFor();
  await page.screenshot({
    path: "test-results/mobile-response.png",
    fullPage: true,
  });
  await page.goto(base, { waitUntil: "networkidle" });
  await page.evaluate(() => fetch("/api/session/reset", { method: "POST" }));
  await page.getByText("Things are chilling", { exact: true }).waitFor();
  assert.deepEqual(errors, [], "No browser runtime exceptions");
  console.log(
    "Passed: sidebar-free layout, camera dropdown, timed incident marker, trace acknowledgment and resolution, settings, source dialog, mobile layout, resolved mobile state, backup escalation; no runtime exceptions.",
  );
} finally {
  await browser.close();
}
