"""
LLM Router — multi-provider LLM call with automatic fallback chain.

Chain: OpenAI → Anthropic → Gemini → local Ollama → deterministic heuristics.

Every call is logged to logs/llm.jsonl with provider, model, tokens, latency, success.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    latency_s: float
    tokens_in: int = 0
    tokens_out: int = 0
    success: bool = True
    error: str | None = None


class LLMRouter:
    """Routes LLM calls through a priority chain with automatic fallback."""

    PROVIDER_CHAIN = ["openai", "anthropic", "gemini", "ollama", "heuristics"]

    def __init__(self, config: dict, log_path: str = "logs/llm.jsonl"):
        self.config = config
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        role: str = "default",
        prefer_provider: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Send a chat completion request with automatic fallback."""
        # Determine provider priority
        per_role = self.config.get("llm", {}).get("per_role", {})
        role_provider = per_role.get(role, self.config.get("llm", {}).get("default_provider", "openai"))

        # Build the chain: preferred first, then the rest in order
        chain = []
        if prefer_provider:
            chain.append(prefer_provider)
        if role_provider and role_provider not in chain:
            chain.append(role_provider)
        for p in self.PROVIDER_CHAIN:
            if p not in chain:
                chain.append(p)

        last_error: str | None = None
        for provider in chain:
            try:
                resp = self._call_provider(
                    provider, system_prompt, user_prompt, max_tokens, temperature
                )
                if resp.success:
                    self._log(resp, role)
                    return resp
                last_error = resp.error
            except Exception as e:  # noqa: BLE001
                last_error = f"{provider}: {e}"
                continue

        # All providers failed — return heuristic response
        resp = LLMResponse(
            text=self._heuristic_response(system_prompt, user_prompt),
            provider="heuristics",
            model="deterministic-fallback",
            latency_s=0.0,
            success=True,
            error=f"all providers failed; last_error={last_error}",
        )
        self._log(resp, role)
        return resp

    def _call_provider(
        self, provider: str, system: str, user: str, max_tokens: int, temperature: float
    ) -> LLMResponse:
        t0 = time.time()
        if provider == "openai":
            return self._call_openai(system, user, max_tokens, temperature, t0)
        if provider == "anthropic":
            return self._call_anthropic(system, user, max_tokens, temperature, t0)
        if provider == "gemini":
            return self._call_gemini(system, user, max_tokens, temperature, t0)
        if provider == "ollama":
            return self._call_ollama(system, user, max_tokens, temperature, t0)
        if provider == "heuristics":
            return LLMResponse(
                text=self._heuristic_response(system, user),
                provider="heuristics",
                model="deterministic-fallback",
                latency_s=time.time() - t0,
                success=True,
            )
        return LLMResponse(
            text="", provider=provider, model="", latency_s=0.0, success=False, error="unknown provider"
        )

    def _call_openai(self, system: str, user: str, max_tokens: int, temperature: float, t0: float) -> LLMResponse:
        api_key = os.environ.get("OPENAI_API_KEY") or self.config.get("llm", {}).get("openai_api_key")
        if not api_key:
            return LLMResponse("", "openai", "", 0, success=False, error="no api key")
        try:
            from openai import OpenAI  # type: ignore

            client = OpenAI(api_key=api_key)
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            text = resp.choices[0].message.content or ""
            return LLMResponse(
                text=text,
                provider="openai",
                model="gpt-4o-mini",
                latency_s=time.time() - t0,
                tokens_in=resp.usage.prompt_tokens if resp.usage else 0,
                tokens_out=resp.usage.completion_tokens if resp.usage else 0,
                success=True,
            )
        except Exception as e:  # noqa: BLE001
            return LLMResponse("", "openai", "", time.time() - t0, success=False, error=str(e))

    def _call_anthropic(self, system: str, user: str, max_tokens: int, temperature: float, t0: float) -> LLMResponse:
        api_key = os.environ.get("ANTHROPIC_API_KEY") or self.config.get("llm", {}).get("anthropic_api_key")
        if not api_key:
            return LLMResponse("", "anthropic", "", 0, success=False, error="no api key")
        try:
            import anthropic  # type: ignore

            client = anthropic.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model="claude-3-5-sonnet-latest",
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            text = resp.content[0].text if resp.content else ""
            return LLMResponse(
                text=text,
                provider="anthropic",
                model="claude-3-5-sonnet-latest",
                latency_s=time.time() - t0,
                tokens_in=resp.usage.input_tokens,
                tokens_out=resp.usage.output_tokens,
                success=True,
            )
        except Exception as e:  # noqa: BLE001
            return LLMResponse("", "anthropic", "", time.time() - t0, success=False, error=str(e))

    def _call_gemini(self, system: str, user: str, max_tokens: int, temperature: float, t0: float) -> LLMResponse:
        api_key = os.environ.get("GEMINI_API_KEY") or self.config.get("llm", {}).get("gemini_api_key")
        if not api_key:
            return LLMResponse("", "gemini", "", 0, success=False, error="no api key")
        try:
            import google.generativeai as genai  # type: ignore

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-flash", system_instruction=system)
            resp = model.generate_content(user, generation_config={"max_output_tokens": max_tokens, "temperature": temperature})
            return LLMResponse(
                text=resp.text or "",
                provider="gemini",
                model="gemini-1.5-flash",
                latency_s=time.time() - t0,
                success=True,
            )
        except Exception as e:  # noqa: BLE001
            return LLMResponse("", "gemini", "", time.time() - t0, success=False, error=str(e))

    def _call_ollama(self, system: str, user: str, max_tokens: int, temperature: float, t0: float) -> LLMResponse:
        host = self.config.get("llm", {}).get("ollama_host", "http://localhost:11434")
        model = self.config.get("llm", {}).get("ollama_model", "llama3.1:8b")
        try:
            import httpx

            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    f"{host}/api/chat",
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "stream": False,
                        "options": {"temperature": temperature, "num_predict": max_tokens},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return LLMResponse(
                    text=data.get("message", {}).get("content", ""),
                    provider="ollama",
                    model=model,
                    latency_s=time.time() - t0,
                    success=True,
                )
        except Exception as e:  # noqa: BLE001
            return LLMResponse("", "ollama", "", time.time() - t0, success=False, error=str(e))

    def _heuristic_response(self, system: str, user: str) -> str:
        """Deterministic last-resort response. Used when all LLM providers fail."""
        return f"[HEURISTIC FALLBACK] Unable to reach any LLM provider. Echoing user prompt for downstream handling:\n\n{user}"

    def _log(self, resp: LLMResponse, role: str) -> None:
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "role": role,
            "provider": resp.provider,
            "model": resp.model,
            "latency_s": round(resp.latency_s, 3),
            "tokens_in": resp.tokens_in,
            "tokens_out": resp.tokens_out,
            "success": resp.success,
            "error": resp.error,
        }
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
