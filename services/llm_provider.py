"""Provider-agnostic LLM transport for language-only application tasks."""

from __future__ import annotations

import json
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Type, TypeVar

import requests
from pydantic import BaseModel, ValidationError


class ConfigurationError(RuntimeError):
    """Raised when a provider cannot be used safely due to missing configuration."""


class ProviderUnavailableError(RuntimeError):
    """Raised for retryable provider failures such as 429 and 5xx responses."""


class ProviderTimeoutError(TimeoutError):
    """Raised when a provider exceeds the request timeout."""


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


def sanitize_prompt_text(value: str) -> str:
    """Remove common instruction-injection tails before model transport."""
    cleaned = re.sub(r"[\x00-\x1f\x7f]", " ", str(value or ""))
    cleaned = re.sub(
        r"\b(ignore|disregard)\s+(all\s+)?previous\s+instructions?\b.*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def _with_structured_contract(request: "LLMRequest", schema: Type[StructuredModel]) -> "LLMRequest":
    schema_json = json.dumps(schema.model_json_schema(), sort_keys=True)
    return LLMRequest(
        task=request.task,
        system_prompt=(
            f"{request.system_prompt}\n\n"
            "Output contract: return exactly one valid JSON object. Do not use Markdown, "
            "comments, prose, or additional keys. Validate against this JSON Schema:\n"
            f"{schema_json}"
        ),
        user_prompt=request.user_prompt,
        model=request.model,
        temperature=request.temperature,
        timeout_seconds=request.timeout_seconds,
        top_p=request.top_p,
        max_tokens=request.max_tokens,
        response_format="json",
    )


@dataclass(frozen=True)
class LLMRequest:
    task: str
    system_prompt: str
    user_prompt: str
    model: str | None = None
    temperature: float = 0.0
    timeout_seconds: float = 5.0
    top_p: float = 1.0
    max_tokens: int = 2048
    response_format: str = "json"


@dataclass(frozen=True)
class LLMResponse:
    provider: str
    model: str
    text: str
    raw: Dict[str, Any]


class LLMProvider(ABC):
    name: str

    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        """Generate language output without changing application state."""

    def generate(self, request: LLMRequest) -> LLMResponse:
        return self.complete(request)

    def extract_structured(self, request: LLMRequest, schema: Type[StructuredModel]) -> StructuredModel:
        response = self.complete(_with_structured_contract(request, schema))
        raw_text = response.text.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_text, flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            raw_text = fenced.group(1)
        try:
            return schema.model_validate(json.loads(raw_text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError(f"Provider returned invalid structured output: {exc}") from exc


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")

    def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        payload = {
            "model": model,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "max_tokens": request.max_tokens,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_prompt},
            ],
        }
        if request.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        data = _post_json(f"{self.base_url}/chat/completions", {"Authorization": f"Bearer {self._key()}"}, payload, request.timeout_seconds)
        return LLMResponse(self.name, model, data["choices"][0]["message"]["content"], data)

    def _key(self) -> str:
        return _require_key(self.api_key, "OPENAI_API_KEY")


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.base_url = (base_url or os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")).rstrip("/")

    def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
        payload = {
            "model": model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": request.user_prompt}],
        }
        headers = {
            "x-api-key": _require_key(self.api_key, "ANTHROPIC_API_KEY"),
            "anthropic-version": "2023-06-01",
        }
        data = _post_json(f"{self.base_url}/messages", headers, payload, request.timeout_seconds)
        return LLMResponse(self.name, model, data["content"][0]["text"], data)


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.base_url = (base_url or os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")).rstrip("/")

    def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        payload = {
            "system_instruction": {"parts": [{"text": request.system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": request.user_prompt}]}],
            "generationConfig": {
                "temperature": request.temperature,
                "topP": request.top_p,
                "maxOutputTokens": request.max_tokens,
                "responseMimeType": "application/json" if request.response_format == "json" else "text/plain",
            },
        }
        data = _post_json(
            f"{self.base_url}/models/{model}:generateContent?key={_require_key(self.api_key, 'GEMINI_API_KEY')}",
            {},
            payload,
            request.timeout_seconds,
        )
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return LLMResponse(self.name, model, text, data)


class LLMRouter:
    """Routes language tasks while leaving financial and workflow decisions deterministic."""

    def __init__(self, providers: Mapping[str, LLMProvider] | None = None):
        self.providers = dict(providers or {
            "openai": OpenAIProvider(),
            "anthropic": AnthropicProvider(),
            "gemini": GeminiProvider(),
        })
        self.task_providers = self._load_task_providers()
        self.fallback_providers = self._load_fallback_providers()

    def complete(self, request: LLMRequest) -> LLMResponse:
        request = LLMRequest(
            task=request.task,
            system_prompt=request.system_prompt,
            user_prompt=sanitize_prompt_text(request.user_prompt),
            model=request.model,
            temperature=request.temperature,
            timeout_seconds=request.timeout_seconds,
            top_p=request.top_p,
            max_tokens=request.max_tokens,
            response_format=request.response_format,
        )
        provider_names = [
            self.task_providers.get(request.task, os.getenv("LLM_DEFAULT_PROVIDER", "openai")),
            *self.fallback_providers.get(request.task, []),
        ]
        errors = []
        retryable_failure = False
        retry_attempts = max(1, int(os.getenv("LLM_RETRY_ATTEMPTS", "3")))
        for provider_name in dict.fromkeys(provider_names):
            provider = self.providers.get(provider_name)
            if provider is None:
                errors.append(ValueError(f"Unknown LLM provider '{provider_name}' for task '{request.task}'."))
                continue
            for attempt in range(retry_attempts):
                try:
                    return provider.complete(request)
                except (ProviderUnavailableError, ProviderTimeoutError, requests.RequestException) as exc:
                    errors.append(exc)
                    retryable_failure = True
                    if attempt + 1 < retry_attempts:
                        time.sleep(2 ** attempt)
                    else:
                        break
        if errors:
            if not retryable_failure:
                raise errors[-1]
            raise ProviderUnavailableError(f"All configured LLM providers failed for task '{request.task}'.") from errors[-1]
        raise ValueError(f"No LLM provider configured for task '{request.task}'.")

    def set_task_provider(self, task: str, provider_name: str) -> None:
        if provider_name not in self.providers:
            raise ValueError(f"Unknown LLM provider '{provider_name}'.")
        self.task_providers[task] = provider_name

    def extract_structured(self, request: LLMRequest, schema: Type[StructuredModel], max_attempts: int = 2) -> StructuredModel:
        last_error: Exception | None = None
        current_request = _with_structured_contract(request, schema)
        for attempt in range(max_attempts):
            response = self.complete(current_request)
            try:
                raw_text = response.text.strip()
                fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", raw_text, flags=re.IGNORECASE | re.DOTALL)
                if fenced:
                    raw_text = fenced.group(1)
                return schema.model_validate(json.loads(raw_text))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                current_request = LLMRequest(
                    task=request.task,
                    system_prompt=current_request.system_prompt,
                    user_prompt=(
                        f"{request.user_prompt}\n\nPrevious output failed schema validation: {exc}. "
                        "Return only corrected JSON matching the requested schema."
                    ),
                    model=request.model,
                    temperature=request.temperature,
                    timeout_seconds=request.timeout_seconds,
                    top_p=request.top_p,
                    max_tokens=request.max_tokens,
                    response_format=request.response_format,
                )
        raise ValueError(f"Structured extraction failed after {max_attempts} attempts: {last_error}") from last_error

    @staticmethod
    def _load_task_providers() -> Dict[str, str]:
        configured = os.getenv("LLM_TASK_PROVIDERS", "")
        if not configured.strip():
            return {}
        try:
            mapping = json.loads(configured)
        except json.JSONDecodeError as exc:
            raise ValueError("LLM_TASK_PROVIDERS must be valid JSON.") from exc
        if not isinstance(mapping, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in mapping.items()):
            raise ValueError("LLM_TASK_PROVIDERS must be a JSON object of task names to provider names.")
        return mapping

    @staticmethod
    def _load_fallback_providers() -> Dict[str, list[str]]:
        configured = os.getenv("LLM_FALLBACK_PROVIDERS", "")
        if not configured.strip():
            return {}
        mapping = json.loads(configured)
        if not isinstance(mapping, dict):
            raise ValueError("LLM_FALLBACK_PROVIDERS must be a JSON object.")
        return {str(task): [str(provider) for provider in providers] for task, providers in mapping.items()}


def _require_key(value: str | None, environment_name: str) -> str:
    if not value:
        raise ConfigurationError(f"Missing required secret {environment_name}; configure it in the process environment.")
    return value


def _post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout_seconds: float = 5.0) -> Dict[str, Any]:
    try:
        response = requests.post(url, headers={**headers, "Content-Type": "application/json"}, json=payload, timeout=timeout_seconds)
    except requests.Timeout as exc:
        raise ProviderTimeoutError("LLM provider request timed out.") from exc
    if response.status_code == 429 or response.status_code >= 500:
        raise ProviderUnavailableError(f"LLM provider returned retryable status {response.status_code}.")
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("LLM provider returned a non-object response.")
    return data
