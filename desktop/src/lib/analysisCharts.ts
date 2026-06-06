import chinaMap from "@svg-maps/china";
import taiwanMainMap from "@svg-maps/taiwan.main";
import type { AnalysisChartKey, AnalysisResult, AnalysisSource, ChartAsset, ChartDatum } from "../types";

export interface ChinaMapLocation {
  id: string;
  name: string;
  path?: string;
  paths?: string[];
  transform?: string;
}

export const analysisChartOptions: Array<{ key: AnalysisChartKey; label: string; description: string }> = [
  { key: "sentiment_distribution", label: "情绪分布", description: "环图标注各情绪数量" },
  { key: "topic_ranking", label: "主题排行", description: "长主题横向排行" },
  { key: "time_trend", label: "时间趋势", description: "评论量与点赞趋势" },
  { key: "level_distribution", label: "等级分布", description: "用户等级人数分布" },
  { key: "region_map", label: "地域分布", description: "中国地图与海外数据" },
  { key: "word_cloud", label: "词云图", description: "高频词权重展示" },
  { key: "deep_analysis", label: "舆论深入剖析", description: "社会学、心理学、哲学视角" }
];

export const DEFAULT_ANALYSIS_CHART_KEYS = analysisChartOptions.map((item) => item.key);
export const DYNAMICS_UNSUPPORTED_CHART_KEYS: AnalysisChartKey[] = ["time_trend", "level_distribution", "region_map", "deep_analysis"];

const chartTitleByKey = Object.fromEntries(analysisChartOptions.map((item) => [item.key, item.label])) as Record<AnalysisChartKey, string>;

const fileNameByKey: Record<Exclude<AnalysisChartKey, "deep_analysis">, string> = {
  sentiment_distribution: "sentiment-distribution.svg",
  topic_ranking: "topic-ranking.svg",
  time_trend: "time-trend.svg",
  level_distribution: "level-distribution.svg",
  region_map: "region-map.svg",
  word_cloud: "word-cloud.png"
};

export const CHINA_REGION_ID_BY_NAME: Record<string, string> = {
  安徽: "anhui",
  北京: "beijing",
  重庆: "chongqing",
  福建: "fujian",
  甘肃: "gansu",
  广东: "guangdong",
  广西: "guangxi-zhuang",
  贵州: "guizhou",
  海南: "hainan",
  河北: "hebei",
  黑龙江: "heilongjiang",
  河南: "henan",
  香港: "hong-kong",
  湖北: "hubei",
  湖南: "hunan",
  江苏: "jiangsu",
  江西: "jiangxi",
  吉林: "jilin",
  辽宁: "liaoning",
  澳门: "macau",
  内蒙古: "nei-mongol",
  宁夏: "ningxia-hui",
  青海: "quinghai",
  陕西: "shaanxi",
  山东: "shandong",
  上海: "shanghai",
  山西: "shanxi",
  四川: "sichuan",
  台湾: "taiwan",
  天津: "tianjin",
  新疆: "xinjiang-uygur",
  西藏: "xizang",
  云南: "yunnan",
  浙江: "zhejiang"
};

const baseChinaMapLocations = chinaMap.locations as ChinaMapLocation[];
const taiwanMapLocation: ChinaMapLocation = {
  id: "taiwan",
  name: "台湾",
  paths: (taiwanMainMap.locations as Array<{ path: string }>).map((location) => location.path),
  transform: "translate(598 444) scale(0.086) translate(-312 -322)"
};
const supplementalChinaMapLocations = baseChinaMapLocations.some((location) => location.id === taiwanMapLocation.id) ? [] : [taiwanMapLocation];

export const chinaMapLocations = [...baseChinaMapLocations, ...supplementalChinaMapLocations];
export const chinaMapViewBox = chinaMap.viewBox;

