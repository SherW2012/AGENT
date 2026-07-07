from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderProfile:
    id: str
    label: str
    transport: str
    key_env: str
    base_url: str | None
    default_model: str
    models: tuple[str, ...]
    key_url: str
    docs_url: str
    key_hint: str
    # Vision capability, a config fact like base_url (not intent guessing):
    #   "native" - the configured chat model already accepts images
    #   "switch" - same API key, but image turns must route to vision_model
    #   "none"   - the provider's chat API is text-only
    vision: str = "none"
    vision_model: str | None = None
    # Provider-side web search: the name of the builtin tool the model itself
    # executes (Kimi/Moonshot's "$web_search"). None means the provider has no
    # builtin search and the local scraping web_search tool is used instead.
    builtin_search_tool: str | None = None
    # Documented provider limitation (platform.moonshot.ai/docs/guide/use-web-search):
    # the builtin search tool is temporarily incompatible with the model's
    # thinking mode, so requests that offer it must send
    # {"thinking": {"type": "disabled"}} or the tool is silently unusable.
    builtin_search_conflicts_with_thinking: bool = False

    def resolve_vision_model(self) -> str | None:
        """Vision model for image turns; env var overrides the profile default
        so new provider models don't require a code change."""
        override = os.getenv(f"{self.id.upper()}_VISION_MODEL") or os.getenv(
            f"BNCT_AGENT_{self.id.upper()}_VISION_MODEL"
        )
        return (override or self.vision_model or "").strip() or None

    def public_config(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "baseUrl": self.base_url or "",
            "defaultModel": self.default_model,
            "models": list(self.models),
            "keyUrl": self.key_url,
            "docsUrl": self.docs_url,
            "keyEnv": self.key_env,
            "keyHint": self.key_hint,
            "vision": self.vision,
            "visionModel": self.resolve_vision_model() or "",
            "builtinSearch": bool(self.builtin_search_tool),
        }


PROVIDERS: dict[str, ProviderProfile] = {
    "openai": ProviderProfile(
        id="openai",
        label="OpenAI / GPT",
        transport="responses",
        key_env="OPENAI_API_KEY",
        base_url=None,
        default_model="gpt-5.4-mini",
        models=("gpt-5.4-mini",),
        key_url="https://platform.openai.com/api-keys",
        docs_url="https://developers.openai.com/api/docs/quickstart",
        key_hint="sk-...",
        vision="native",
    ),
    "deepseek": ProviderProfile(
        id="deepseek",
        label="DeepSeek",
        transport="chat_completions",
        key_env="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com",
        default_model="deepseek-v4-pro",
        models=("deepseek-v4-pro", "deepseek-v4-flash"),
        key_url="https://platform.deepseek.com/api_keys",
        docs_url="https://api-docs.deepseek.com/",
        key_hint="DeepSeek API Key",
    ),
    "kimi": ProviderProfile(
        id="kimi",
        label="Kimi / Moonshot",
        transport="chat_completions",
        key_env="MOONSHOT_API_KEY",
        base_url="https://api.moonshot.cn/v1",
        default_model="kimi-k2.6",
        models=("kimi-k2.6", "kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k2.5"),
        key_url="https://platform.kimi.com/console/account",
        docs_url="https://platform.kimi.com/docs/api/quickstart",
        key_hint="Kimi API Key",
        vision="switch",
        vision_model="moonshot-v1-32k-vision-preview",
        builtin_search_tool="$web_search",
        builtin_search_conflicts_with_thinking=True,
    ),
}


def get_provider(provider: str | None) -> ProviderProfile:
    provider_id = (provider or "openai").strip().lower()
    try:
        return PROVIDERS[provider_id]
    except KeyError as exc:
        choices = ", ".join(PROVIDERS)
        raise ValueError(f"不支持的模型供应商: {provider_id}；可选值: {choices}") from exc


def public_provider_configs() -> list[dict[str, object]]:
    return [profile.public_config() for profile in PROVIDERS.values()]
