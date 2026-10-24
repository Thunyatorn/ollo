// SRC-4 acceptance in a real browser against the running app (npm start). A generated MJPEG
// stream is served over local HTTP, so the server's real OpenCV capture path reads it; no camera
// is opened. Checks: the source dialog, the live picture, analysis with no dashboard tab open,
// a reload returning to the camera, and `offline` within 3 s of the stream stalling.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { createServer } from "node:http";
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
});
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const errors = [];
const watch = (page) => page.on("pageerror", (error) => errors.push(error.message));
await mkdir("test-results", { recursive: true });
// GET /api/state from loopback also sets the operator session cookie for these requests.
const getState = async () => (await context.request.get(`${base}/api/state`)).json();
const resetSession = async () => {
  await getState();
  await context.request.post(`${base}/api/session/reset`);
};
async function waitFor(check, timeout, what) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (await check()) return (Date.now() - start) / 1000;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out after ${timeout} ms waiting for ${what}`);
}

// A 1280×720 synthetic camera at 15 fps; `stalled` keeps connections open but stops sending.
let stalled = false;
const clients = new Set();
let frames = [];
const camera = createServer((req, res) => {
  res.writeHead(200, {
    "Content-Type": "multipart/x-mixed-replace; boundary=frame",
    "Cache-Control": "no-store",
  });
  clients.add(res);
  req.on("close", () => clients.delete(res));
});
let index = 0;
const pump = setInterval(() => {
  if (stalled || !frames.length) return;
  const jpeg = frames[index++ % frames.length];
  for (const res of clients)
    res.write(
      Buffer.concat([
        Buffer.from(`--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ${jpeg.length}\r\n\r\n`),
        jpeg,
        Buffer.from("\r\n"),
      ]),
    );
}, 1000 / 15);
await new Promise((resolve) => camera.listen(0, "127.0.0.1", resolve));
const streamUrl = `http://127.0.0.1:${camera.address().port}/stream.mjpg`;

try {
  await resetSession();
  let page = await context.newPage();
  watch(page);
  // Not "networkidle": a dashboard showing a server camera always has a frame request open.
  await page.goto(base, { waitUntil: "load" });
  frames = (
    await page.evaluate(() => {
      const canvas = Object.assign(document.createElement("canvas"), { width: 1280, height: 720 });
      const context = canvas.getContext("2d");
      return Array.from({ length: 30 }, (_, i) => {
        context.fillStyle = "#202125";
        context.fillRect(0, 0, 1280, 720);
        context.fillStyle = "#c4c5c9";
        context.fillRect(80 + i * 30, 320, 90, 90);
        context.font = "40px sans-serif";
        context.fillText("SYNTHETIC SERVER CAMERA TEST", 80, 120);
        return canvas.toDataURL("image/jpeg", 0.8).split(",")[1];
      });
    })
  ).map((b64) => Buffer.from(b64, "base64"));

  // Source dialog: a file path is refused with the server's reason; the stream URL connects.
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Manage source", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Connect video source" });
  const input = dialog.getByRole("textbox", { name: "Camera index or stream URL" });
  await input.fill("file:///etc/passwd");
  await dialog.getByRole("button", { name: "Connect", exact: true }).click();
  await dialog.getByRole("alert").filter({ hasText: /webcam index/i }).waitFor();
  assert.equal((await getState()).camera.capture, null, "A refused source opens nothing");
  await input.fill(streamUrl);
  await dialog.getByRole("button", { name: "Connect", exact: true }).click();
  await dialog.waitFor({ state: "detached" });
  await page.getByRole("button", { name: "Monitor", exact: true }).click();
  await page.getByText("SERVER CAMERA", { exact: true }).waitFor();
  const picture = page.getByRole("img", { name: "Server camera picture" });
  await picture.waitFor();
  await waitFor(async () => (await getState()).camera.analysis_fps >= 8, 15000, "analysis at 8+ fps");
  assert.equal(await picture.evaluate((img) => img.naturalWidth), 640);
  let state = await getState();
  assert.equal(state.session.source_type, "server_camera");
  assert.equal(state.camera.capture.status, "live");
  assert.equal(state.camera.health, "active");
  await page.screenshot({ path: "test-results/server-camera.png" });

  // No dashboard tab at all: the server keeps analyzing at the capture rate.
  await page.close();
  const rates = [];
  for (let i = 0; i < 8; i++) {
    await new Promise((resolve) => setTimeout(resolve, 500));
    rates.push((await getState()).camera.analysis_fps);
  }
  assert.ok(Math.min(...rates) >= 10, `Analysis with no tab open: ${rates.join(", ")} fps`);

  // A reload returns to the server camera view.
  page = await context.newPage();
  watch(page);
  await page.goto(base, { waitUntil: "load" });
  await page.getByText("SERVER CAMERA", { exact: true }).waitFor();
  await page.getByRole("img", { name: "Server camera picture" }).waitFor();

  // The stream stalls with the connection still open: offline within 3 s, then back.
  stalled = true;
  const offlineAfter = await waitFor(
    async () => (await getState()).camera.health === "offline",
    5000,
    "offline",
  );
  assert.ok(offlineAfter < 3, `Offline after ${offlineAfter} s`);
  await page.getByText("Reconnecting automatically", { exact: false }).waitFor();
  await page.screenshot({ path: "test-results/server-camera-offline.png" });
  stalled = false;
  const onlineAfter = await waitFor(
    async () => (await getState()).camera.health === "active",
    10000,
    "active again",
  );
  state = await getState();
  const types = state.events.map((e) => e.type);
  assert.ok(types.includes("camera_offline") && types.includes("camera_online"));

  // Reset releases the camera.
  await resetSession();
  assert.equal((await getState()).camera.capture, null);
  assert.deepEqual(errors, [], "No browser runtime exceptions");
  console.log(
    `Passed: server camera via dialog (file path refused), live 640 px picture, analysis with no tab open (${Math.min(...rates)}–${Math.max(...rates)} fps), reload returns to the camera, offline ${offlineAfter.toFixed(1)} s after a stall, active again ${onlineAfter.toFixed(1)} s after resuming, reset releases the camera; no runtime exceptions.`,
  );
} finally {
  // Never leave a server camera running for the next suite, even after a failure.
  await resetSession().catch(() => {});
  clearInterval(pump);
  for (const res of clients) res.destroy();
  camera.close();
  await browser.close();
}
