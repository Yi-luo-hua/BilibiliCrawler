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

test("a cancelled analysis becomes restartable without being marked failed", () => {
  const running = taskReducer(initialTaskState, {
    type: "session.running",
    mode: "analysis",
  });
  const stopping = taskReducer(running, { type: "stop.requested" });

  const cancelled = taskReducer(stopping, {
    type: "cancelled",
    mode: "analysis",
  });

  assert.equal(cancelled.phase, "cancelled");
  assert.equal(cancelled.progressStatus, "分析已停止");
  assert.equal(cancelled.summary, "分析已停止");

  const afterIdle = taskReducer(cancelled, {
    type: "progress",
    status: "idle",
    mode: "analysis",
    percent: 100,
  });
  assert.equal(afterIdle.phase, "cancelled");

  const restarted = taskReducer(afterIdle, {
    type: "start.requested",
    mode: "analysis",
  });
  assert.equal(restarted.phase, "starting");
});

test("waiting and retry messages refresh without increasing the completed percentage", () => {
  const running = taskReducer(initialTaskState, { type: "session.running", mode: "analysis" });
  const waiting = taskReducer(running, {
    type: "analysis.progress", percent: 45,
    message: "第 1/2 批 · 已用时 1s · 等待 LLM 响应 · 请求 1/3（重试 0）",
  });
  const retrying = taskReducer(waiting, {
    type: "analysis.progress", percent: 45,
    message: "第 1/2 批 · 已用时 2s · LLM_UNAVAILABLE · 退避中（间隔 1s）",
  });
  assert.equal(retrying.progressPercent, waiting.progressPercent);
  assert.equal(retrying.phase, "running");
  assert.match(retrying.progressStatus, /退避中/);
  const legacy = taskReducer(retrying, { type: "analysis.progress", percent: 80 });
  assert.equal(legacy.progressStatus, retrying.progressStatus);
  assert.equal(legacy.progressPercent, 80);
});
