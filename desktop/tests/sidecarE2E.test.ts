import assert from "node:assert/strict";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import readline from "node:readline";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { SidecarClient } from "../src/lib/sidecarClient.ts";
import type {
  SidecarBroadcastEvent,
  SidecarMessage,
  SidecarRequest,
} from "../src/types.ts";

const repoRoot = fileURLToPath(new URL("../../", import.meta.url));
const fixturePath = path.join(
  repoRoot,
  "desktop",
  "tests",
  "fixtures",
  "sidecar_e2e.py",
);

function pythonExecutable(): string {
  if (process.env.BILIBILI_E2E_PYTHON) return process.env.BILIBILI_E2E_PYTHON;
  const candidates =
    process.platform === "win32"
      ? [path.join(repoRoot, ".venv", "Scripts", "python.exe"), "python"]
      : [path.join(repoRoot, ".venv", "bin", "python"), "python3", "python"];
  return candidates.find(
    (candidate) =>
      candidate === "python" ||
      candidate === "python3" ||
      existsSync(candidate),
  )!;
}

function filesUnder(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(target) : [target];
  });
}

class SidecarHarness {
  readonly child: ChildProcessWithoutNullStreams;
  readonly client: SidecarClient;
  readonly events: SidecarBroadcastEvent[] = [];
  readonly runRoot = mkdtempSync(path.join(tmpdir(), "bilibili-sidecar-e2e-"));
  private stderr = "";
  private nextId = 1;

  constructor() {
    this.child = spawn(pythonExecutable(), [fixturePath], {
      cwd: repoRoot,
      env: { ...process.env, BILIBILI_AGENT_RUNS_DIR: this.runRoot },
      stdio: ["pipe", "pipe", "pipe"],
    });
    this.client = new SidecarClient(
      (request) => this.send(request),
      () => `e2e-${this.nextId++}`,
    );
    readline
      .createInterface({ input: this.child.stdout })
      .on("line", (line) => {
        const message = JSON.parse(line) as SidecarMessage;
        if (!this.client.accept(message) && message.kind === "event") {
          this.events.push(message);
        }
      });
    this.child.stderr.on("data", (chunk) => {
      this.stderr += chunk.toString();
    });
    this.child.on("exit", (code) => {
      this.client.dispose(`sidecar exited with ${code}: ${this.stderr}`);
    });
  }

  async send(request: SidecarRequest): Promise<void> {
    if (this.child.exitCode !== null) {
      throw new Error(
        `sidecar already exited with ${this.child.exitCode}: ${this.stderr}`,
      );
    }
    await new Promise<void>((resolve, reject) => {
      this.child.stdin.write(`${JSON.stringify(request)}\n`, (error) => {
        if (error) reject(error);
        else resolve();
      });
    });
  }

  async waitForEvent(
    event: SidecarBroadcastEvent["event"],
    mode?: SidecarBroadcastEvent["mode"],
    after = 0,
    status?: SidecarBroadcastEvent["status"],
  ): Promise<SidecarBroadcastEvent> {
    const deadline = Date.now() + 5_000;
    while (Date.now() < deadline) {
      const found = this.events
        .slice(after)
        .find(
          (item) =>
            item.event === event &&
            (mode === undefined || item.mode === mode) &&
            (status === undefined || item.status === status),
        );
      if (found) return found;
      if (this.child.exitCode !== null) break;
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
    throw new Error(
      `timed out waiting for ${event}/${mode ?? "*"}; events=${JSON.stringify(this.events)}; stderr=${this.stderr}`,
    );
  }

  async close(): Promise<void> {
    this.client.dispose();
    if (this.child.exitCode === null) {
      this.child.stdin.end();
      await Promise.race([
        new Promise<void>((resolve) =>
          this.child.once("exit", () => resolve()),
        ),
        new Promise<void>((resolve) => setTimeout(resolve, 1_000)),
      ]);
    }
    if (this.child.exitCode === null) {
      this.child.kill();
      await Promise.race([
        new Promise<void>((resolve) =>
          this.child.once("exit", () => resolve()),
        ),
        new Promise<void>((resolve) => setTimeout(resolve, 1_000)),
      ]);
    }
    rmSync(this.runRoot, { recursive: true, force: true });
  }
}

test("SidecarClient completes a persisted comment-to-analysis run over JSON lines", async (t) => {
  const harness = new SidecarHarness();
  t.after(() => harness.close());

  const crawl = await harness.client.request("comments.start", {
    input: "BV1xx411c7mD",
    max_pages: 1,
  });
  assert.equal(crawl.id, "e2e-1");
  await harness.waitForEvent("finished", "comments");

  const canary = "sk-sidecar-e2e-canary";
  const analysisStart = harness.events.length;
  const analysis = await harness.client.request("analysis.start", {
    source: "comments",
    sample_size: 123,
    batch_size: 45,
    chart_keys: ["word_cloud", "topic_ranking"],
    llm_config: { api_key: canary, model: "normal" },
  });
  assert.equal(analysis.id, "e2e-2");
  await harness.waitForEvent("finished", "analysis", analysisStart);

  const latest = await harness.client.request("analysis.latest");
  assert.equal(latest.id, "e2e-3");
  assert.equal(latest.result?.summary, "端到端分析完成");
  assert.equal(latest.result?.report_markdown, "");
  assert.deepEqual(
    harness.events
      .slice(analysisStart)
      .filter((item) => item.event === "analysis.progress")
      .map((item) => item.percent),
    [50],
  );

  const runDirs = readdirSync(harness.runRoot, { withFileTypes: true }).filter(
    (entry) => entry.isDirectory(),
  );
  assert.equal(runDirs.length, 1);
  const runDir = path.join(harness.runRoot, runDirs[0].name);
  const required = [
    "comments.json",
    "comments.csv",
    "analysis.json",
    "report.md",
    "manifest.json",
  ];
  for (const filename of required) {
    assert.equal(
      existsSync(path.join(runDir, filename)),
      true,
      `${filename} is missing`,
    );
  }
  for (const artifact of filesUnder(runDir)) {
    const raw = readFileSync(artifact);
    assert.equal(
      raw.includes(Buffer.from(canary)),
      false,
      `${path.basename(artifact)} leaked the API key`,
    );
  }
});

test("SidecarClient cancellation produces no stale finished and permits a clean retry", async (t) => {
  const harness = new SidecarHarness();
  t.after(() => harness.close());

  await harness.client.request("comments.start", {
    input: "BV1xx411c7mD",
    max_pages: 1,
  });
  await harness.waitForEvent("finished", "comments");
  const cancelledStart = harness.events.length;
  await harness.client.request("analysis.start", {
    source: "comments",
    llm_config: { api_key: "test-key", model: "block-until-cancel" },
  });
  await harness.waitForEvent("analysis.progress", undefined, cancelledStart);

  const stop = await harness.client.request("task.stop");
  assert.equal(stop.id, "e2e-3");
  await harness.waitForEvent("cancelled", "analysis", cancelledStart);
  await harness.waitForEvent("progress", "analysis", cancelledStart, "idle");
  assert.equal(
    harness.events
      .slice(cancelledStart)
      .some((item) => item.event === "finished" && item.mode === "analysis"),
    false,
  );

  const retryStart = harness.events.length;
  await harness.client.request("analysis.start", {
    source: "comments",
    llm_config: { api_key: "test-key", model: "normal" },
  });
  await harness.waitForEvent("finished", "analysis", retryStart);
  assert.equal(
    harness.events.filter(
      (item) => item.event === "finished" && item.mode === "analysis",
    ).length,
    1,
  );
});
