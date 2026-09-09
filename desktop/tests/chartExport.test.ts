import assert from "node:assert/strict";
import test from "node:test";
import { buildAnalysisChartAssets, compactChartLabel } from "../src/lib/analysisCharts.ts";
import type { AnalysisResult } from "../src/types.ts";

test("topic export separates long Unicode labels, bars and large values", async () => {
  const name = "对产品质量与售后服务的讨论😀<安全>";
  const result = {
    meta: { source: "comments", chart_keys: ["topic_ranking"] },
    topic_counts: [{ name, value: 123456789012345 }, { name: "价格", value: 1 }],
  } as AnalysisResult;
  const [asset] = await buildAnalysisChartAssets(result);
  const svg = asset.svg!;
  assert.ok(svg.includes(compactChartLabel(name, 10)));
  assert.ok(svg.includes("&lt;安全&gt;"));
  const bar = svg.match(/<rect x="([\d.]+)" y="80" width="([\d.]+)"/)!;
  const x = Number(bar[1]);
  // A conservative full-width glyph estimate, independent of the layout constants.
  assert.ok(28 + Array.from(compactChartLabel(name, 10)).length * 14 + 16 <= x);
  assert.ok(x + Number(bar[2]) + 10 + String(result.topic_counts[0].value).length * 8 < 820);
});

test("shared topic labels do not split astral Unicode characters", () => {
  assert.equal(compactChartLabel("😀".repeat(12), 10), "😀".repeat(9) + "…");
});
