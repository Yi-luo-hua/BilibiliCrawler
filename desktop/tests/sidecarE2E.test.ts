import assert from "node:assert/strict";
import {
  spawn,
  spawnSync,
  type ChildProcessWithoutNullStreams,
} from "node:child_process";
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { createServer } from "node:http";
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
  const configured = process.env.BILIBILI_E2E_PYTHON;
  const candidates = configured
    ? [configured]
    : process.platform === "win32"
      ? [path.join(repoRoot, ".venv", "Scripts", "python.exe"), "python"]
      : [path.join(repoRoot, ".venv", "bin", "python"), "python3", "python"];
  for (const candidate of candidates) {
    const probe = spawnSync(candidate, ["--version"], {
      stdio: "ignore",
      windowsHide: true,
    });
    if (!probe.error && probe.status === 0) return candidate;
  }
  throw new Error(
    `no usable Python interpreter found: ${candidates.join(", ")}`,
  );
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
  readonly runRoot: string;
  private readonly closed: Promise<void>;
  private didClose = false;
  private stderr = "";
  private nextId = 1;
  private spawnError: Error | null = null;

  constructor(realProvider = false) {
    const executable = pythonExecutable();
    this.runRoot = mkdtempSync(path.join(tmpdir(), "bilibili-sidecar-e2e-"));
    this.child = spawn(executable, [fixturePath], {
      cwd: repoRoot,
      env: {
        ...process.env, BILIBILI_AGENT_RUNS_DIR: this.runRoot,
        BILIBILI_E2E_REAL_PROVIDER: realProvider ? "1" : "0",
      },
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.client = new SidecarClient(
      (request) => this.send(request),
      () => `e2e-${this.nextId++}`,
    );
    this.closed = new Promise((resolve) => {
      this.child.once("close", () => resolve());
    });
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
    this.child.on("error", (error) => {
      this.spawnError = error;
      this.stderr += `${error.message}\n`;
      this.client.dispose(`sidecar failed to start: ${error.message}`);
    });
    this.child.on("close", (code, signal) => {
      this.didClose = true;
      this.client.dispose(
        `sidecar closed with code=${code} signal=${signal}: ${this.stderr}`,
      );
    });
  }

  async send(request: SidecarRequest): Promise<void> {
    if (this.spawnError) throw this.spawnError;
    if (this.child.exitCode !== null || this.child.signalCode !== null) {
      throw new Error(
        `sidecar already closed with code=${this.child.exitCode} signal=${this.child.signalCode}: ${this.stderr}`,
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
      if (
        this.spawnError ||
        this.child.exitCode !== null ||
        this.child.signalCode !== null
      )
        break;
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
    throw new Error(
      `timed out waiting for ${event}/${mode ?? "*"}; events=${JSON.stringify(this.events)}; stderr=${this.stderr}`,
    );
  }

  private async waitForClose(timeoutMs: number): Promise<boolean> {
    return new Promise((resolve) => {
      const timer = setTimeout(() => resolve(false), timeoutMs);
      this.closed.then(() => {
        clearTimeout(timer);
        resolve(true);
      });
    });
  }

  async close(): Promise<void> {
    this.client.dispose();
    let closed = this.didClose;
    if (
      !closed &&
      this.child.exitCode === null &&
      this.child.signalCode === null
    ) {
      if (!this.child.stdin.destroyed) this.child.stdin.end();
    }
    if (!closed) closed = await this.waitForClose(1_000);
    if (!closed) {
      this.child.kill();
      closed = await this.waitForClose(1_000);
    }
    if (!closed) throw new Error(`sidecar did not close: ${this.stderr}`);
    rmSync(this.runRoot, { recursive: true, force: true });
  }
}

test("SidecarClient receives real provider waiting and retry details over JSON lines", async (t) => {
  let requests = 0;
  const server = createServer((request, response) => {
    request.resume();
    request.on("end", () => {
      requests += 1;
      if (requests === 1) {
        response.writeHead(503, { "Content-Type": "application/json", "Retry-After": "1" });
        response.end(JSON.stringify({ error: { message: "temporary" } }));
      } else {
        response.writeHead(200, { "Content-Type": "application/json" });
        response.end(JSON.stringify({ choices: [{ message: { content: '{"summary":"桌面等待测试"}' } }] }));
      }
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve())));
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  const harness = new SidecarHarness(true);
  t.after(() => harness.close());
  await harness.client.request("comments.start", { input: "BV1xx411c7mD", max_pages: 1 });
  await harness.waitForEvent("progress", "comments", 0, "idle");
  const after = harness.events.length;
  await harness.client.request("analysis.start", {
    source: "comments", chart_keys: ["topic_ranking"],
    llm_config: { api_key: "sk-progress-canary-12345", model: "test-model", base_url: `http://127.0.0.1:${address.port}/v1` },
  });
  const finished = await harness.waitForEvent("finished", "analysis", after);
  const progress = harness.events.slice(after).filter((event) => event.event === "analysis.progress" && event.message?.includes("第 1/1 批 ·"));
  assert.ok(progress.some((event) => event.message?.includes("连接/读取超时 90/90s")));
  assert.ok(progress.some((event) => event.message?.includes("退避中")));
  assert.ok(progress.some((event) => event.message?.includes("请求 2/3（重试 1）")));
  assert.ok(progress.every((event) => event.percent === 80));
  assert.equal(requests, 2);
  assert.equal(finished.result?.summary, "桌面等待测试");
  assert.equal(JSON.stringify(progress).includes("sk-progress-canary"), false);
});

test("SidecarClient completes a persisted comment-to-analysis run over JSON lines", async (t) => {
  const harness = new SidecarHarness();
  t.after(() => harness.close());

  const crawlStart = harness.events.length;
  const crawl = await harness.client.request("comments.start", {
    input: "BV1xx411c7mD",
    max_pages: 1,
  });
  assert.equal(crawl.id, "e2e-1");
  await harness.waitForEvent("finished", "comments", crawlStart);
  await harness.waitForEvent("progress", "comments", crawlStart, "idle");

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
  await harness.waitForEvent("progress", "analysis", analysisStart, "idle");

  const latest = await harness.client.request("analysis.latest");
  assert.equal(latest.id, "e2e-3");
  assert.equal(latest.result?.summary, "端到端分析完成");
  assert.equal(latest.result?.report_markdown, "");
  assert.match(
    latest.result?.word_cloud_image ?? "",
    /^data:image\/png;base64,/,
  );
  assert.equal(existsSync(latest.result?.word_cloud_image_path ?? ""), true);
  assert.deepEqual(
    harness.events
      .slice(analysisStart)
      .filter((item) => item.event === "analysis.progress")
      .map((item) => item.percent),
    [50],
  );

  const resolutionOrder: string[] = [];
  const delayedLatest = harness.client
    .request("analysis.latest", { _fixture_response_delay_ms: 150 })
    .then((response) => {
      resolutionOrder.push("latest");
      return response;
    });
  const statusRequest = harness.client
    .request("session.status")
    .then((response) => {
      resolutionOrder.push("status");
      return response;
    });
  const status = await statusRequest;
  assert.equal(status.id, "e2e-5");
  assert.deepEqual(resolutionOrder, ["status"]);
  const correlatedLatest = await delayedLatest;
  assert.equal(correlatedLatest.id, "e2e-4");
  assert.equal(correlatedLatest.result?.summary, "端到端分析完成");
  assert.deepEqual(resolutionOrder, ["status", "latest"]);

  const csvPath = path.join(harness.runRoot, "exported-comments.csv");
  const csvExport = await harness.client.request("export.csv", {
    kind: "comments",
    path: csvPath,
  });
  assert.equal(csvExport.id, "e2e-6");
  assert.equal(csvExport.path, csvPath);
  assert.match(readFileSync(csvPath, "utf8"), /端到端用户/);

  const analysisPath = path.join(harness.runRoot, "exported-analysis.json");
  const analysisExport = await harness.client.request("analysis.export", {
    format: "json",
    path: analysisPath,
  });
  assert.equal(analysisExport.id, "e2e-7");
  assert.equal(analysisExport.path, analysisPath);
  const exportedAnalysis = readFileSync(analysisPath, "utf8");

  const markdownPath = path.join(harness.runRoot, "exported-analysis.md");
  const markdownExport = await harness.client.request("analysis.export", {
    format: "markdown",
    path: markdownPath,
  });
  assert.equal(markdownExport.id, "e2e-8");
  assert.equal(markdownExport.path, markdownPath);
  const exportedMarkdown = readFileSync(markdownPath, "utf8");

  assert.equal(exportedAnalysis.includes(canary), false);
  assert.equal(
    JSON.parse(exportedAnalysis).meta.config.llm_config.api_key,
    "***",
  );
  assert.equal(exportedMarkdown.includes(canary), false);
  assert.match(exportedMarkdown, /# 端到端报告/);

  const runDirs = readdirSync(harness.runRoot, { withFileTypes: true }).filter(
    (entry) =>
      entry.isDirectory() && /^\d{8}-\d{6}-[0-9a-f]{8}$/.test(entry.name),
  );
  assert.equal(runDirs.length, 1);
  const runDir = path.join(harness.runRoot, runDirs[0].name);
  const required = [
    "comments.json",
    "comments.csv",
    "analysis.json",
    "report.md",
    "manifest.json",
    path.join("assets", "word_cloud.png"),
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

  const crawlStart = harness.events.length;
  await harness.client.request("comments.start", {
    input: "BV1xx411c7mD",
    max_pages: 1,
  });
  await harness.waitForEvent("finished", "comments", crawlStart);
  await harness.waitForEvent("progress", "comments", crawlStart, "idle");
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
  const cancelledEvents = harness.events.slice(cancelledStart);
  const cancelledIndex = cancelledEvents.findIndex(
    (item) => item.event === "cancelled" && item.mode === "analysis",
  );
  const idleIndex = cancelledEvents.findIndex(
    (item) =>
      item.event === "progress" &&
      item.mode === "analysis" &&
      item.status === "idle",
  );
  assert.deepEqual(cancelledEvents.slice(cancelledIndex, idleIndex + 1), [
    {
      kind: "event",
      event: "cancelled",
      mode: "analysis",
      message: "分析已被取消",
    },
    { kind: "event", event: "log", message: "分析任务已取消" },
    {
      kind: "event",
      event: "progress",
      status: "idle",
      mode: "analysis",
      percent: 100,
    },
  ]);
  assert.equal(
    cancelledEvents.some(
      (item) =>
        (item.event === "finished" || item.event === "error") &&
        (item.mode === undefined || item.mode === "analysis"),
    ),
    false,
  );

  const retryStart = harness.events.length;
  await harness.client.request("analysis.start", {
    source: "comments",
    llm_config: { api_key: "test-key", model: "normal" },
  });
  await harness.waitForEvent("finished", "analysis", retryStart);
  await harness.waitForEvent("progress", "analysis", retryStart, "idle");
  const eventsAfterCancellation = harness.events.slice(cancelledStart);
  assert.equal(
    eventsAfterCancellation.filter(
      (item) => item.event === "finished" && item.mode === "analysis",
    ).length,
    1,
  );
  assert.equal(
    eventsAfterCancellation.some(
      (item) =>
        item.event === "error" &&
        (item.mode === undefined || item.mode === "analysis"),
    ),
    false,
  );
});