const palette = ["#1e73d6", "#fb7299", "#29bf73", "#f5a524", "#7c6ff6", "#16a3a8", "#ef4b5d", "#8b5cf6"];
const axis = "#7b8798";
const text = "#1f2937";
const muted = "#65748b";
const grid = "#d7dee8";
const panel = "#ffffff";
const pale = "#e8eef7";

export function getAutoAnalysisSource(hasComments: boolean, hasDynamics: boolean, latestSource?: AnalysisSource | null): AnalysisSource | null {
  if (latestSource === "comments" && hasComments) return "comments";
  if (latestSource === "dynamics" && hasDynamics) return "dynamics";
  if (latestSource === "all" && (hasComments || hasDynamics)) return hasComments && hasDynamics ? "all" : hasComments ? "comments" : "dynamics";
  if (hasComments && hasDynamics) return "all";
  if (hasComments) return "comments";
  if (hasDynamics) return "dynamics";
  return null;
}

export function analysisSourceLabel(source: AnalysisSource | null) {
  if (source === "comments") return "评论数据";
  if (source === "dynamics") return "动态数据";
  if (source === "all") return "评论 + 动态";
  return "等待爬取数据";
}

export function getAnalysisChartOptionsForSource(source: AnalysisSource | null) {
  if (source !== "dynamics") return analysisChartOptions;
  const unsupported = new Set(DYNAMICS_UNSUPPORTED_CHART_KEYS);
  return analysisChartOptions.filter((item) => !unsupported.has(item.key));
}

export function normalizeAnalysisChartKeys(value: unknown, source?: AnalysisSource | null): AnalysisChartKey[] {
  const allowed = getAnalysisChartOptionsForSource(source ?? null).map((item) => item.key);
  if (!Array.isArray(value)) return [...allowed];
  const valid = new Set(allowed);
  const selected = value.filter((item): item is AnalysisChartKey => typeof item === "string" && valid.has(item as AnalysisChartKey));
  return selected.length ? selected : [...allowed];
}

export function hasAnalysisChart(result: AnalysisResult, key: AnalysisChartKey) {
  const keys = normalizeAnalysisChartKeys(result.meta?.chart_keys, result.meta?.source);
  return keys.includes(key);
}

export async function buildAnalysisChartAssets(result: AnalysisResult): Promise<ChartAsset[]> {
  const keys = normalizeAnalysisChartKeys(result.meta?.chart_keys, result.meta?.source);
  const assets: ChartAsset[] = [];
  for (const key of keys) {
    if (key === "deep_analysis") continue;
    if (key === "word_cloud") {
      if (result.word_cloud_image_path) {
        assets.push({
          key,
          filename: fileNameByKey[key],
          title: chartTitleByKey[key],
          file_path: result.word_cloud_image_path,
          mime_type: "image/png"
        });
      } else if (result.word_cloud_image?.startsWith("data:image/png;base64,")) {
        assets.push({
          key,
          filename: fileNameByKey[key],
          title: chartTitleByKey[key],
          data_url: result.word_cloud_image,
          mime_type: "image/png"
        });
      }
      continue;
    }
    const svg = await buildChartSvg(result, key);
    if (!svg) continue;
    assets.push({
      key,
      filename: fileNameByKey[key],
      title: chartTitleByKey[key],
      svg
    });
  }
  return assets;
}

export function getRegionValueByMapId(regionCounts: ChartDatum[], mapId: string) {
  const item = regionCounts.find((entry) => CHINA_REGION_ID_BY_NAME[entry.name] === mapId);
  return numberValue(item);
}

export function unmappedDomesticRegions(regionCounts: ChartDatum[]) {
  return regionCounts.filter((item) => !CHINA_REGION_ID_BY_NAME[item.name] && numberValue(item) > 0);
}

export function getMapLocationPaths(location: ChinaMapLocation) {
  if (location.paths?.length) return location.paths;
  return location.path ? [location.path] : [];
}

