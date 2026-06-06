"""
LLM-powered opinion and sentiment analysis for crawled Bilibili data.
"""
from __future__ import annotations

import base64
import io
import json
import math
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import requests


ProgressCallback = Callable[[str, int], None]


class AnalysisError(RuntimeError):
    """Raised when analysis cannot be completed."""


class AnalysisCancelled(AnalysisError):
    """Raised when the user cancels an analysis task."""


class LLMAnalysisProcessor:
    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    DEFAULT_MODEL = "gpt-4.1-mini"
    WORD_CLOUD_LIMIT = 80
    WORD_CLOUD_WIDTH = 800
    WORD_CLOUD_HEIGHT = 440
    ALL_CHART_KEYS = [
        "sentiment_distribution",
        "topic_ranking",
        "time_trend",
        "level_distribution",
        "region_map",
        "word_cloud",
        "deep_analysis",
    ]
    SENTIMENT_KEYS = {"sentiment_distribution"}
    DYNAMICS_UNSUPPORTED_CHART_KEYS = {"time_trend", "level_distribution", "region_map", "deep_analysis"}
    DOMESTIC_REGIONS = {
        "北京",
        "天津",
        "上海",
        "重庆",
        "河北",
        "山西",
        "辽宁",
        "吉林",
        "黑龙江",
        "江苏",
        "浙江",
        "安徽",
        "福建",
        "江西",
        "山东",
        "河南",
        "湖北",
        "湖南",
        "广东",
        "海南",
        "四川",
        "贵州",
        "云南",
        "陕西",
        "甘肃",
        "青海",
        "台湾",
        "内蒙古",
        "广西",
        "西藏",
        "宁夏",
        "新疆",
        "香港",
        "澳门",
    }
    REGION_ALIASES = {
        "广西壮族自治区": "广西",
        "内蒙古自治区": "内蒙古",
        "宁夏回族自治区": "宁夏",
        "新疆维吾尔自治区": "新疆",
        "西藏自治区": "西藏",
        "香港特别行政区": "香港",
        "澳门特别行政区": "澳门",
        "中国香港": "香港",
        "中国澳门": "澳门",
        "中国台湾": "台湾",
    }
    STOP_WORDS = {
        "这个",
        "还是",
        "有点",
        "希望",
        "作者",
        "同意",
        "视频",
        "评论",
        "动态",
        "一个",
        "没有",
        "就是",
        "不是",
        "可以",
        "感觉",
        "真的",
        "因为",
        "所以",
        "如果",
        "但是",
        "这样",
        "现在",
        "大家",
        "内容",
        "问题",
        "图片",
        "转发",
        "抽奖",
        "分享",
        "图片动态",
        "转发抽奖",
        "分享动态",
    }

    @classmethod
    def analyze(
        cls,
        comments: list[dict[str, Any]],
        dynamics: list[dict[str, Any]],
        params: dict[str, Any],
        progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        source = cls._normalize_source(comments, dynamics, params.get("source"))
        strategy = params.get("strategy") or "sample"
        sample_size = cls._clamp_int(params.get("sample_size"), 300, 20, 2000)
        batch_size = cls._clamp_int(params.get("batch_size"), 80, 20, 200)
        chart_keys = cls._normalize_chart_keys(params.get("chart_keys"), source)
        llm_config = params.get("llm_config") or {}

        records = cls._build_records(comments, dynamics, source)
        if not records:
            raise AnalysisError("没有可分析的数据，请先完成评论或动态爬取")

        api_key = str(llm_config.get("api_key") or "").strip()
        model = str(llm_config.get("model") or "").strip() or cls.DEFAULT_MODEL
        base_url = str(llm_config.get("base_url") or "").strip() or cls.DEFAULT_BASE_URL
        if not api_key:
            raise AnalysisError("缺少 LLM API Key")

        if progress:
            progress("正在准备分析样本", 8)

        selected = cls._select_records(records, sample_size) if strategy == "sample" else records
        batches = cls._chunk_records(selected, batch_size)
        batch_results: list[dict[str, Any]] = []

        for index, batch in enumerate(batches, start=1):
            if cancel_event and cancel_event.is_set():
                raise AnalysisCancelled("分析已被取消")
            if progress:
                percent = 10 + int(index / max(1, len(batches)) * 70)
                progress(f"正在调用 LLM 分析第 {index}/{len(batches)} 批", percent)
            batch_results.append(cls._call_llm(base_url, api_key, model, batch, source, strategy, chart_keys))

        cls._raise_if_cancelled(cancel_event)
        merged = cls._merge_llm_results(batch_results, selected, len(records), len(comments), len(dynamics), strategy, chart_keys)
        if progress and len(batch_results) > 1:
            progress("正在整合分批总结", 84)
        cls._integrate_summary(base_url, api_key, model, batch_results, merged, strategy, len(records), len(selected))
        cls._raise_if_cancelled(cancel_event)
        if progress:
            progress("正在汇总分析结果", 86)

        local_layers = cls._build_local_layers(records, selected, chart_keys)
        cls._raise_if_cancelled(cancel_event)
        location_stats = cls._location_stats(records)
        merged["overview"].update(location_stats)
        if cls._chart_enabled(chart_keys, "word_cloud") and not merged.get("word_counts"):
            merged["word_counts"] = cls._build_word_counts(selected)
        cls._raise_if_cancelled(cancel_event)
        result = {
            **merged,
            **local_layers,
            "meta": {
                "source": source,
                "strategy": strategy,
                "model": model,
                "total_records": len(records),
                "analyzed_records": len(selected),
                "batch_count": len(batches),
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "chart_keys": chart_keys,
                **location_stats,
            },
        }
        if cls._chart_enabled(chart_keys, "word_cloud"):
            if progress:
                progress("正在生成词云图", 88)
            cls._raise_if_cancelled(cancel_event)
            result["word_cloud_image"] = cls._build_word_cloud_image(result.get("word_counts", []))
            cls._raise_if_cancelled(cancel_event)
            if progress:
                progress("词云图已生成", 92)
        if progress:
            progress("正在生成分析报告", 95)
        result["report_markdown"] = cls._build_markdown_report(result)
        cls._raise_if_cancelled(cancel_event)
        if progress:
            progress("分析结果已就绪", 98)
        return result

    @classmethod
    def _call_llm(
        cls,
        base_url: str,
        api_key: str,
        model: str,
        records: list[dict[str, Any]],
        source: str,
        strategy: str,
        chart_keys: list[str],
    ) -> dict[str, Any]:
        endpoint = base_url.rstrip("/") + "/chat/completions"
        messages = [
            {
                "role": "system",
                "content": (
                    "你是中文社交媒体舆论分析师。只返回合法 JSON，不要输出 Markdown。"
                    "分类必须克制，不能捏造评论中不存在的事实。"
                ),
            },
            {
                "role": "user",
                "content": cls._build_prompt(records, source, strategy, chart_keys),
            },
        ]
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        session = requests.Session()
        session.trust_env = False
        try:
            response = session.post(endpoint, headers=headers, json=payload, timeout=90)
            if response.status_code in {400, 404, 422}:
                payload.pop("response_format", None)
                response = session.post(endpoint, headers=headers, json=payload, timeout=90)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise AnalysisError(f"LLM 请求失败: {exc}") from exc
        except ValueError as exc:
            raise AnalysisError("LLM 返回不是有效 JSON 响应") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AnalysisError("LLM 响应缺少 choices[0].message.content") from exc
        return cls._parse_json_object(str(content))

    @classmethod
    def _call_summary_llm(
        cls,
        base_url: str,
        api_key: str,
        model: str,
        batch_results: list[dict[str, Any]],
        merged: dict[str, Any],
        strategy: str,
        total_records: int,
        analyzed: int,
    ) -> dict[str, Any]:
        endpoint = base_url.rstrip("/") + "/chat/completions"
        prompt_payload = {
            "strategy": strategy,
            "total_records": total_records,
            "analyzed_records": analyzed,
            "batch_summaries": [str(item.get("summary") or "").strip() for item in batch_results if str(item.get("summary") or "").strip()],
            "insights": merged.get("insights", []),
            "risk_points": merged.get("risk_points", []),
            "notable_quotes": merged.get("notable_quotes", []),
        }
        messages = [
            {
                "role": "system",
                "content": (
                    "你是中文社交媒体舆论分析师。只返回合法 JSON，不要输出 Markdown。"
                    "必须综合批次结论，不能简单拼接，不能捏造评论中不存在的事实。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请把以下分批舆论分析结果整合为总总结。"
                    "返回 JSON 对象，字段：summary 字符串（一句话总体概括）；"
                    "summary_points 数组（4-7 条短句，分点清晰，不要出现批次编号）。"
                    "数据如下："
                    + json.dumps(prompt_payload, ensure_ascii=False)
                ),
            },
        ]
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.18,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        session = requests.Session()
        session.trust_env = False
        try:
            response = session.post(endpoint, headers=headers, json=payload, timeout=90)
            if response.status_code in {400, 404, 422}:
                payload.pop("response_format", None)
                response = session.post(endpoint, headers=headers, json=payload, timeout=90)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise AnalysisError(f"LLM 总结整合失败: {exc}") from exc
        except ValueError as exc:
            raise AnalysisError("LLM 总结整合返回不是有效 JSON 响应") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AnalysisError("LLM 总结整合响应缺少 choices[0].message.content") from exc
        parsed = cls._parse_json_object(str(content))
        summary = str(parsed.get("summary") or "").strip()
        points = cls._strings(parsed.get("summary_points"))[:7]
        if not summary and points:
            summary = points[0]
        if not summary:
            raise AnalysisError("LLM 总结整合缺少 summary")
        return {"summary": summary, "summary_points": points}

    @classmethod
    def _build_prompt(cls, records: list[dict[str, Any]], source: str, strategy: str, chart_keys: list[str]) -> str:
        compact_records = [
            {
                "id": item["id"],
                "type": item["type"],
                "content": item["content"][:600],
                "likes": item["likes"],
                "replies": item["replies"],
                "time": item["time_text"],
                "ip": item.get("ip_location", ""),
                "level": item.get("user_level", ""),
            }
            for item in records
        ]
        fields = [
            "summary 字符串，概括总体舆论走向；",
            "risk_points 数组，列出争议、误解、负面扩散风险；",
            "insights 数组，列出 3-6 条关键洞察；",
            "notable_quotes 数组，最多 5 条代表性评论短句。",
        ]
        if cls._needs_sentiment(chart_keys):
            fields.append("sentiment_counts 数组，元素为 {name,value}，name 只能是 正向/中性/负向；")
        if cls._chart_enabled(chart_keys, "topic_ranking"):
            fields.append("topic_counts 数组，最多 8 项，元素为 {name,value}；")
        if cls._chart_enabled(chart_keys, "word_cloud"):
            fields.append(f"word_counts 数组，最多 {cls.WORD_CLOUD_LIMIT} 项，元素为 {{name,value}}，name 使用 2-8 个字的中文关键词或短语；")
        if cls._chart_enabled(chart_keys, "deep_analysis"):
            fields.append(
                "deep_analysis 对象，包含 sociology、psychology、philosophy 三个字符串，分别从社会学、心理学、哲学角度剖析，必须基于评论证据，不能捏造事实；"
            )
        return (
            f"请分析以下 B 站{source}数据，策略为{strategy}。"
            "返回 JSON 对象，字段必须包含："
            + "".join(fields)
            + "value 必须是整数。数据如下："
            + json.dumps(compact_records, ensure_ascii=False)
        )

    @staticmethod
    def _extract_json_text(content: str) -> str:
        """Extract the outermost JSON object from LLM output using brace counting."""
        # 1. Strip markdown code fences
        text = re.sub(r"```(?:json)?\s*\n?", "", content)
        text = re.sub(r"\n?\s*```", "", text)
        # 2. Find the first '{' and track matching '}'
        start = text.find("{")
        if start == -1:
            raise AnalysisError("LLM 未返回可解析的 JSON 对象")
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        raise AnalysisError("LLM 返回中无法匹配 JSON 对象的闭合大括号")

    @classmethod
    def _parse_json_object(cls, content: str) -> dict[str, Any]:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            json_text = cls._extract_json_text(content)
            try:
                parsed = json.loads(json_text)
            except json.JSONDecodeError:
                # Last resort: try to repair trailing commas (common LLM mistake)
                repaired = re.sub(r",\s*([}\]])", r"\1", json_text)
                try:
                    parsed = json.loads(repaired)
                except json.JSONDecodeError as exc:
                    preview = json_text[:500] if len(json_text) > 500 else json_text
                    raise AnalysisError(
                        f"LLM JSON 解析失败: {exc}\n原始内容预览: {preview}"
                    ) from exc
        if not isinstance(parsed, dict):
            raise AnalysisError("LLM 返回 JSON 顶层不是对象")
        return parsed

    @staticmethod
    def _raise_if_cancelled(cancel_event: threading.Event | None) -> None:
        if cancel_event and cancel_event.is_set():
            raise AnalysisCancelled("分析已被取消")

    @classmethod
    def _integrate_summary(
        cls,
        base_url: str,
        api_key: str,
        model: str,
        batch_results: list[dict[str, Any]],
        merged: dict[str, Any],
        strategy: str,
        total_records: int,
        analyzed: int,
    ) -> None:
        fallback_points = cls._fallback_summary_points(batch_results, merged)
        if len(batch_results) <= 1:
            merged["summary_points"] = fallback_points
            return
        try:
            integrated = cls._call_summary_llm(base_url, api_key, model, batch_results, merged, strategy, total_records, analyzed)
        except Exception:
            merged["summary_points"] = fallback_points
            if fallback_points:
                merged["summary"] = "；".join(fallback_points[:2])
            return
        merged["summary"] = str(integrated.get("summary") or merged.get("summary") or "").strip()
        points = cls._strings(integrated.get("summary_points"))[:7]
        merged["summary_points"] = points or fallback_points

    @classmethod
    def _fallback_summary_points(cls, batch_results: list[dict[str, Any]], merged: dict[str, Any]) -> list[str]:
        points: list[str] = []
        points.extend(str(item.get("summary") or "").strip() for item in batch_results if str(item.get("summary") or "").strip())
        points.extend(cls._strings(merged.get("insights")))
        points.extend(cls._strings(merged.get("risk_points")))
        return cls._dedupe([cls._trim_sentence(item, 110) for item in points if item])[:7]

    @staticmethod
    def _trim_sentence(value: str, limit: int) -> str:
        text = re.sub(r"\s+", " ", value).strip(" ；;。")
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip("，,；;。") + "…"

    @classmethod
    def _build_records(
        cls,
        comments: list[dict[str, Any]],
        dynamics: list[dict[str, Any]],
        source: str,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        if source in {"comments", "all"}:
            records.extend(cls._comment_record(item) for item in comments)
        if source in {"dynamics", "all"}:
            records.extend(cls._dynamic_record(item) for item in dynamics)
        if source not in {"comments", "dynamics", "all"}:
            raise AnalysisError("未知分析数据源")
        return [item for item in records if item["content"]]

    @classmethod
    def _comment_record(cls, comment: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(comment.get("comment_id") or ""),
            "type": "comment_reply" if comment.get("is_reply") else "comment",
            "content": str(comment.get("content") or "").strip(),
            "likes": int(comment.get("like_count") or 0),
            "replies": int(comment.get("reply_count") or 0),
            "timestamp": int(comment.get("ctime") or 0),
            "time_text": str(comment.get("ctime_text") or ""),
            "ip_location": str(comment.get("ip_location") or ""),
            "user_level": cls._normalize_user_level(comment.get("user_level")) or "",
            "username": str(comment.get("username") or ""),
        }

    @staticmethod
    def _dynamic_record(dynamic: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(dynamic.get("dynamic_id") or ""),
            "type": f"dynamic:{dynamic.get('type') or 'unknown'}",
            "content": str(dynamic.get("content") or "").strip(),
            "likes": int(dynamic.get("like_count") or 0),
            "replies": int(dynamic.get("comment_count") or 0),
            "timestamp": int(dynamic.get("timestamp") or 0),
            "time_text": str(dynamic.get("publish_time") or ""),
            "ip_location": "",
            "user_level": "",
            "username": str(dynamic.get("username") or ""),
            "forwards": int(dynamic.get("forward_count") or 0),
        }

    @staticmethod
    def _normalize_user_level(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            if isinstance(value, float) and not value.is_integer():
                return None
            level = int(value)
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                numeric = float(text)
            except ValueError:
                return None
            if not numeric.is_integer():
                return None
            level = int(numeric)
        else:
            return None
        if 1 <= level <= 6:
            return level
        return None

    @classmethod
    def _select_records(cls, records: list[dict[str, Any]], sample_size: int) -> list[dict[str, Any]]:
        if len(records) <= sample_size:
            return records
        by_heat = sorted(records, key=lambda item: (item["likes"] * 2 + item["replies"], item["timestamp"]), reverse=True)
        by_time = sorted(records, key=lambda item: item["timestamp"], reverse=True)
        main = [item for item in records if item["type"] == "comment"]
        buckets = [
            by_heat[: math.ceil(sample_size * 0.45)],
            by_time[: math.ceil(sample_size * 0.35)],
            main[: math.ceil(sample_size * 0.2)],
        ]
        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in cls._flatten(buckets):
            key = f"{item['type']}:{item['id']}:{item['content'][:24]}"
            if key in seen:
                continue
            seen.add(key)
            selected.append(item)
            if len(selected) >= sample_size:
                return selected
        for item in records:
            if len(selected) >= sample_size:
                break
            key = f"{item['type']}:{item['id']}:{item['content'][:24]}"
            if key not in seen:
                selected.append(item)
                seen.add(key)
        return selected

    @staticmethod
    def _flatten(groups: Iterable[Iterable[dict[str, Any]]]) -> Iterable[dict[str, Any]]:
        for group in groups:
            yield from group

    @staticmethod
    def _chunk_records(records: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
        return [records[index : index + batch_size] for index in range(0, len(records), batch_size)]

    @classmethod
    def _merge_llm_results(
        cls,
        results: list[dict[str, Any]],
        selected: list[dict[str, Any]],
        total_records: int,
        total_comments: int,
        total_dynamics: int,
        strategy: str,
        chart_keys: list[str],
    ) -> dict[str, Any]:
        sentiment = Counter({"正向": 0, "中性": 0, "负向": 0})
        topics: Counter[str] = Counter()
        words: Counter[str] = Counter()
        risk_points: list[str] = []
        insights: list[str] = []
        quotes: list[str] = []
        summaries: list[str] = []
        deep_segments = {"sociology": [], "psychology": [], "philosophy": []}

        for result in results:
            summaries.append(str(result.get("summary") or "").strip())
            if cls._needs_sentiment(chart_keys):
                for item in cls._list_of_dicts(result.get("sentiment_counts")):
                    name = str(item.get("name") or "").strip()
                    if name in sentiment:
                        sentiment[name] += cls._safe_int(item.get("value"))
            if cls._chart_enabled(chart_keys, "topic_ranking"):
                for item in cls._list_of_dicts(result.get("topic_counts")):
                    name = str(item.get("name") or "").strip()
                    if name:
                        topics[name] += cls._safe_int(item.get("value"))
            if cls._chart_enabled(chart_keys, "word_cloud"):
                for item in cls._list_of_dicts(result.get("word_counts")):
                    name = str(item.get("name") or "").strip()
                    if name:
                        words[name] += cls._safe_int(item.get("value"))
            if cls._chart_enabled(chart_keys, "deep_analysis") and isinstance(result.get("deep_analysis"), dict):
                deep = result.get("deep_analysis") or {}
                for key in deep_segments:
                    text = str(deep.get(key) or "").strip()
                    if text:
                        deep_segments[key].append(text)
            risk_points.extend(cls._strings(result.get("risk_points")))
            insights.extend(cls._strings(result.get("insights")))
            quotes.extend(cls._strings(result.get("notable_quotes")))

        analyzed = len(selected)
        overview = {
            "total_records": total_records,
            "analyzed_records": analyzed,
            "comments": total_comments,
            "dynamics": total_dynamics,
            "risk_count": len(cls._dedupe(risk_points)),
        }
        summary = cls._compact_summary(summaries, strategy, total_records, analyzed)
        return {
            "summary": summary,
            "overview": overview,
            "sentiment_counts": cls._counter_items(sentiment, ["正向", "中性", "负向"]) if cls._needs_sentiment(chart_keys) else [],
            "topic_counts": cls._counter_items(topics)[:8] if cls._chart_enabled(chart_keys, "topic_ranking") else [],
            "word_counts": cls._counter_items(words)[: cls.WORD_CLOUD_LIMIT] if cls._chart_enabled(chart_keys, "word_cloud") else [],
            "risk_points": cls._dedupe(risk_points)[:8],
            "insights": cls._dedupe(insights)[:8],
            "notable_quotes": cls._dedupe(quotes)[:5],
            "deep_analysis": {
                key: cls._compact_analysis_segments(value)
                for key, value in deep_segments.items()
            }
            if cls._chart_enabled(chart_keys, "deep_analysis")
            else {"sociology": "", "psychology": "", "philosophy": ""},
        }

    @classmethod
    def _build_local_layers(
        cls,
        records: list[dict[str, Any]],
        selected: list[dict[str, Any]],
        chart_keys: list[str],
    ) -> dict[str, Any]:
        time_buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {"name": "", "count": 0, "likes": 0})
        region = Counter()
        overseas_region = Counter()
        user_levels = Counter()
        content_types = Counter()

        for item in records:
            day = cls._day_label(item)
            bucket = time_buckets[day]
            bucket["name"] = day
            bucket["count"] += 1
            bucket["likes"] += item["likes"]
            if cls._is_comment_record(item):
                normalized_region, is_domestic = cls._normalize_region(item.get("ip_location"))
                if normalized_region:
                    if is_domestic:
                        region[normalized_region] += 1
                    else:
                        overseas_region[normalized_region] += 1
            level = cls._normalize_user_level(item.get("user_level"))
            if level is not None:
                user_levels[f"Lv{level}"] += 1
            content_types[str(item["type"])] += 1

        engagement_items = sorted(
            selected,
            key=lambda item: item["likes"] * 2 + item["replies"] + int(item.get("forwards") or 0),
            reverse=True,
        )[:10]
        return {
            "time_series": sorted(time_buckets.values(), key=lambda item: item["name"])[-14:]
            if cls._chart_enabled(chart_keys, "time_trend")
            else [],
            "region_counts": cls._counter_items(region)
            if cls._chart_enabled(chart_keys, "region_map")
            else [],
            "overseas_region_counts": cls._counter_items(overseas_region)
            if cls._chart_enabled(chart_keys, "region_map")
            else [],
            "user_level_counts": cls._counter_items(
                user_levels,
                [f"Lv{level}" for level in range(1, 7)],
                keep_zero_keys=[f"Lv{level}" for level in range(1, 7)],
            )
            if cls._chart_enabled(chart_keys, "level_distribution")
            else [],
            "content_type_counts": cls._counter_items(content_types),
            "engagement_items": [
                {
                    "name": item["content"][:28] + ("..." if len(item["content"]) > 28 else ""),
                    "likes": item["likes"],
                    "replies": item["replies"],
                    "type": item["type"],
                }
                for item in engagement_items
            ],
        }

    @classmethod
    def _build_markdown_report(
        cls,
        result: dict[str, Any],
        chart_assets: list[dict[str, Any]] | None = None,
        asset_dir_name: str = "",
    ) -> str:
        meta = result.get("meta") or {}
        chart_keys = cls._normalize_chart_keys(meta.get("chart_keys"), meta.get("source"))
        assets_by_key = {
            str(item.get("key")): str(item.get("filename") or "")
            for item in chart_assets or []
            if isinstance(item, dict) and item.get("key") and item.get("filename")
        }
        lines = [
            "# Bilibili 舆论分析报告",
            "",
            f"- 生成时间：{meta.get('generated_at', '')}",
            f"- 数据源：{meta.get('source', '')}",
            f"- 分析策略：{meta.get('strategy', '')}",
            f"- 模型：{meta.get('model', '')}",
            f"- 分析样本：{meta.get('analyzed_records', 0)} / {meta.get('total_records', 0)}",
            f"- IP 属地覆盖：{meta.get('ip_locations', 0)} / {int(meta.get('ip_locations', 0) or 0) + int(meta.get('missing_ip_locations', 0) or 0)}",
            f"- 分析模块：{'、'.join(chart_keys)}",
            "",
            "## 总结",
            str(result.get("summary") or ""),
        ]
        summary_points = cls._strings(result.get("summary_points"))
        if summary_points:
            lines.extend([""])
            lines.extend(f"- {item}" for item in summary_points)

        for key in chart_keys:
            if key == "sentiment_distribution":
                cls._append_chart_section(lines, "情绪分布", key, assets_by_key, asset_dir_name)
                lines.extend(cls._items_lines(result.get("sentiment_counts", [])))
            elif key == "topic_ranking":
                cls._append_chart_section(lines, "主题排行", key, assets_by_key, asset_dir_name)
                lines.extend(cls._items_lines(result.get("topic_counts", [])))
            elif key == "time_trend":
                cls._append_chart_section(lines, "时间趋势", key, assets_by_key, asset_dir_name)
                lines.extend(
                    f"- {item.get('name', '')}：数量 {item.get('count', 0)}，点赞 {item.get('likes', 0)}"
                    for item in result.get("time_series", [])
                    if isinstance(item, dict)
                )
            elif key == "level_distribution":
                cls._append_chart_section(lines, "等级分布", key, assets_by_key, asset_dir_name)
                lines.extend(cls._items_lines(result.get("user_level_counts", [])))
            elif key == "region_map":
                cls._append_chart_section(lines, "地域分布", key, assets_by_key, asset_dir_name)
                lines.extend(["", "### 国内 / 地图数据"])
                lines.extend(cls._items_lines(result.get("region_counts", [])))
                lines.extend(["", "### 海外 / 未知"])
                overseas = list(cls._items_lines(result.get("overseas_region_counts", [])))
                lines.extend(overseas if overseas else ["- 暂无"])
            elif key == "word_cloud":
                cls._append_chart_section(lines, "词云图", key, assets_by_key, asset_dir_name)
                lines.extend(cls._items_lines(result.get("word_counts", [])))
            elif key == "deep_analysis":
                lines.extend(["", "## 舆论深入剖析"])
                deep = result.get("deep_analysis") if isinstance(result.get("deep_analysis"), dict) else {}
                lines.extend(
                    [
                        "",
                        "### 社会学视角",
                        str((deep or {}).get("sociology") or "暂无剖析"),
                        "",
                        "### 心理学视角",
                        str((deep or {}).get("psychology") or "暂无剖析"),
                        "",
                        "### 哲学视角",
                        str((deep or {}).get("philosophy") or "暂无剖析"),
                    ]
                )

        lines.extend(["", "## 关键洞察"])
        lines.extend(f"- {item}" for item in result.get("insights", []))
        lines.extend(["", "## 风险点"])
        risks = result.get("risk_points", [])
        lines.extend((f"- {item}" for item in risks) if risks else ["- 暂无明显风险点"])
        lines.extend(["", "## 代表性评论"])
        lines.extend(f"- {item}" for item in result.get("notable_quotes", []))
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _compact_summary(summaries: list[str], strategy: str, total_records: int, analyzed: int) -> str:
        clean = [item for item in summaries if item]
        if not clean:
            return "LLM 未返回有效总结。"
        if len(clean) == 1:
            return clean[0]
        joined = "；".join(clean[:5])
        return f"本次采用{strategy}策略，分析 {analyzed}/{total_records} 条数据。分批结论概览：{joined}"

    @staticmethod
    def _day_label(item: dict[str, Any]) -> str:
        timestamp = int(item.get("timestamp") or 0)
        if timestamp > 0:
            return datetime.fromtimestamp(timestamp).strftime("%m-%d")
        text = str(item.get("time_text") or "")
        if text:
            return text[:10]
        return time.strftime("%m-%d")

    @classmethod
    def _location_stats(cls, records: list[dict[str, Any]]) -> dict[str, Any]:
        comment_records = [item for item in records if cls._is_comment_record(item)]
        ip_locations = sum(1 for item in comment_records if str(item.get("ip_location") or "").strip())
        total = len(comment_records)
        return {
            "ip_locations": ip_locations,
            "missing_ip_locations": total - ip_locations,
            "ip_location_coverage": round(ip_locations / total, 4) if total else 0,
        }

    @staticmethod
    def _is_comment_record(item: dict[str, Any]) -> bool:
        return str(item.get("type") or "").startswith("comment")

    @staticmethod
    def _counter_items(
        counter: Counter[str],
        order: list[str] | None = None,
        keep_zero_keys: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        if order:
            keep = set(keep_zero_keys or [])
            return [{"name": name, "value": int(counter.get(name, 0))} for name in order if counter.get(name, 0) or name in keep]
        return [{"name": name, "value": int(value)} for name, value in counter.most_common()]

    @classmethod
    def _normalize_source(cls, comments: list[dict[str, Any]], dynamics: list[dict[str, Any]], value: Any) -> str:
        source = str(value or "auto").strip()
        if source in {"comments", "dynamics", "all"}:
            return source
        if comments and dynamics:
            return "all"
        if comments:
            return "comments"
        if dynamics:
            return "dynamics"
        return "all"

    @classmethod
    def _normalize_chart_keys(cls, value: Any, source: Any = None) -> list[str]:
        allowed_keys = list(cls.ALL_CHART_KEYS)
        if str(source or "") == "dynamics":
            allowed_keys = [key for key in allowed_keys if key not in cls.DYNAMICS_UNSUPPORTED_CHART_KEYS]
        if not isinstance(value, list):
            return allowed_keys
        selected: list[str] = []
        for item in value:
            key = str(item)
            if key in allowed_keys and key not in selected:
                selected.append(key)
        return selected or allowed_keys

    @classmethod
    def _chart_enabled(cls, chart_keys: list[str], key: str) -> bool:
        return key in chart_keys

    @classmethod
    def _needs_sentiment(cls, chart_keys: list[str]) -> bool:
        return any(key in chart_keys for key in cls.SENTIMENT_KEYS)

    @classmethod
    def _normalize_region(cls, value: Any) -> tuple[str, bool]:
        text = str(value or "").strip()
        if not text:
            return "未知", False
        text = re.sub(r"^(IP属地|属地|来自)[:：\s]*", "", text)
        text = text.strip()
        text = cls.REGION_ALIASES.get(text, text)
        if text in cls.DOMESTIC_REGIONS:
            return text, True
        for region in cls.DOMESTIC_REGIONS:
            if text.startswith(region):
                return region, True
        for suffix in ["省", "市", "自治区", "特别行政区"]:
            if text.endswith(suffix):
                candidate = text[: -len(suffix)]
                candidate = cls.REGION_ALIASES.get(candidate, candidate)
                if candidate in cls.DOMESTIC_REGIONS:
                    return candidate, True
        return text, False

    @classmethod
    def _build_word_counts(cls, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counter: Counter[str] = Counter()
        texts = [str(item.get("content") or "") for item in records]
        try:
            import jieba
        except Exception:
            return cls._build_word_counts_by_regex(texts)

        text = "\n".join(texts).replace("\u3000", " ")
        for token in jieba.lcut(text):
            token = cls._clean_word_token(token)
            if token:
                counter[token] += 1
        return cls._counter_items(counter)[: cls.WORD_CLOUD_LIMIT]

    @classmethod
    def _build_word_counts_by_regex(cls, texts: list[str]) -> list[dict[str, Any]]:
        counter: Counter[str] = Counter()
        for content in texts:
            chunks = re.findall(r"[\u4e00-\u9fff]{2,12}|[A-Za-z0-9][A-Za-z0-9_+-]{1,24}", content)
            for chunk in chunks:
                if chunk in cls.STOP_WORDS:
                    continue
                if re.fullmatch(r"[\u4e00-\u9fff]{2,12}", chunk):
                    if len(chunk) <= 4:
                        tokens = [chunk]
                    else:
                        tokens = [chunk[index : index + 2] for index in range(0, len(chunk) - 1)]
                        tokens.extend(chunk[index : index + 3] for index in range(0, len(chunk) - 2))
                else:
                    tokens = [chunk.lower()]
                for token in tokens:
                    token = cls._clean_word_token(token)
                    if token:
                        counter[token] += 1
        return cls._counter_items(counter)[: cls.WORD_CLOUD_LIMIT]

    @classmethod
    def _clean_word_token(cls, token: Any) -> str:
        text = str(token or "").strip().lower()
        if not text or text in cls.STOP_WORDS:
            return ""
        if len(text) < 2:
            return ""
        if re.fullmatch(r"[\W_]+", text):
            return ""
        if re.fullmatch(r"\d+", text):
            return ""
        if re.fullmatch(r"[\u4e00-\u9fff]+", text):
            return text
        if re.fullmatch(r"[a-z0-9\u4e00-\u9fff][a-z0-9\u4e00-\u9fff_+-]{1,24}", text):
            return text
        if re.fullmatch(r"[a-z0-9][a-z0-9_+-]{1,24}", text):
            return text
        return ""

    @classmethod
    def _build_word_cloud_image(cls, word_counts: Any) -> str:
        import sys
        import threading

        frequencies: dict[str, int] = {}
        for item in cls._list_of_dicts(word_counts):
            name = cls._clean_word_token(item.get("name"))
            value = cls._safe_int(item.get("value"))
            if name and value > 0:
                frequencies[name] = frequencies.get(name, 0) + value
        if not frequencies:
            print("[analysis] word_cloud: no frequencies, skip", file=sys.stderr)
            return ""

        try:
            print("[analysis] word_cloud: importing wordcloud...", file=sys.stderr)
            from wordcloud import WordCloud
            print("[analysis] word_cloud: import done", file=sys.stderr)
        except Exception as exc:
            print(f"[analysis] word_cloud: import failed: {exc}", file=sys.stderr)
            return ""

        font_path = cls._word_cloud_font_path()
        print(f"[analysis] word_cloud: font_path={font_path}", file=sys.stderr)

        result_holder: dict[str, Any] = {"image": ""}
        error_holder: dict[str, Any] = {"error": None}

        def _generate() -> None:
            try:
                print("[analysis] word_cloud: building WordCloud instance...", file=sys.stderr)
                options: dict[str, Any] = {
                    "width": cls.WORD_CLOUD_WIDTH,
                    "height": cls.WORD_CLOUD_HEIGHT,
                    "background_color": "white",
                    "max_words": cls.WORD_CLOUD_LIMIT,
                    "stopwords": set(cls.STOP_WORDS),
                    "collocations": False,
                    "prefer_horizontal": 0.72,
                    "relative_scaling": 0.55,
                    "margin": 2,
                    "random_state": 42,
                    "colormap": "viridis",
                }
                if font_path:
                    options["font_path"] = font_path
                print("[analysis] word_cloud: WordCloud(**options)...", file=sys.stderr)
                word_cloud = WordCloud(**options)
                print("[analysis] word_cloud: generate_from_frequencies...", file=sys.stderr)
                word_cloud.generate_from_frequencies(frequencies)
                print("[analysis] word_cloud: saving to PNG buffer...", file=sys.stderr)
                buffer = io.BytesIO()
                word_cloud.to_image().save(buffer, format="PNG", optimize=True)
                print("[analysis] word_cloud: encoding base64...", file=sys.stderr)
                result_holder["image"] = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
                print("[analysis] word_cloud: done", file=sys.stderr)
            except Exception as exc:
                error_holder["error"] = exc
                print(f"[analysis] word_cloud: error: {exc}", file=sys.stderr)

        thread = threading.Thread(target=_generate, daemon=True)
        thread.start()
        thread.join(timeout=30)
        if thread.is_alive():
            print("[analysis] word_cloud: TIMEOUT after 30s — wordcloud generation hung", file=sys.stderr)
            return ""
        if error_holder["error"] is not None:
            return ""
        return result_holder["image"]

    @staticmethod
    def _word_cloud_font_path() -> str:
        # Prefer single-face .ttf over multi-face .ttc (PIL has known issues with .ttc)
        # Skip fonts larger than 18 MB — they cause extreme slowdown on first load
        font_candidates = [
            # .ttf fonts first (single face, fast to load)
            ("C:/Windows/Fonts/simhei.ttf", 18 * 1024 * 1024),
            ("C:/Windows/Fonts/simkai.ttf", 18 * 1024 * 1024),
            ("C:/Windows/Fonts/simfang.ttf", 18 * 1024 * 1024),
            ("C:/Windows/Fonts/Deng.ttf", 18 * 1024 * 1024),
            ("C:/Windows/Fonts/Dengb.ttf", 18 * 1024 * 1024),
            # .ttc fonts (may be slow but serve as fallback)
            ("C:/Windows/Fonts/msyh.ttc", 18 * 1024 * 1024),
            ("C:/Windows/Fonts/msyhbd.ttc", 18 * 1024 * 1024),
            ("C:/Windows/Fonts/simsun.ttc", 18 * 1024 * 1024),
            ("C:/Windows/Fonts/NotoSansCJK-Regular.ttc", 18 * 1024 * 1024),
        ]
        for path_str, max_size in font_candidates:
            path = Path(path_str)
            if not path.exists():
                continue
            try:
                if path.stat().st_size > max_size:
                    continue
            except OSError:
                continue
            return str(path)
        return ""

    @staticmethod
    def _compact_analysis_segments(items: list[str]) -> str:
        clean = [item for item in items if item]
        if not clean:
            return ""
        if len(clean) == 1:
            return clean[0]
        return "；".join(clean[:5])

    @staticmethod
    def _append_chart_section(
        lines: list[str],
        title: str,
        key: str,
        assets_by_key: dict[str, str],
        asset_dir_name: str,
    ) -> None:
        lines.extend(["", f"## {title}"])
        filename = assets_by_key.get(key)
        if filename and asset_dir_name:
            lines.extend(["", f"![{title}]({asset_dir_name}/{filename})", ""])

    @staticmethod
    def _items_lines(value: Any) -> Iterable[str]:
        if not isinstance(value, list):
            return []
        return (
            f"- {item.get('name', '')}：{item.get('value', item.get('count', 0))}"
            for item in value
            if isinstance(item, dict)
        )

    @staticmethod
    def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    @staticmethod
    def _strings(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _clamp_int(cls, value: Any, fallback: int, minimum: int, maximum: int) -> int:
        parsed = cls._safe_int(value)
        if parsed <= 0:
            parsed = fallback
        return max(minimum, min(maximum, parsed))
