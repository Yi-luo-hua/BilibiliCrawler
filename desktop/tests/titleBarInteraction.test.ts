import assert from "node:assert/strict";
import test from "node:test";

import { handleTitleBarMouseDown } from "../src/lib/titleBarInteraction.ts";

test("a primary-button title-bar double click toggles maximize without starting a drag", async () => {
  const calls: string[] = [];

  await handleTitleBarMouseDown(
    { button: 0, detail: 2 },
    {
      startDragging: async () => {
        calls.push("drag");
      },
      toggleMaximize: async () => {
        calls.push("toggle-maximize");
      },
    },
  );

  assert.deepEqual(calls, ["toggle-maximize"]);
});

test("a primary-button title-bar single click starts dragging without toggling maximize", async () => {
  const calls: string[] = [];

  await handleTitleBarMouseDown(
    { button: 0, detail: 1 },
    {
      startDragging: async () => {
        calls.push("drag");
      },
      toggleMaximize: async () => {
        calls.push("toggle-maximize");
      },
    },
  );

  assert.deepEqual(calls, ["drag"]);
});