export function regionFill(value: number, totalValue: number) {
  if (!value || totalValue <= 0) return "#dfe8f3";
  const percent = (value / totalValue) * 100;
  const lightness =
    percent >= 30 ? 34 :
    percent >= 20 ? 40 :
    percent >= 10 ? 48 :
    percent >= 5 ? 56 :
    percent >= 2 ? 66 :
    percent >= 1 ? 76 :
    84;
  return `hsl(147 58% ${lightness}%)`;
}

export function regionStroke(_value: number, _maxValue: number) {
  return "rgba(255,255,255,0.72)";
}

export function regionStrokeWidth(_value: number, _maxValue: number) {
  return 0.8;
}

async function buildChartSvg(result: AnalysisResult, key: Exclude<AnalysisChartKey, "deep_analysis" | "word_cloud">) {
  switch (key) {
    case "sentiment_distribution":
      return donutSvg("情绪分布", result.sentiment_counts);
    case "topic_ranking":
      return horizontalBarSvg("主题排行", result.topic_counts, 820, 74);
    case "time_trend":
      return lineSvg("时间趋势", result.time_series);
    case "level_distribution":
      return verticalBarSvg("等级分布", result.user_level_counts);
    case "region_map":
      return mapSvg("地域分布", result.region_counts, result.overseas_region_counts);
  }
}

function wrapSvg(title: string, width: number, height: number, content: string, subtitle?: string) {
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeXml(title)}">`,
    `<rect width="${width}" height="${height}" rx="18" fill="${panel}"/>`,
    `<text x="28" y="38" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="22" font-weight="700" fill="${text}">${escapeXml(title)}</text>`,
    subtitle ? `<text x="28" y="62" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="13" fill="${muted}">${escapeXml(subtitle)}</text>` : "",
    content,
    "</svg>"
  ].join("");
}

function donutSvg(title: string, data: ChartDatum[]) {
  const items = normalizeData(data).slice(0, 8);
  const total = sumValues(items);
  if (!items.length || total <= 0) return emptySvg(title);
  const cx = 160;
  const cy = 142;
  const radius = 76;
  const stroke = 34;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  const slices = items
    .map((item, index) => {
      const value = numberValue(item);
      const length = (value / total) * circumference;
      const dash = `${length} ${circumference - length}`;
      const circle = `<circle cx="${cx}" cy="${cy}" r="${radius}" fill="none" stroke="${palette[index % palette.length]}" stroke-width="${stroke}" stroke-dasharray="${dash}" stroke-dashoffset="${-offset}" transform="rotate(-90 ${cx} ${cy})"/>`;
      offset += length;
      return circle;
    })
    .join("");
  const labels = items
    .map((item, index) => {
      const y = 92 + index * 34;
      const value = numberValue(item);
      const percent = `${((value / total) * 100).toFixed(1)}%`;
      return `<g><rect x="315" y="${y - 12}" width="13" height="13" rx="3" fill="${palette[index % palette.length]}"/><text x="338" y="${y}" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="15" fill="${text}">${escapeXml(item.name)} ${value} (${percent})</text></g>`;
    })
    .join("");
  const content = `${slices}<circle cx="${cx}" cy="${cy}" r="52" fill="${panel}"/><text x="${cx}" y="${cy - 4}" text-anchor="middle" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="20" font-weight="700" fill="${text}">${total}</text><text x="${cx}" y="${cy + 20}" text-anchor="middle" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="13" fill="${muted}">总量</text>${labels}`;
  return wrapSvg(title, 620, 310, content);
}

