import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";
const source = await readFile(new URL("../src/timecode.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const { parsePlaybackTime, formatPlaybackTime } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
test("accepts seconds, minutes and hours", () => {
  for (const [text, seconds] of [["45", 45], ["1:05", 65], ["01:05", 65], ["1:02:03", 3723], ["0", 0]]) assert.equal(parsePlaybackTime(text, 8000), seconds);
});
test("rejects malformed input and invalid fields", () => {
  for (const text of ["", " ", " 45", "45 ", "1.5", "-1", "1:5", "1:60", "1:02:60", "1:02:03:04", "2 PM", "NaN", "Infinity"]) assert.equal(parsePlaybackTime(text, 8000), null, text);
});
test("clamps valid seeks to duration", () => {
  assert.equal(parsePlaybackTime("999", 120), 120);
  assert.equal(parsePlaybackTime("1:02:03", 120), 120);
  assert.equal(parsePlaybackTime("1", 0), 0);
});
test("formats hours based on duration", () => {
  assert.equal(formatPlaybackTime(65, 120), "01:05");
  assert.equal(formatPlaybackTime(65, 3600), "0:01:05");
  assert.equal(formatPlaybackTime(3723, 7200), "1:02:03");
});
