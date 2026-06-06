import { useEffect, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";
import { convertFileSrc } from "@tauri-apps/api/core";
import { AlertTriangle, BrainCircuit, Database, FileText, Gauge, MapPinned, Tags } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import {
  analysisChartOptions,
  analysisSourceLabel,
  chinaMapLocations,
  chinaMapViewBox,
  getAnalysisChartOptionsForSource,
  getMapLocationPaths,
  getRegionValueByMapId,
  hasAnalysisChart,
  normalizeAnalysisChartKeys,
  regionFill,
  regionStroke,
  regionStrokeWidth,
  unmappedDomesticRegions
} from "../lib/analysisCharts";
import type { AnalysisChartKey, AnalysisResult, AnalysisSource, AnalysisStrategy, ChartDatum, UIConfig } from "../types";

interface Props {
  config: UIConfig;
  setConfig: Dispatch<SetStateAction<UIConfig>>;
  llmApiKey: string;
  setLlmApiKey: Dispatch<SetStateAction<string>>;
  hasComments: boolean;
  hasDynamics: boolean;
  analysisSource: AnalysisSource | null;
  analysisResult: AnalysisResult | null;
  analysisStats?: {
    total_records?: number;
    analyzed_records?: number;
    risk_count?: number;
  };
}

const strategyOptions: Array<{ value: AnalysisStrategy; label: string }> = [
  { value: "sample", label: "抽样 + 聚合" },
  { value: "full", label: "全量分批" }
];

const colors = ["#1e73d6", "#fb7299", "#29bf73", "#f5a524", "#7c6ff6", "#16a3a8", "#ef4b5d", "#8b5cf6"];
const axisTick = { fontSize: 11, fill: "var(--muted)" };

export function AnalysisWorkspace({ config, setConfig, llmApiKey, setLlmApiKey, hasComments, hasDynamics, analysisSource, analysisResult, analysisStats }: Props) {
  const selectedKeys = normalizeAnalysisChartKeys(config.analysis_chart_keys, analysisSource);
  const availableChartOptions = getAnalysisChartOptionsForSource(analysisSource);
  const patch = (data: Partial<UIConfig>) => setConfig((prev) => ({ ...prev, ...data }));
  const canAnalyzeSource = Boolean(analysisSource);
  const [sampleSizeInput, setSampleSizeInput] = useState(String(config.analysis_sample_size));
  const [batchSizeInput, setBatchSizeInput] = useState(String(config.analysis_batch_size));

  useEffect(() => {
    setSampleSizeInput(String(config.analysis_sample_size));
  }, [config.analysis_sample_size]);

  useEffect(() => {
    setBatchSizeInput(String(config.analysis_batch_size));
  }, [config.analysis_batch_size]);

  const updateSampleSize = (value: string) => {
    const digits = onlyDigits(value);
    setSampleSizeInput(digits);
    if (digits !== "") {
      patch({ analysis_sample_size: Number.parseInt(digits, 10) });
    }
  };

  const updateBatchSize = (value: string) => {
    const digits = onlyDigits(value);
    setBatchSizeInput(digits);
    if (digits !== "") {
      patch({ analysis_batch_size: Number.parseInt(digits, 10) });
    }
  };

  const commitSampleSize = (value: string) => {
    if (value === "") {
      setSampleSizeInput("300");
      patch({ analysis_sample_size: 300 });
    }
  };

  const commitBatchSize = (value: string) => {
    if (value === "") {
      setBatchSizeInput("80");
      patch({ analysis_batch_size: 80 });
    }
  };

  const toggleChart = (key: AnalysisChartKey) => {
    const selected = normalizeAnalysisChartKeys(config.analysis_chart_keys, analysisSource);
    if (selected.includes(key)) {
      if (selected.length === 1) return;
      patch({ analysis_chart_keys: selected.filter((item) => item !== key) });
      return;
    }
    patch({ analysis_chart_keys: [...selected, key] });
  };

  return (
    <section className="workspace analysis-workspace">
      <div className="analysis-header">
        <div className="panel-title">
          <h2>舆论分析</h2>
          <p>调用 OpenAI 兼容接口分析情绪、主题、风险和互动层级</p>
        </div>
        <div className={canAnalyzeSource ? "data-state ready" : "data-state"}>
          <Database size={18} />
          {canAnalyzeSource ? "数据可分析" : "等待爬取数据"}
        </div>
      </div>

      <div className="analysis-config-grid">
        <label className="field wide">
          <span>Base URL</span>
          <input value={config.llm_base_url} onChange={(event) => patch({ llm_base_url: event.target.value })} placeholder="https://api.openai.com/v1" />
        </label>
        <label className="field">
          <span>模型</span>
          <input value={config.llm_model} onChange={(event) => patch({ llm_model: event.target.value })} placeholder="gpt-4.1-mini / deepseek-chat" />
        </label>
        <label className="field">
          <span>API Key</span>
          <input
            type="password"
            value={llmApiKey}
            onChange={(event) => setLlmApiKey(event.target.value)}
            placeholder="加密存储于本地凭据文件"
          />
        </label>
        <label className="field">
          <span>数据源</span>
          <input value={analysisSourceLabel(analysisSource)} readOnly aria-readonly="true" />
        </label>
        <label className="field">
          <span>分析策略</span>
          <select value={config.analysis_strategy} onChange={(event) => patch({ analysis_strategy: event.target.value as AnalysisStrategy })}>
            {strategyOptions.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        {config.analysis_strategy === "sample" ? (
          <label className="field">
            <span>抽样数量</span>
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              value={sampleSizeInput}
              onChange={(event) => updateSampleSize(event.target.value)}
              onBlur={(event) => commitSampleSize(event.currentTarget.value)}
            />
          </label>
        ) : null}
        <label className="field">
          <span>分批大小</span>
          <input
            type="text"
            inputMode="numeric"
            pattern="[0-9]*"
            value={batchSizeInput}
            onChange={(event) => updateBatchSize(event.target.value)}
            onBlur={(event) => commitBatchSize(event.currentTarget.value)}
          />
        </label>
      </div>

      <div className="analysis-module-picker">
        <div className="module-picker-title">
          <Tags size={17} />
          <strong>分析模块</strong>
          <span>{selectedKeys.length} 项</span>
        </div>
        <div className="module-option-grid">
          {availableChartOptions.map((item) => {
            const checked = selectedKeys.includes(item.key);
            return (
              <label className={checked ? "module-option selected" : "module-option"} key={item.key}>
                <input type="checkbox" checked={checked} onChange={() => toggleChart(item.key)} disabled={checked && selectedKeys.length === 1} />
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.description}</small>
                </span>
              </label>
            );
          })}
        </div>
      </div>

      <div className="analysis-data-row">
        <span className={hasComments ? "source-pill ready" : "source-pill"}>评论数据：{hasComments ? "已就绪" : "暂无"}</span>
        <span className={hasDynamics ? "source-pill ready" : "source-pill"}>动态数据：{hasDynamics ? "已就绪" : "暂无"}</span>
        <span className={analysisSource ? "source-pill ready" : "source-pill"}>自动匹配：{analysisSourceLabel(analysisSource)}</span>
        <span className="source-pill">策略：{config.analysis_strategy === "sample" ? "抽样聚合" : "全量分批"}</span>
      </div>

      {analysisResult ? <AnalysisDashboard result={analysisResult} /> : analysisStats?.analyzed_records ? <MissingAnalysisResult /> : <EmptyAnalysis />}
    </section>
  );
}

function AnalysisDashboard({ result }: { result: AnalysisResult }) {
  const activeLabels = normalizeAnalysisChartKeys(result.meta.chart_keys, result.meta.source)
    .map((key) => analysisChartOptions.find((item) => item.key === key)?.label)
    .filter(Boolean)
    .join(" / ");
  const overviewCards = [
    { icon: Gauge, label: "分析样本", value: `${result.overview.analyzed_records ?? 0}/${result.overview.total_records ?? 0}` },
    { icon: BrainCircuit, label: "主题数", value: result.topic_counts.length },
    { icon: AlertTriangle, label: "风险点", value: result.risk_points.length },
    { icon: FileText, label: "批次数", value: result.meta.batch_count }
  ];
  const topicData = result.topic_counts.map((item) => ({ ...item, shortName: compactChartLabel(item.name, 10) }));
  const topicChartHeight = Math.max(260, topicData.length * 36 + 62);

  return (
    <div className="analysis-dashboard">
      <div className="analysis-summary">
        <strong>分析总结</strong>
        <p>{result.summary}</p>
        {result.summary_points?.length ? (
          <ul className="summary-point-list">
            {result.summary_points.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : null}
        <span className="analysis-module-badge">本次模块：{activeLabels}</span>
      </div>
      <div className="analysis-metrics">
        {overviewCards.map((item) => {
          const Icon = item.icon;
          return (
            <div className="analysis-metric" key={item.label}>
              <Icon size={18} />
              <strong>{item.value}</strong>
              <span>{item.label}</span>
            </div>
          );
        })}
      </div>
      <div className="chart-grid">
        {hasAnalysisChart(result, "sentiment_distribution") ? (
          <ChartPanel title="情绪分布">
            {result.sentiment_counts.length ? (
              <ResponsiveContainer width="100%" height={250}>
                <PieChart>
                  <Pie
                    data={result.sentiment_counts}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={52}
                    outerRadius={82}
                    paddingAngle={3}
                    labelLine
                    label={renderPieLabel}
                  >
                    {result.sentiment_counts.map((_, index) => (
                      <Cell key={index} fill={colors[index % colors.length]} />
                    ))}
                  </Pie>
                  <Tooltip content={<ChartTooltip />} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <EmptyChart />
            )}
          </ChartPanel>
        ) : null}
        {hasAnalysisChart(result, "topic_ranking") ? (
          <ChartPanel title="主题排行" className="topic-chart-panel">
            {topicData.length ? (
              <div className="chart-scroll">
                <ResponsiveContainer width="100%" height={topicChartHeight}>
                  <BarChart data={topicData} layout="vertical" margin={{ top: 8, right: 28, bottom: 4, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                    <XAxis type="number" tick={axisTick} allowDecimals={false} />
                    <YAxis type="category" dataKey="shortName" width={98} tick={axisTick} tickLine={false} axisLine={false} />
                    <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(30, 115, 214, 0.08)" }} />
                    <Bar dataKey="value" radius={[0, 8, 8, 0]} fill="#1e73d6" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyChart />
            )}
          </ChartPanel>
        ) : null}
        {hasAnalysisChart(result, "time_trend") ? (
          <ChartPanel title="时间趋势">
            {result.time_series.length ? (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={result.time_series}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" tick={axisTick} />
                  <YAxis width={34} tick={axisTick} />
                  <Tooltip content={<ChartTooltip />} />
                  <Line type="monotone" dataKey="count" name="数量" stroke="#1e73d6" strokeWidth={3} dot={false} />
                  <Line type="monotone" dataKey="likes" name="点赞" stroke="#fb7299" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <EmptyChart />
            )}
          </ChartPanel>
        ) : null}
        {hasAnalysisChart(result, "level_distribution") ? (
          <ChartPanel title="等级分布">
            {result.user_level_counts.length ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={result.user_level_counts}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" tick={axisTick} />
                  <YAxis width={34} tick={axisTick} />
                  <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(41, 191, 115, 0.08)" }} />
                  <Bar dataKey="value" radius={[8, 8, 0, 0]} fill="#29bf73" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyChart />
            )}
          </ChartPanel>
        ) : null}
        {hasAnalysisChart(result, "region_map") ? (
          <ChartPanel title="地域分布" className="region-chart-panel">
            <RegionMap regionCounts={result.region_counts} overseasCounts={result.overseas_region_counts} />
          </ChartPanel>
        ) : null}
        {hasAnalysisChart(result, "word_cloud") ? (
          <ChartPanel title="词云图" className="word-cloud-panel">
            <WordCloud image={result.word_cloud_image} imagePath={result.word_cloud_image_path} data={result.word_counts} />
          </ChartPanel>
        ) : null}
      </div>
      {hasAnalysisChart(result, "deep_analysis") ? <DeepAnalysisBlock result={result} /> : null}
      <StackedAnalysisCards
        title="分析要点"
        cards={[
          { title: "关键洞察", items: result.insights, empty: "暂无洞察" },
          { title: "风险点", items: result.risk_points, empty: "暂无明显风险点" },
          { title: "代表性评论", items: result.notable_quotes, empty: "暂无代表性评论" },
        ]}
      />
    </div>
  );
}

function RegionMap({ regionCounts, overseasCounts }: { regionCounts: ChartDatum[]; overseasCounts: ChartDatum[] }) {
  const totalValue = [...regionCounts, ...overseasCounts].reduce((sum, item) => sum + numberValue(item), 0);
  const maxPercent = totalValue > 0 ? Math.max(...regionCounts.map((item) => (numberValue(item) / totalValue) * 100), 0) : 0;
  const sideList = [...unmappedDomesticRegions(regionCounts), ...overseasCounts.filter((item) => numberValue(item) > 0)].slice(0, 8);
  return (
    <div className="region-map-layout">
      <svg className="china-map" viewBox={chinaMapViewBox} role="img" aria-label="中国地域分布">
        {chinaMapLocations.map((location) => {
          const value = getRegionValueByMapId(regionCounts, location.id);
          const paths = getMapLocationPaths(location);
          return (
            <g key={location.id}>
              <g className="map-region-layer">
                {paths.map((path, index) => (
                  <path
                    key={`${location.id}-${index}`}
                    d={path}
                    transform={location.transform}
                    fill={regionFill(value, totalValue)}
                    stroke={regionStroke(value, totalValue)}
                    strokeWidth={regionStrokeWidth(value, totalValue)}
                  >
                    <title>
                      {location.name}: {value}
                    </title>
                  </path>
                ))}
              </g>
            </g>
          );
        })}
      </svg>
      <div className="region-side">
        <div>
          <MapPinned size={16} />
          <strong>海外 / 未上图</strong>
        </div>
        {sideList.length ? (
          sideList.map((item) => (
            <p key={item.name}>
              <span>{item.name}</span>
              <b>{numberValue(item)}</b>
            </p>
          ))
        ) : (
          <p className="muted-row">暂无数据</p>
        )}
        <small>颜色按占总人数百分比分档，地区标值仍为人数，总人数 {totalValue}，最高占比 {formatPercentValue(maxPercent)}</small>
      </div>
    </div>
  );
}

function WordCloud({ image, imagePath, data }: { image?: string; imagePath?: string; data: ChartDatum[] }) {
  // Prefer base64 data URL (always works in <img src>); fall back to
  // Tauri asset protocol when base64 is unavailable (e.g. legacy results).
  const source = image || (imagePath ? convertFileSrc(imagePath) : "");
  if (!source) return <EmptyChart />;
  return (
    <div className="word-cloud" aria-label="词云图">
      <img
        className="word-cloud-image"
        src={source}
        alt={`词云图，包含 ${data.length} 个高频词`}
      />
    </div>
  );
}

type TooltipPayloadItem = {
  name?: string;
  value?: number | string;
  color?: string;
  dataKey?: string | number;
  payload?: Record<string, unknown>;
};

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: TooltipPayloadItem[]; label?: unknown }) {
  if (!active || !payload?.length) return null;
  const first = payload[0];
  const firstPayload = first.payload || {};
  const title = String(firstPayload.name ?? label ?? first.name ?? "");
  return (
    <div className="chart-tooltip">
      {title ? <strong>{title}</strong> : null}
      {payload.map((item, index) => {
        const name = tooltipSeriesName(item);
        return (
          <p key={`${name}-${index}`}>
            <i style={{ background: item.color || colors[index % colors.length] }} />
            <span>{name}</span>
            <b>{formatTooltipValue(item.value)}</b>
          </p>
        );
      })}
    </div>
  );
}

function DeepAnalysisBlock({ result }: { result: AnalysisResult }) {
  return (
    <StackedAnalysisCards
      title="舆论深入剖析"
      cards={[
        { title: "社会学视角", items: [result.deep_analysis.sociology], empty: "暂无剖析" },
        { title: "心理学视角", items: [result.deep_analysis.psychology], empty: "暂无剖析" },
        { title: "哲学视角", items: [result.deep_analysis.philosophy], empty: "暂无剖析" },
      ]}
    />
  );
}

function ChartPanel({ title, children, className = "" }: { title: string; children: ReactNode; className?: string }) {
  return (
    <div className={["chart-panel", className].filter(Boolean).join(" ")}>
      <strong>{title}</strong>
      {children}
    </div>
  );
}

function StackedAnalysisCards({ title, cards }: { title: string; cards: Array<{ title: string; items: string[]; empty: string }> }) {
  return (
    <section className="stacked-analysis-group">
      <strong>{title}</strong>
      <div className="stacked-analysis-cards">
        {cards.map((card) => {
          const values = card.items.map((item) => String(item || "").trim()).filter(Boolean);
          return (
            <article className="stacked-analysis-card" key={card.title}>
              <h3>{card.title}</h3>
              {(values.length ? values : [card.empty]).map((item, index) => (
                <p key={`${card.title}-${index}`}>{item}</p>
              ))}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function EmptyChart() {
  return <div className="empty-chart">暂无图表数据</div>;
}

function EmptyAnalysis() {
  return (
    <div className="analysis-empty">
      <BrainCircuit size={42} />
      <strong>完成爬取后开始分析</strong>
      <p>可先抓取评论或动态，再在底部点击“开始分析”生成舆论摘要和可视化图表。</p>
    </div>
  );
}

function MissingAnalysisResult() {
  return (
    <div className="analysis-empty">
      <BrainCircuit size={42} />
      <strong>分析已完成，结果正在同步</strong>
      <p>如果图表没有自动出现，请重新安装最新测试包后再次分析。</p>
    </div>
  );
}

function renderPieLabel(props: { name?: string; value?: number; percent?: number; x?: number; y?: number; textAnchor?: string }) {
  const { name, value, percent, x, y, textAnchor } = props;
  if (typeof x !== "number" || typeof y !== "number") return null;
  const anchor = textAnchor === "start" || textAnchor === "middle" || textAnchor === "end" ? textAnchor : "middle";
  return (
    <text x={x} y={y} textAnchor={anchor} fill="var(--text)" fontSize={12}>
      {name} {value ?? 0} ({((percent ?? 0) * 100).toFixed(1)}%)
    </text>
  );
}

function onlyDigits(value: string) {
  return value.replace(/\D/g, "");
}

function compactChartLabel(value: unknown, limit: number) {
  const text = String(value ?? "");
  return text.length <= limit ? text : `${text.slice(0, limit - 1)}…`;
}

function numberValue(item: ChartDatum) {
  const value = item.value ?? item.count ?? 0;
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function formatPercentValue(value: number) {
  return `${Number(value.toFixed(2))}%`;
}

function tooltipSeriesName(item: TooltipPayloadItem) {
  const key = String(item.dataKey ?? item.name ?? "");
  if (key === "value") return "数量";
  if (key === "count") return "数量";
  if (key === "likes") return "点赞";
  return String(item.name ?? "数值");
}

function formatTooltipValue(value: unknown) {
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(2);
  return String(value ?? "-");
}
