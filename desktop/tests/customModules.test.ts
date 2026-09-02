import assert from "node:assert/strict";
import test from "node:test";

import {
  CUSTOM_MODULE_PROMPT_LIMIT,
  CUSTOM_MODULE_SAVED_LIMIT,
  CUSTOM_MODULE_TITLE_LIMIT,
  isCustomModuleKey,
  newCustomModuleId,
  normalizeAnalysisChartKeys,
  normalizeCustomModules,
  resultCustomModules,
  resultModuleKeys,
  truncateByCodePoint,
} from "../src/lib/analysisCharts.ts";
import type { AnalysisResult } from "../src/types.ts";

const MODULE = { id: "custom_a1b2c3", title: "传播路径", prompt: "分析扩散" };
const EMOJI = "🎬";
const HIGH_SURROGATE = /[\uD800-\uDBFF]/;

test("a malformed module is dropped rather than repaired", () => {
  const rejected = [
    { id: "custom_zzzzzz", title: "标题", prompt: "提示" },
    { id: "custom_a1b2c", title: "标题", prompt: "提示" },
    { id: "deep_analysis", title: "标题", prompt: "提示" },
    { id: "custom_a1b2c3", title: "", prompt: "提示" },
    { id: "custom_a1b2c3", title: "标题", prompt: "   " },
    "not-an-object",
  ];
  for (const entry of rejected) {
    assert.deepEqual(normalizeCustomModules([entry]), [], JSON.stringify(entry));
  }
});

test("ids are lowercased and fields truncated", () => {
  const [module] = normalizeCustomModules([
    { id: "custom_A1B2C3", title: "标".repeat(60), prompt: "提".repeat(900) },
  ]);
  assert.equal(module.id, "custom_a1b2c3");
  assert.equal([...module.title].length, CUSTOM_MODULE_TITLE_LIMIT);
  assert.equal([...module.prompt].length, CUSTOM_MODULE_PROMPT_LIMIT);
});

test("limits count Unicode code points, matching Rust and Python", () => {
  // `.slice` counts UTF-16 units: an emoji costs two and can be cut into a
  // lone surrogate, so the three layers would disagree on what fits.
  assert.equal([...truncateByCodePoint(EMOJI.repeat(40), CUSTOM_MODULE_TITLE_LIMIT)].length, CUSTOM_MODULE_TITLE_LIMIT);
  assert.equal(truncateByCodePoint(EMOJI.repeat(40), 2), EMOJI.repeat(2));
  assert.equal(truncateByCodePoint("短", 24), "短");
  // A truncation must never end on a dangling high surrogate.
  const cut = truncateByCodePoint(EMOJI.repeat(40), 3);
  assert.ok(!HIGH_SURROGATE.test(cut.slice(-1)));

  const [module] = normalizeCustomModules([
    { ...MODULE, title: EMOJI.repeat(40), prompt: EMOJI.repeat(900) },
  ]);
  assert.equal([...module.title].length, CUSTOM_MODULE_TITLE_LIMIT);
  assert.equal([...module.prompt].length, CUSTOM_MODULE_PROMPT_LIMIT);
});

test("a stored enabled flag is ignored rather than carried forward", () => {
  // The selection list is the single source of truth; a second flag could
  // contradict it, so it is not part of the stored shape.
  const [module] = normalizeCustomModules([{ ...MODULE, enabled: false }]);
  assert.deepEqual(module, MODULE);
});

test("duplicates keep the first entry and the saved count is capped", () => {
  const many = [
    MODULE,
    { ...MODULE, title: "后来的" },
    ...Array.from({ length: 12 }, (_, index) => ({
      ...MODULE,
      id: `custom_${index.toString(16).padStart(6, "0")}`,
      title: `模块${index}`,
    })),
  ];
  const normalized = normalizeCustomModules(many);
  assert.equal(normalized[0].title, "传播路径");
  assert.equal(normalized.length, CUSTOM_MODULE_SAVED_LIMIT);
});

test("custom ids are never part of the default selection", () => {
  // Falling back to "everything" must not silently start spending tokens on
  // modules the user never ticked.
  for (const value of [undefined, null, "not-a-list", []]) {
    const keys = normalizeAnalysisChartKeys(value, null, ["custom_a1b2c3"]);
    assert.ok(!keys.includes("custom_a1b2c3"), String(value));
    assert.ok(keys.includes("topic_ranking"));
  }
  assert.deepEqual(normalizeAnalysisChartKeys(["custom_a1b2c3"], null, ["custom_a1b2c3"]), [
    "custom_a1b2c3",
  ]);
});

test("a selection whose module was deleted is dropped", () => {
  assert.deepEqual(normalizeAnalysisChartKeys(["topic_ranking", "custom_a1b2c3"], null, []), [
    "topic_ranking",
  ]);
});

test("a fresh id avoids the ids already saved", () => {
  // A collision would make the editor treat a new module as an edit and
  // overwrite the existing one without saying so.
  const taken = Array.from({ length: 400 }, (_, index) => `custom_${index.toString(16).padStart(6, "0")}`);
  for (let attempt = 0; attempt < 300; attempt += 1) {
    assert.ok(!taken.includes(newCustomModuleId(taken)));
  }
});

test("a generated id round-trips through the key guard and normalizer", () => {
  const id = newCustomModuleId();
  assert.ok(isCustomModuleKey(id));
  assert.equal(normalizeCustomModules([{ ...MODULE, id }])[0].id, id);
  assert.ok(!isCustomModuleKey("topic_ranking"));
});

test("historical results read their titles from the run snapshot", () => {
  // The module has since been renamed away; the report must still say what it
  // said when it ran.
  const result = {
    custom_results: { custom_a1b2c3: "扩散主要来自二创" },
    meta: {
      source: "comments",
      chart_keys: ["topic_ranking", "custom_a1b2c3"],
      custom_modules: [MODULE],
    },
  } as unknown as AnalysisResult;

  assert.deepEqual(resultModuleKeys(result), ["topic_ranking", "custom_a1b2c3"]);
  assert.deepEqual(resultCustomModules(result), [
    { id: "custom_a1b2c3", title: "传播路径", text: "扩散主要来自二创" },
  ]);
});

test("a result without a snapshot exposes no custom sections", () => {
  const result = {
    meta: { source: "comments", chart_keys: ["topic_ranking", "custom_a1b2c3"] },
  } as unknown as AnalysisResult;
  assert.deepEqual(resultCustomModules(result), []);
  assert.deepEqual(resultModuleKeys(result), ["topic_ranking"]);
});
