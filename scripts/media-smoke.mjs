import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const { chromium } = await import(
  process.env.PLAYWRIGHT_MODULE
    ? pathToFileURL(process.env.PLAYWRIGHT_MODULE).href
    : "playwright"
);
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
await mkdir("test-results", { recursive: true });
try {
  await page.goto(process.env.LOOKOUT_URL || "http://127.0.0.1:5173", {
    waitUntil: "networkidle",
  });
  // Generate consent-free synthetic input to exercise the actual video path.
  // This is a media/transport test, not a person-recognition benchmark.
  const bytes = await page.evaluate(async () => {
    const canvas = document.createElement("canvas");
    canvas.width = 320;
    canvas.height = 240;
    const context = canvas.getContext("2d");
    const stream = canvas.captureStream(12);
    const recorder = new MediaRecorder(stream, {
      mimeType: "video/webm;codecs=vp8",
    });
    const chunks = [];
    recorder.ondataavailable = (e) => chunks.push(e.data);
    const done = new Promise(
      (resolve) =>
        (recorder.onstop = async () =>
          resolve(
            Array.from(new Uint8Array(await new Blob(chunks).arrayBuffer())),
          )),
    );
    let frame = 0;
    const interval = setInterval(() => {
      context.fillStyle = "#202125";
      context.fillRect(0, 0, 320, 240);
      context.fillStyle = "#c4c5c9";
      context.fillRect(20 + (frame % 180), 100, 25, 25);
      context.font = "14px sans-serif";
      context.fillText("SYNTHETIC TRANSPORT TEST", 20, 40);
      frame++;
    }, 80);
    recorder.start();
    await new Promise((resolve) => setTimeout(resolve, 5000));
    recorder.stop();
    clearInterval(interval);
    stream.getTracks().forEach((track) => track.stop());
    return done;
  });
  await writeFile("test-results/transport.webm", Buffer.from(bytes));
  await page
    .locator("input[type=file]")
    .setInputFiles("test-results/transport.webm");
  await page.waitForFunction(
    async () => {
      const response = await fetch("/api/state");
      const state = await response.json();
      return (
        state.session.source_type === "recorded" &&
        state.session.status === "active" &&
        state.camera.last_frame_at
      );
    },
    { timeout: 15000 },
  );
  const state = await page.evaluate(async () =>
    (await fetch("/api/state")).json(),
  );
  assert.equal(state.session.calls_armed, false);
  assert.equal(state.analysis.health.review, "disabled");
  await page.screenshot({ path: "test-results/upload.png", fullPage: true });
  await page
    .getByRole("button", { name: "Pause playback", exact: true })
    .click();
  const paused = await page.evaluate(async () =>
    (await fetch("/api/state")).json(),
  );
  assert.equal(paused.session.status, "paused");
  assert.deepEqual(errors, []);
  console.log(
    "Passed: synthetic WebM upload, decoding, real sampled-frame ingestion, analysis status, calls disarmed, pause; no browser exceptions.",
  );
} finally {
  await browser.close();
}
