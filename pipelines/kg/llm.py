# -*- coding: utf-8 -*-
"""极简大模型 JSON 抽取客户端（OpenAI / DeepSeek 兼容协议）。

只依赖标准库，便于在没有安装 requests 的环境里直接运行。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
_KEY_ENVS = ("KG_LLM_API_KEY", "DEEPSEEK_API_KEY")


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
        base_url=os.environ.get("KG_LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        model=os.environ.get("KG_LLM_MODEL", DEFAULT_MODEL),
        timeout=int(os.environ.get("KG_LLM_TIMEOUT", "120")),
        retries=int(os.environ.get("KG_LLM_RETRIES", "2")),
        temperature=float(os.environ.get("KG_LLM_TEMPERATURE", "0.1")),
    )


def prompt_fingerprint(system: str, user: str, model: str) -> str:
    digest = hashlib.sha1()
    digest.update(model.encode("utf-8"))
    digest.update(b"\0")
    digest.update(system.encode("utf-8"))
    digest.update(b"\0")
    digest.update(user.encode("utf-8"))
    return digest.hexdigest()[:16]


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _post_json(url: str, payload: dict, api_key: str, timeout: int) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def chat_json(
    system: str,
    user: str,
    cfg: LLMConfig,
    cache_path: Path | None = None,
    refresh: bool = False,
) -> tuple[dict, dict]:
    """调用对话模型并解析 JSON，返回 (对象, 元信息)。

    结果按提示词指纹缓存，重复运行不会重复付费；refresh=True 强制重调。
    """
    fingerprint = prompt_fingerprint(system, user, cfg.model)
    if cache_path and cache_path.exists() and not refresh:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("fingerprint") == fingerprint:
                return cached["data"], {"source": "cache", "model": cfg.model, "usage": cached.get("usage", {})}
        except (json.JSONDecodeError, KeyError):
            pass  # 缓存损坏时静默重算

    url = f"{cfg.base_url}/chat/completions"
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
            raw = _post_json(url, payload, cfg.api_key, cfg.timeout)
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
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError, json.JSONDecodeError, TimeoutError) as exc:
            last_error = exc
            if attempt >= cfg.retries:
                break
            time.sleep(1.5 * (attempt + 1))

    raise LLMError(f"大模型调用失败：{last_error}")
