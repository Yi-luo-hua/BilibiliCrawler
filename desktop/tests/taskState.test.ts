import assert from "node:assert/strict";
import test from "node:test";

import { initialTaskState, taskReducer } from "../src/state/taskState.ts";

test("task reducer expresses the complete start, run, stop and finish lifecycle", () => {
  const starting = taskReducer(initialTaskState, {
    type: "start.requested",
    mode: "analysis",
  });
  assert.deepEqual(starting, {
    phase: "starting",
    mode: "analysis",
    progressPercent: 0,
    progressStatus: "分析进度",
    summary: "任务启动中",
  });

  const running = taskReducer(starting, {
    type: "progress",
    status: "running",
    mode: "analysis",
    percent: 25,
  });
  assert.equal(running.phase, "running");
  assert.equal(running.progressPercent, 25);
  assert.equal(running.summary, "任务运行中");

  const stopping = taskReducer(running, { type: "stop.requested" });
  assert.equal(stopping.phase, "stopping");
  assert.equal(stopping.progressStatus, "正在停止");

  const finished = taskReducer(stopping, {
    type: "finished",
    mode: "analysis",
    count: 18,
  });
  assert.equal(finished.phase, "succeeded");
  assert.equal(finished.progressPercent, 100);
  assert.equal(finished.summary, "分析完成：18 条");
});
