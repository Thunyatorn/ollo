// SRC-6 "the picture waits for the analysis" in a real browser against the running app (npm start).
// The playhead reply is intercepted: analysis reports itself behind for the first 2.5 s, then caught up.
// Checks that playback holds with "Analyzing…" shown, then resumes on its own once analysis catches up.
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const { chromium } = await import(
  process.env.PLAYWRIGHT_MODULE ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href : "playwright"
);
const base = process.env.LOOKOUT_URL || "http://127.0.0.1:5173";
const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await mkdir("test-results", { recursive: true });

try {
  await page.goto(base, { waitUntil: "load" });
  await writeFile("test-results/catchup.webm", Buffer.from(await page.evaluate(async () => {
    const canvas = Object.assign(document.createElement("canvas"), { width: 320, height: 240 });
    const context = canvas.getContext("2d");
    const recorder = new MediaRecorder(canvas.captureStream(12), { mimeType: "video/webm;codecs=vp8" });
    const chunks = [];
    recorder.ondataavailable = (e) => chunks.push(e.data);
    const done = new Promise((resolve) => (recorder.onstop = async () => resolve(Array.from(new Uint8Array(await new Blob(chunks).arrayBuffer())))));
    let n = 0;
    const timer = setInterval(() => { context.fillStyle = `hsl(${(n++ * 7) % 360} 40% 40%)`; context.fillRect(0, 0, 320, 240); }, 80);
    recorder.start();
    await new Promise((r) => setTimeout(r, 9000));
    recorder.stop(); clearInterval(timer);
    return done;
  })));

  let first = 0;
  await page.route(/\/api\/playhead$/, async (route) => {
    const body = JSON.parse(route.request().postData() || "{}");
    first ||= Date.now();
    const behind = Date.now() - first < 2500;
    await route.fulfill({ contentType: "application/json", body: JSON.stringify({ analyzed_to_ms: behind ? -1 : body.media_time_ms, overlays: [] }) });
  });
  await page.locator("input[type=file]").first().setInputFiles("test-results/catchup.webm");

  const video = () => page.evaluate(() => { const v = document.querySelector(".camera-stage video"); return { paused: v.paused, t: v.currentTime }; });
  await page.getByText("Analyzing", { exact: false }).first().waitFor({ timeout: 6000 });
  const held = await video();
  assert.equal(held.paused, true, "playback holds while analysis is behind");
  console.log(`ok  playback held at ${held.t.toFixed(2)} s with "Analyzing…" shown`);

  await page.waitForFunction(() => !document.body.innerText.includes("Analyzing"), null, { timeout: 8000 });
  const a = await video();
  await page.waitForTimeout(800);
  const b = await video();
  assert.equal(b.paused, false, "playback resumed");
  assert.ok(b.t > a.t, "video time advances again");
  console.log(`ok  playback resumed once analysis caught up (${a.t.toFixed(2)} → ${b.t.toFixed(2)} s)`);
  assert.deepEqual(errors, []);
  console.log("catch-up smoke passed");
} finally {
  await browser.close();
}
