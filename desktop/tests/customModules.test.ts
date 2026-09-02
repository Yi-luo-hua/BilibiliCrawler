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
} from "../src/lib/analysisCharts.ts";
import type { AnalysisResult } from "../src/types.ts";

const MODULE = { id: "custom_a1b2c3", title: "传播路径", prompt: "分析扩散", enabled: true };

test("a malformed module is dropped rather than repaired", () => {
  const rejected = [
    { id: "custom_zzzzzz", title: "标题", prompt: "提示", enabled: true },
    { id: "custom_a1b2c", title: "标题", prompt: "提示", enabled: true },
    { id: "deep_analysis", title: "标题", prompt: "提示", enabled: true },
    { id: "custom_a1b2c3", title: "", prompt: "提示", enabled: true },
    { id: "custom_a1b2c3", title: "标题", prompt: "   ", enabled: true },
    "not-an-object",
  ];
  for (const entry of rejected) {
    assert.deepEqual(normalizeCustomModules([entry]), [], JSON.stringify(entry));
  }
});

test("ids are lowercased and fields truncated by characters", () => {
  const [module] = normalizeCustomModules([
    { id: "custom_A1B2C3", title: "标".repeat(60), prompt: "提".repeat(900), enabled: true },
  ]);
  assert.equal(module.id, "custom_a1b2c3");
  assert.equal([...module.title].length, CUSTOM_MODULE_TITLE_LIMIT);
  assert.equal([...module.prompt].length, CUSTOM_MODULE_PROMPT_LIMIT);
});

test("duplicates keep the first entry and the saved count is capped", () => {
  const many = [
    MODULE,
    { ...MODULE, title: "后来的" },
    ...Array.from({ length: 12 }, (_, index) => ({
      ...MODULE,
      id: `custom_00000${index % 10}${index < 10 ? "" : "a"}`.slice(0, 13),
      title: `模块${index}`,
    })),
  ];
  const normalized = normalizeCustomModules(many);
  assert.equal(normalized[0].title, "传播路径");
  assert.ok(normalized.length <= CUSTOM_MODULE_SAVED_LIMIT);
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

test("a generated id round-trips through the key guard and normalizer", () => {
  const id = newCustomModuleId();
  assert.ok(isCustomModuleKey(id));
  assert.deepEqual(normalizeCustomModules([{ ...MODULE, id }])[0].id, id);
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
      custom_modules: [{ id: "custom_a1b2c3", title: "传播路径", prompt: "分析扩散" }],
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
