// SRC-5 acceptance in a real browser against the running app (npm start). Chromium's fake camera
// stands in for the device camera, so no real camera is opened. Checks that the main camera view
// shows a live picture on connect, after a round trip through Settings, and after selecting
// another camera and coming back.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const { chromium } = await import(
  process.env.PLAYWRIGHT_MODULE
    ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href
    : "playwright"
);
const base = process.env.LOOKOUT_URL || "http://127.0.0.1:5173";
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined,
  args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
});
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ["camera"] });
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await mkdir("test-results", { recursive: true });

// The main camera view's <video> has a live camera stream and its picture is advancing.
async function livePicture(step) {
  const start = Date.now();
  let last;
  while (Date.now() - start < 6000) {
    last = await page.evaluate(async () => {
      const video = [...document.querySelectorAll(".camera-stage video")].find((v) => v.getBoundingClientRect().width > 0);
      if (!video) return { video: false };
      const before = video.currentTime;
      await new Promise((resolve) => setTimeout(resolve, 400));
      return {
        video: true,
        stream: !!video.srcObject && video.srcObject.active,
        width: video.videoWidth,
        advancing: video.currentTime > before,
      };
    });
    if (last.video && last.stream && last.width > 0 && last.advancing) return;
    await page.waitForTimeout(200);
  }
  await page.screenshot({ path: `test-results/webcam-${step}.png` });
  assert.fail(`${step}: no live camera picture (${JSON.stringify(last)})`);
}

await page.goto(base, { waitUntil: "load" });
await page.getByRole("button", { name: "Focus view" }).click();
await page.getByRole("button", { name: /Connect a camera/ }).click();
await page.locator("button.source-option", { hasText: "Use this device" }).click();
await livePicture("connect");
console.log("ok  live picture after connecting the device camera");

await page.getByLabel("Account menu").click();
await page.getByRole("button", { name: "Settings" }).click();
await page.getByRole("button", { name: "NestWatch monitor" }).click();
await livePicture("after-settings");
console.log("ok  live picture after a round trip through Settings");

await page.getByRole("button", { name: /^Focus Gas station/ }).click();
await page.getByRole("button", { name: /^Focus Toddler room/ }).click();
await livePicture("after-camera-switch");
console.log("ok  live picture after selecting another camera and coming back");

assert.deepEqual(errors, [], `page errors: ${errors.join("; ")}`);
await browser.close();
console.log("webcam smoke passed");