function horizontalBarSvg(title: string, data: ChartDatum[], width = 820, labelWidth = 180) {
  const items = normalizeData(data).slice(0, 12);
  if (!items.length) return emptySvg(title);
  const max = Math.max(...items.map(numberValue), 1);
  const rowHeight = 34;
  const top = 80;
  const chartWidth = width - labelWidth - 80;
  const height = Math.max(260, top + items.length * rowHeight + 36);
  const rows = items
    .map((item, index) => {
      const value = numberValue(item);
      const barWidth = (value / max) * chartWidth;
      const y = top + index * rowHeight;
      return [
        `<text x="28" y="${y + 19}" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="14" fill="${text}">${escapeXml(compactText(item.name, 22))}</text>`,
        `<rect x="${labelWidth}" y="${y}" width="${barWidth}" height="22" rx="8" fill="${palette[index % palette.length]}"/>`,
        `<text x="${labelWidth + barWidth + 10}" y="${y + 17}" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="13" fill="${muted}">${value}</text>`
      ].join("");
    })
    .join("");
  return wrapSvg(title, width, height, rows);
}

function verticalBarSvg(title: string, data: ChartDatum[]) {
  const items = normalizeData(data);
  if (!items.length) return emptySvg(title);
  const width = 740;
  const height = 330;
  const left = 54;
  const bottom = 260;
  const chartHeight = 170;
  const max = Math.max(...items.map(numberValue), 1);
  const band = (width - left - 42) / items.length;
  const gridLines = [0, 0.25, 0.5, 0.75, 1]
    .map((ratio) => {
      const y = bottom - ratio * chartHeight;
      return `<line x1="${left}" y1="${y}" x2="${width - 30}" y2="${y}" stroke="${grid}" stroke-dasharray="4 4"/><text x="18" y="${y + 4}" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="11" fill="${muted}">${Math.round(max * ratio)}</text>`;
    })
    .join("");
  const bars = items
    .map((item, index) => {
      const value = numberValue(item);
      const barHeight = (value / max) * chartHeight;
      const x = left + index * band + band * 0.2;
      const y = bottom - barHeight;
      const barWidth = band * 0.6;
      return `<rect x="${x}" y="${y}" width="${barWidth}" height="${barHeight}" rx="8" fill="#29bf73"/><text x="${x + barWidth / 2}" y="${bottom + 24}" text-anchor="middle" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="13" fill="${text}">${escapeXml(item.name)}</text><text x="${x + barWidth / 2}" y="${y - 8}" text-anchor="middle" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="12" fill="${muted}">${value}</text>`;
    })
    .join("");
  return wrapSvg(title, width, height, gridLines + bars);
}

function lineSvg(title: string, data: ChartDatum[]) {
  const items = normalizeData(data).slice(-30);
  if (!items.length) return emptySvg(title);
  const width = 820;
  const height = 340;
  const left = 56;
  const top = 82;
  const chartWidth = 710;
  const chartHeight = 180;
  const max = Math.max(...items.map((item) => Math.max(numberValue({ value: item.count }), numberValue({ value: item.likes }))), 1);
  const step = items.length <= 1 ? chartWidth : chartWidth / (items.length - 1);
  const point = (item: ChartDatum, index: number, field: "count" | "likes") => {
    const raw = field === "count" ? item.count : item.likes;
    const value = typeof raw === "number" ? raw : 0;
    const x = left + index * step;
    const y = top + chartHeight - (value / max) * chartHeight;
    return `${x},${y}`;
  };
  const grids = [0, 0.25, 0.5, 0.75, 1]
    .map((ratio) => {
      const y = top + chartHeight - ratio * chartHeight;
      return `<line x1="${left}" y1="${y}" x2="${left + chartWidth}" y2="${y}" stroke="${grid}" stroke-dasharray="4 4"/>`;
    })
    .join("");
  const labels = items
    .map((item, index) => {
      if (index % Math.max(1, Math.ceil(items.length / 7)) !== 0) return "";
      const x = left + index * step;
      return `<text x="${x}" y="${top + chartHeight + 28}" text-anchor="middle" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="12" fill="${muted}">${escapeXml(item.name)}</text>`;
    })
    .join("");
  const countLine = `<polyline points="${items.map((item, index) => point(item, index, "count")).join(" ")}" fill="none" stroke="#1e73d6" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>`;
  const likeLine = `<polyline points="${items.map((item, index) => point(item, index, "likes")).join(" ")}" fill="none" stroke="#fb7299" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`;
  const legend = `<circle cx="620" cy="38" r="6" fill="#1e73d6"/><text x="634" y="43" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="13" fill="${text}">数量</text><circle cx="695" cy="38" r="6" fill="#fb7299"/><text x="709" y="43" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="13" fill="${text}">点赞</text>`;
  return wrapSvg(title, width, height, grids + countLine + likeLine + labels + legend);
}

