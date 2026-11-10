# -*- coding: utf-8 -*-
"""大模型 JSON 客户端 + 用量计费记账（OpenAI / DeepSeek 兼容协议，仅标准库）。

与 `pipelines/kg/llm.py` 保持一致的调用方式，额外提供：
- 每次调用的 token 用量采集（`usage` 字段）；
- 无 Key 时的 token 预估（按 0.6 token/汉字折算），保证离线也能出账；
- 按阶段累计的账单汇总，输出 USD / CNY。

环境变量：`HARVEST_LLM_API_KEY` / `DEEPSEEK_API_KEY`，未设置时各阶段回退规则实现。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
_KEY_ENVS = ("HARVEST_LLM_API_KEY", "KG_LLM_API_KEY", "DEEPSEEK_API_KEY")

# USD / 1M tokens。键为模型名；未命中时按 flash 档计价（可用环境变量覆盖）。
PRICE_TABLE: dict[str, dict[str, float]] = {
    "deepseek-chat": {"in": 0.15, "hit": 0.003, "out": 0.60},
    "deepseek-flash": {"in": 0.15, "hit": 0.003, "out": 0.60},
    "deepseek-v4-pro": {"in": 0.66, "hit": 0.022, "out": 1.98},
}
_DEFAULT_PRICE = {"in": 0.15, "hit": 0.003, "out": 0.60}
# 峰值时段为两倍价：UTC 01:00-04:00 与 06:00-10:00（周一至周五）
_PEAK_HOURS = ((1, 4), (6, 10))
USD_TO_CNY = 7.1


class LLMError(RuntimeError):
    """调用大模型失败。"""


@dataclass
class LLMConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: int = 120
    retries: int = 2
    temperature: float = 0.1


def config_from_env() -> LLMConfig | None:
    """从环境变量读取配置；没有可用 Key 时返回 None。"""
    api_key = ""
    for name in _KEY_ENVS:
        value = os.environ.get(name, "").strip()
        if value and not value.startswith("请在"):
            api_key = value
            break
    if not api_key:
        return None
    return LLMConfig(
        api_key=api_key,
        base_url=os.environ.get("HARVEST_LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        model=os.environ.get("HARVEST_LLM_MODEL", DEFAULT_MODEL),
        timeout=int(os.environ.get("HARVEST_LLM_TIMEOUT", "120")),
        retries=int(os.environ.get("HARVEST_LLM_RETRIES", "2")),
        temperature=float(os.environ.get("HARVEST_LLM_TEMPERATURE", "0.1")),
    )


# --------------------------------------------------------------------------
# 计价
# --------------------------------------------------------------------------


def is_peak(moment: datetime | None = None) -> bool:
    """是否处于官方定义的峰值计价时段。"""
    moment = moment or datetime.now(timezone.utc)
    if moment.weekday() >= 5:
        return False
    return any(start <= moment.hour < end for start, end in _PEAK_HOURS)


def price_for(model: str, peak: bool | None = None) -> dict[str, float]:
    """返回某模型的单价（USD / 1M tokens）。"""
    table = PRICE_TABLE.get(model)
    if table is None:
        lowered = model.lower()
        table = next((v for k, v in PRICE_TABLE.items() if k in lowered), _DEFAULT_PRICE)
    if peak is None:
        peak = is_peak()
    factor = 2.0 if peak else 1.0
    return {key: value * factor for key, value in table.items()} | {"_peak": peak}


def estimate_tokens(text: str) -> int:
    """按官方口径估算 token 数：1 汉字 ≈ 0.6 token，英文 ≈ 0.3 token/字符。

    不做分词，只按字符类型粗分，足以在无 Key 时给出量级正确的账单。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return max(1, round(cjk * 0.6 + other * 0.3))


# --------------------------------------------------------------------------
# 记账
# --------------------------------------------------------------------------


