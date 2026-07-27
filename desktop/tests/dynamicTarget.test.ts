import assert from "node:assert/strict";
import test from "node:test";

import { parseDynamicTarget } from "../src/lib/dynamicTarget.ts";

test("an invalid non-empty dynamic target is rejected instead of selecting the following feed", () => {
  assert.throws(() => parseDynamicTarget("not-a-uid"), /有效的用户 UID/);
});

test("an empty target explicitly selects the following feed", () => {
  assert.equal(parseDynamicTarget("   "), null);
});

test("a numeric UID or space URL selects that user", () => {
  assert.equal(parseDynamicTarget("123456"), 123456);
  assert.equal(
    parseDynamicTarget("https://space.bilibili.com/123456/dynamic"),
    123456,
  );
});
