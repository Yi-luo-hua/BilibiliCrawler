import assert from "node:assert/strict";
import test from "node:test";
import { buildAnalysisChartAssets, wrapChartLabel } from "../src/lib/analysisCharts.ts";
import type { AnalysisResult } from "../src/types.ts";

test("topic export separates long Unicode labels, bars and large values", async () => {
  const name = "对产品质量与售后服务的讨论😀<安全>";
  const result = {
    meta: { source: "comments", chart_keys: ["topic_ranking"] },
    topic_counts: [{ name, value: 123456789012345 }, { name: "价格", value: 1 }],
  } as AnalysisResult;
  const [asset] = await buildAnalysisChartAssets(result);
  const svg = asset.svg!;
  const labels = [...svg.matchAll(/<tspan[^>]*>(.*?)<\/tspan>/g)].map((match) => match[1]).join("");
  assert.ok(labels.includes(name.replace("<", "&lt;").replace(">", "&gt;")));
  assert.ok(svg.includes("&lt;安全&gt;"));
  const bar = svg.match(/<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)" height="22"/)!;
  const x = Number(bar[1]);
  // A conservative full-width glyph estimate, independent of the layout constants.
  assert.ok(28 + Math.max(...wrapChartLabel(name, 10).map((line) => Array.from(line).length)) * 14 + 16 <= x);
  assert.ok(x + Number(bar[2]) + 10 + String(result.topic_counts[0].value).length * 8 < 820);
});

test("wrapped topic labels preserve every Unicode character", () => {
  const text = "😀".repeat(12);
  assert.deepEqual(wrapChartLabel(text, 10), ["😀".repeat(10), "😀".repeat(2)]);
  assert.equal(wrapChartLabel(text, 10).join(""), text);
});

test("topic export includes all topics with enough space for wrapped labels", async () => {
  const topics = Array.from({ length: 20 }, (_, index) => ({ name: `主题${index}` + "完整主题名称".repeat(5), value: 20 - index }));
  const result = { meta: { source: "comments", chart_keys: ["topic_ranking"] }, topic_counts: topics } as AnalysisResult;
  const [asset] = await buildAnalysisChartAssets(result);
  const svg = asset.svg!;
  assert.equal([...svg.matchAll(/height="22" rx="8"/g)].length, topics.length);
  const lines = [...svg.matchAll(/<tspan x="28" y="([\d.]+)">/g)].map((match) => Number(match[1]));
  assert.ok(lines.every((y, index) => index === 0 || y - lines[index - 1] >= 18));
  assert.ok(!svg.includes("…"));
});

test("time trend export preserves every day and early peaks across months", async () => {
  const days = Array.from({ length: 40 }, (_, index) => ({
    name: new Date(Date.UTC(2026, 8, index + 1)).toISOString().slice(0, 10),
    count: index === 0 ? 1000 : index + 1,
    likes: index === 0 ? 500 : index,
  }));
  const result = { meta: { source: "comments", chart_keys: ["time_trend"] }, time_series: days } as AnalysisResult;
  const [asset] = await buildAnalysisChartAssets(result);
  const lines = [...asset.svg!.matchAll(/<polyline points="([^"]+)"/g)]
    .map((match) => match[1].split(" "));

  assert.equal(lines.length, 2);
  for (const points of lines) assert.equal(points.length, days.length);
  assert.equal(lines[0][0], "56,82");
  assert.equal(lines[1][0], "56,172");
  assert.ok(asset.svg!.includes(days[0].name));
});
