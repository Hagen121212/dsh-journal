from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import Config
from .util import parse_llm_json, truncate


class BudgetExceeded(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


def resolve_api_key(cfg: Config) -> str:
    key = os.environ.get(cfg.api_key_env, "").strip()
    if key:
        return key
    cred = cfg.dsh_home / ".credentials.yaml"
    if cred.exists():
        text = cred.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"DEEPSEEK_API_KEY\s*:\s*(\S+)", text)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    key_file = cfg.home / "api_key.txt"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    raise LLMError(
        f"未找到 API key。请设置环境变量 {cfg.api_key_env}，或放到 {key_file}。"
    )


class LLM:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.api_key = resolve_api_key(cfg)
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.reasoning_tokens = 0
        self.total_tokens = 0
        self.cache_hit_tokens = 0
        self.usage_log: list[dict[str, Any]] = []

    def _budget_check(self) -> None:
        if self.calls >= self.cfg.max_calls_per_run:
            raise BudgetExceeded(f"达到本次运行调用上限 {self.cfg.max_calls_per_run}")
        if self.total_tokens >= self.cfg.max_total_tokens_per_run:
            raise BudgetExceeded(f"达到本次运行 token 上限 {self.cfg.max_total_tokens_per_run}")

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        label: str = "",
        max_tokens: int | None = None,
        effort: str | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        self._budget_check()
        body = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens or self.cfg.max_output_tokens,
            "temperature": self.cfg.temperature if temperature is None else temperature,
            "reasoning_effort": effort or self.cfg.reasoning_effort,
            "stream": False,
        }
        data = self._post_with_retries(body, label=label)
        choice = (data.get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        finish = choice.get("finish_reason")
        if not content and finish == "length" and body["max_tokens"] < 32000:
            body["max_tokens"] = min(32000, body["max_tokens"] * 2)
            data = self._post_with_retries(body, label=label + ":longer")
            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
            finish = choice.get("finish_reason")
        if not content:
            raise LLMError(f"模型返回空内容（{label}，finish={finish}）")
        obj = parse_llm_json(content)
        if not obj:
            # One repair attempt with the raw response.
            repair = {
                "model": self.cfg.model,
                "messages": [
                    {"role": "system", "content": "You repair malformed JSON. Return only one valid JSON object."},
                    {"role": "user", "content": truncate(content, 12000)},
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": max_tokens or self.cfg.max_output_tokens,
                "temperature": 0,
                "reasoning_effort": "low",
                "stream": False,
            }
            data2 = self._post_with_retries(repair, label=label + ":repair")
            obj = parse_llm_json(data2["choices"][0]["message"].get("content") or "")
        if not obj:
            raise LLMError(f"模型没有返回有效 JSON（{label}）")
        return obj

    def _post_with_retries(self, body: dict[str, Any], *, label: str = "", attempts: int = 4) -> dict[str, Any]:
        url = self.cfg.base_url + "/chat/completions"
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "deepseek-journal/1.0",
        }
        last_err: Exception | None = None
        for attempt in range(1, attempts + 1):
            self._budget_check()
            req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.cfg.timeout_seconds, context=ssl.create_default_context()) as r:
                    data = json.loads(r.read().decode("utf-8"))
                self.calls += 1
                usage = data.get("usage") or {}
                self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
                self.completion_tokens += int(usage.get("completion_tokens") or 0)
                self.total_tokens += int(usage.get("total_tokens") or 0)
                details = usage.get("completion_tokens_details") or {}
                self.reasoning_tokens += int(details.get("reasoning_tokens") or 0)
                self.cache_hit_tokens += int(usage.get("prompt_cache_hit_tokens") or 0)
                self.usage_log.append({
                    "label": label,
                    "model": data.get("model"),
                    "finish_reason": ((data.get("choices") or [{}])[0]).get("finish_reason"),
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "reasoning_tokens": details.get("reasoning_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                    "cache_hit_tokens": usage.get("prompt_cache_hit_tokens"),
                })
                return data
            except urllib.error.HTTPError as e:
                body_text = ""
                try:
                    body_text = e.read().decode("utf-8", "replace")
                except Exception:
                    pass
                last_err = LLMError(f"HTTP {e.code}: {truncate(body_text, 500)}")
                if e.code in (400, 401, 402, 403, 404):
                    break
            except Exception as e:
                last_err = e
            if attempt < attempts:
                time.sleep(min(2 ** attempt, 12))
        raise LLMError(f"API 调用失败（{label}）：{last_err}")

    def usage_summary(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "cache_hit_tokens": self.cache_hit_tokens,
            "usage": self.usage_log,
        }
