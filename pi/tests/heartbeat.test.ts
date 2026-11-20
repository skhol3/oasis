import { test } from "node:test";
import assert from "node:assert/strict";
import { setTimeout as sleep } from "node:timers/promises";
import { withHeartbeat } from "../lib/heartbeat.ts";

test("withHeartbeat beats while the work runs and returns its result", async () => {
  const beats: number[] = [];
  const result = await withHeartbeat(async () => { await sleep(70); return "done"; }, (s) => beats.push(s), 20);
  assert.equal(result, "done");
  assert.ok(beats.length >= 2 && beats.length <= 3, `beats: ${beats.length}`);
  assert.ok(beats.every((seconds) => seconds === 0), "elapsed time is reported in whole seconds");
  const seen = beats.length;
  await sleep(60);
  assert.equal(beats.length, seen, "no beat after the work ended");
});

test("withHeartbeat stops beating and rethrows when the work fails", async () => {
  let beats = 0;
  const failure = new Error("boom");
  await assert.rejects(
    withHeartbeat(async () => { await sleep(30); throw failure; }, () => { beats++; }, 10),
    (error) => error === failure,
  );
  const seen = beats;
  assert.ok(seen >= 1);
  await sleep(40);
  assert.equal(beats, seen, "no beat after the failure");
});

test("withHeartbeat does not beat for work that ends before the first interval", async () => {
  let beats = 0;
  assert.equal(await withHeartbeat(async () => 7, () => { beats++; }, 20), 7);
  await sleep(40);
  assert.equal(beats, 0);
});