function mapSvg(title: string, regionCounts: ChartDatum[], overseasCounts: ChartDatum[]) {
  const regionTotal = sumValues(regionCounts) + sumValues(overseasCounts);
  const maxPercent = regionTotal > 0 ? Math.max(...regionCounts.map((item) => (numberValue(item) / regionTotal) * 100), 0) : 0;
  const paths = chinaMapLocations
    .map((location) => {
      const value = getRegionValueByMapId(regionCounts, location.id);
      const locationPaths = getMapLocationPaths(location);
      const transform = location.transform ? ` transform="${location.transform}"` : "";
      const mainPaths = locationPaths
        .map(
          (path) =>
            `<path d="${path}"${transform} fill="${regionFill(value, regionTotal)}" stroke="${regionStroke(value, regionTotal)}" stroke-width="${regionStrokeWidth(value, regionTotal)}"><title>${escapeXml(location.name)} ${value}</title></path>`,
        )
        .join("");
      return mainPaths;
    })
    .join("");
  const overseas = [...unmappedDomesticRegions(regionCounts), ...normalizeData(overseasCounts)].slice(0, 8);
  const overseasList =
    overseas.length > 0
      ? overseas
          .map((item, index) => `<text x="575" y="${106 + index * 24}" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="13" fill="${text}">${escapeXml(item.name)}：${numberValue(item)}</text>`)
          .join("")
      : `<text x="575" y="106" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="13" fill="${muted}">暂无海外或未上图地区</text>`;
  const legend = [1, 5, 10, 20, 30]
    .map((percent, index) => `<rect x="${60 + index * 44}" y="488" width="34" height="14" rx="4" fill="${regionFill(regionTotal * percent / 100, regionTotal)}"/><text x="${60 + index * 44}" y="515" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="10" fill="${muted}">${percent}%</text>`)
    .join("");
  const map = `<g transform="translate(35 68) scale(0.66)">${paths}</g>`;
  const content = `${map}<text x="575" y="76" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="15" font-weight="700" fill="${text}">海外 / 未上图</text>${overseasList}${legend}<text x="60" y="540" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="12" fill="${muted}">颜色按占总人数百分比分档，地区标值仍为人数，总人数 ${regionTotal}，最高占比 ${formatNumber(maxPercent)}%</text>`;
  return wrapSvg(title, 820, 550, content);
}

function emptySvg(title: string) {
  return wrapSvg(title, 620, 220, `<text x="28" y="112" font-family="Arial, 'Microsoft YaHei', sans-serif" font-size="15" fill="${muted}">暂无可导出的图表数据</text>`);
}

function normalizeData(data: ChartDatum[] | undefined) {
  return (Array.isArray(data) ? data : []).filter((item) => item && item.name && numberValue(item) > 0);
}

function sumValues(items: ChartDatum[]) {
  return items.reduce((total, item) => total + numberValue(item), 0);
}

function numberValue(item: Partial<ChartDatum> | undefined) {
  const value = item?.value ?? item?.count ?? 0;
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function compactText(value: string, limit: number) {
  return value.length <= limit ? value : `${value.slice(0, limit - 1)}…`;
}

function formatNumber(value: number) {
  return Number(value.toFixed(2));
}

function escapeXml(value: unknown) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
