import assert from "node:assert/strict";
import test from "node:test";

import { SidecarClient } from "../src/lib/sidecarClient.ts";
import type { SidecarRequest } from "../src/types.ts";

test("request remains pending until the matching sidecar response arrives", async () => {
  const sent: SidecarRequest[] = [];
  const client = new SidecarClient(
    async (request) => {
      sent.push(request);
    },
    () => "request-1",
  );

  let settled = false;
  const pending = client.request("session.status").finally(() => {
    settled = true;
  });

  await Promise.resolve();
  assert.equal(sent.length, 1);
  assert.equal(settled, false);

  client.accept({ kind: "response", id: "another-request", ok: true });
  await Promise.resolve();
  assert.equal(settled, false);

  client.accept({
    kind: "response",
    id: "request-1",
    ok: true,
    logged_in: true,
    task_running: false,
  });

  const response = await pending;
  assert.equal(response.logged_in, true);
  assert.equal(settled, true);
});

test("a failed matching response rejects only its request", async () => {
  const client = new SidecarClient(
    async () => undefined,
    () => "request-2",
  );
  const pending = client.request("comments.start", { input: "BV1example" });

  client.accept({
    kind: "response",
    id: "request-2",
    ok: false,
    error: "无法识别输入",
  });

  await assert.rejects(pending, /无法识别输入/);
});