@dataclass
class StageUsage:
    stage: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    charged: bool
    source: str  # api / cache / estimated

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class CostTracker:
    """按阶段累计 token 与费用。

    `source=estimated` 表示无 Key、按提示词字符数折算的预估值；
    `source=cache` 表示命中本地缓存，不重复计费。
    """

    model: str = DEFAULT_MODEL
    peak: bool | None = None
    records: list[StageUsage] = field(default_factory=list)

    def record(
        self,
        stage: str,
        prompt: str,
        output: str,
        usage: dict[str, Any] | None = None,
        source: str = "estimated",
    ) -> StageUsage:
        if usage:
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            cached_tokens = int(usage.get("prompt_cache_hit_tokens") or 0)
        else:
            prompt_tokens = estimate_tokens(prompt)
            completion_tokens = estimate_tokens(output)
            cached_tokens = 0
        item = StageUsage(
            stage=stage,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            charged=source in {"api", "estimated"},
            source=source,
        )
        self.records.append(item)
        return item

    # -- 汇总 ---------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        price = price_for(self.model, self.peak)
        prompt = sum(r.prompt_tokens for r in self.records)
        completion = sum(r.completion_tokens for r in self.records)
        cached = sum(r.cached_tokens for r in self.records)
        missed = prompt - cached

        del missed  # 计费按「是否实际扣费」逐条累加，缓存命中的那部分不再重复计费
        model_cost = sum(
            (r.prompt_tokens - r.cached_tokens) * price["in"]
            + r.cached_tokens * price["hit"]
            + r.completion_tokens * price["out"]
            for r in self.records
            if r.charged
        ) / 1_000_000
        stages: dict[str, dict[str, Any]] = {}
        for r in self.records:
            bucket = stages.setdefault(
                r.stage,
                {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0},
            )
            bucket["calls"] += 1
            bucket["prompt_tokens"] += r.prompt_tokens
            bucket["completion_tokens"] += r.completion_tokens
            if r.charged:
                bucket["cost_usd"] += (
                    (r.prompt_tokens - r.cached_tokens) * price["in"]
                    + r.cached_tokens * price["hit"]
                    + r.completion_tokens * price["out"]
                ) / 1_000_000

        return {
            "model": self.model,
            "peak": bool(price["_peak"]),
            "unit_price_usd_per_mtok": {
                "input": price["in"],
                "input_cached": price["hit"],
                "output": price["out"],
            },
            "calls": len(self.records),
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "cached_tokens": cached,
            "cost_usd": round(model_cost, 6),
            "cost_cny": round(model_cost * USD_TO_CNY, 4),
            "stages": {
                k: {**v, "cost_usd": round(v["cost_usd"], 6)}
                for k, v in stages.items()
            },
            "has_estimate": any(r.source == "estimated" for r in self.records),
            "has_measured": any(r.source == "api" for r in self.records),
        }


# --------------------------------------------------------------------------
# 调用
# --------------------------------------------------------------------------


def prompt_fingerprint(system: str, user: str, model: str) -> str:
    digest = hashlib.sha1()
    for part in (model, system, user):
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _post_json(url: str, payload: dict, api_key: str, timeout: int) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def chat_json(
    system: str,
    user: str,
    cfg: LLMConfig,
    cache_path: Path | None = None,
    refresh: bool = False,
) -> tuple[dict, dict[str, Any]]:
    """调用对话模型并解析 JSON，返回 (对象, 元信息)。

    结果按「模型 + 提示词」指纹缓存，重复运行不重复付费；`refresh=True` 强制重调。
    """
    fingerprint = prompt_fingerprint(system, user, cfg.model)
    if cache_path and cache_path.exists() and not refresh:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fingerprint:
                return cached["data"], {
                    "source": "cache",
                    "model": cfg.model,
                    "usage": cached.get("usage", {}),
                }
        except (json.JSONDecodeError, KeyError):
            pass  # 缓存损坏时静默重算

    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": cfg.temperature,
        "response_format": {"type": "json_object"},
    }

    last_error: Exception | None = None
    for attempt in range(cfg.retries + 1):
        try:
            raw = _post_json(f"{cfg.base_url}/chat/completions", payload, cfg.api_key, cfg.timeout)
            content = raw["choices"][0]["message"]["content"]
            data = json.loads(_strip_code_fence(content))
            usage = raw.get("usage", {})
            if cache_path:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps(
                        {"fingerprint": fingerprint, "model": cfg.model, "usage": usage, "data": data},
                        ensure_ascii=False,
                        indent=1,
                    ),
                    encoding="utf-8",
                )
            return data, {"source": "api", "model": cfg.model, "usage": usage}
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError,
                json.JSONDecodeError, TimeoutError) as exc:
            last_error = exc
            if attempt >= cfg.retries:
                break
            time.sleep(1.5 * (attempt + 1))

    raise LLMError(f"大模型调用失败：{last_error}")


def render_cost_report(summary: dict[str, Any], extra: dict[str, Any] | None = None) -> str:
    """把账单汇总渲染成 Markdown 片段。"""
    peak = "峰值" if summary["peak"] else "错峰"
    lines = [
        f"模型 `{summary['model']}`（{peak}价），共 {summary['calls']} 次调用。",
        "",
        "| 阶段 | 调用 | 输入 token | 输出 token | 费用 USD |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, item in summary["stages"].items():
        lines.append(
            f"| {name} | {item['calls']} | {item['prompt_tokens']:,} | "
            f"{item['completion_tokens']:,} | ${item['cost_usd']:.4f} |"
        )
    lines.append(
        f"| **合计** | **{summary['calls']}** | **{summary['prompt_tokens']:,}** | "
        f"**{summary['completion_tokens']:,}** | **${summary['cost_usd']:.4f}** |"
    )
    lines.append("")
    lines.append(
        f"token 合计 **{summary['total_tokens']:,}**，模型费 **${summary['cost_usd']:.4f} "
        f"≈ ¥{summary['cost_cny']:.2f}**。"
    )
    if extra:
        lines.append("")
        for key, value in extra.items():
            lines.append(f"- {key}：{value}")
    if summary["has_estimate"] and not summary["has_measured"]:
        lines.append("")
        lines.append("> 本次未配置 API Key，token 数按提示词字符数折算，属**预估**；配置 Key 后为实测值。")
    return "\n".join(lines)
