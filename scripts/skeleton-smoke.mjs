// UI-6 skeleton overlay in a real browser, with the running server's caregiver roles. Overlays are injected by intercepting the
// frame endpoint (with the posted epoch and media time echoed back), so this checks rendering
// only, not detection accuracy. Run with the app running: node scripts/design-smoke.mjs
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const modulePath = process.env.PLAYWRIGHT_MODULE;
const { chromium } = await import(
  modulePath ? pathToFileURL(modulePath).href : "playwright"
);
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined,
});
const base = process.env.LOOKOUT_URL || "http://127.0.0.1:5173";
const page = await browser.newPage({ viewport: { width: 1536, height: 1024 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await mkdir("test-results", { recursive: true });
const api = (path, method = "POST", body) =>
  page.evaluate(
    async ({ path, method, body }) =>
      (
        await fetch(path, {
          method,
          headers: { "Content-Type": "application/json" },
          body: body === undefined ? undefined : JSON.stringify(body),
        })
      ).json(),
    { path, method, body },
  );
// Top-down test calibration: the whole frame maps to an 8 m × 8 m floor.
const TOP = [
  [0.1, 0.1],
  [0.9, 0.1],
  [0.9, 0.9],
  [0.1, 0.9],
].map(([u, v]) => ({ image: [u, v], floor: [8 * u, 8 * v] }));
// COCO pose for one standing person with confident keypoints.
const STAND = [
  [0, 0.08], [-0.02, 0.06], [0.02, 0.06], [-0.04, 0.07], [0.04, 0.07],
  [-0.12, 0.2], [0.12, 0.2], [-0.15, 0.35], [0.15, 0.35], [-0.16, 0.48],
  [0.16, 0.48], [-0.08, 0.52], [0.08, 0.52], [-0.08, 0.75], [0.08, 0.75],
  [-0.08, 0.98], [0.08, 0.98],
];
const person = (epoch, media_time_ms) => {
  const x0 = 0.4, top = 0.2, h = 0.6;
  const keypoints = STAND.map(([dx, dy]) => [x0 + (dx * h * 9) / 16, top + dy * h, 0.9]);
  return {
    id: "person-1", label: "Person 1 · pose tracking", track_id: 1,
    x: x0 - 0.08, y: top, width: 0.16, height: h, keypoints,
    foot: [x0, top + 0.98 * h], floor: [8 * x0, 8 * (top + 0.98 * h)],
    approach: {
      p: 0.8, eta_s: 1.4, warning: true, started: false,
      path: [[x0, 0.79], [0.7, 0.79]], floor_path: [[3.2, 6.3], [5.6, 6.3]], zone: "test zone",
    },
    epoch, frame_seq: 1, media_time_ms,
  };
};
try {
  await page.goto(base, { waitUntil: "load" });
  const state = await api("/api/state", "GET");
  console.log("caregiver roles from the server:", state.caregivers.map((c) => c.role).join(", "));
  await writeFile("test-results/skeleton.webm", Buffer.from(await page.evaluate(async () => {
    const canvas = Object.assign(document.createElement("canvas"), { width: 320, height: 240 });
    const context = canvas.getContext("2d");
    const recorder = new MediaRecorder(canvas.captureStream(12), { mimeType: "video/webm;codecs=vp8" });
    const chunks = [];
    recorder.ondataavailable = (e) => chunks.push(e.data);
    const done = new Promise((resolve) => (recorder.onstop = async () =>
      resolve(Array.from(new Uint8Array(await new Blob(chunks).arrayBuffer())))));
    const timer = setInterval(() => { context.fillStyle = "#202125"; context.fillRect(0, 0, 320, 240); }, 80);
    recorder.start();
    await new Promise((r) => setTimeout(r, 6000));
    recorder.stop(); clearInterval(timer);
    return done;
  })));
  // One tracked person in every frame response (rendering only, not detection).
  await page.route(/\/api\/(frames|playhead)$/, async (route) => {   // recordings send the playhead (SRC-6)
    const body = JSON.parse(route.request().postData() || "{}");
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ accepted: true, overlays: [person(body.epoch, body.media_time_ms)] }) });
  });
  await page.locator("input[type=file]").first().setInputFiles("test-results/skeleton.webm");
  await page.locator(".skeleton line").first().waitFor({ timeout: 10000 });
  assert.ok((await page.locator(".skeleton line").count()) >= 12, "Skeleton limbs drawn");
  await page.getByText(/Person 1/).first().waitFor();
  await page.screenshot({ path: "test-results/skeleton.png" });
  assert.deepEqual(errors, []);
  console.log("Passed: skeleton and track label drawn over an uploaded video, with the server's caregiver roles.");
} finally {
  await browser.close();
}
