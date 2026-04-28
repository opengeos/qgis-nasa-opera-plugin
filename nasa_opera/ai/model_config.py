"""GeoAgent model/provider settings for the NASA OPERA AI assistant."""

from __future__ import annotations

import os

SETTINGS_PREFIX = "NasaOpera/"

DEFAULT_MODELS = {
    "bedrock": "us.anthropic.claude-sonnet-4-6",
    "openai": "gpt-5.5",
    "anthropic": "claude-sonnet-4-6",
    "gemini": "gemini-3.1-pro-preview",
    "ollama": "qwen3.5:4b",
}

AVAILABLE_MODELS = {
    "bedrock": [
        "us.anthropic.claude-sonnet-4-6",
        "us.anthropic.claude-opus-4-7",
        "us.anthropic.claude-haiku-4-5",
    ],
    "openai": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"],
    "anthropic": [
        "claude-sonnet-4-6",
        "claude-opus-4-7",
        "claude-haiku-4-6",
    ],
    "gemini": [
        "gemini-3.1-pro-preview",
        "gemini-3-flash-preview",
        "gemini-3.1-flash-lite-preview",
    ],
    "ollama": [
        "qwen3.5:latest",
        "qwen3.5:0.8b",
        "qwen3.5:2b",
        "qwen3.5:4b",
        "qwen3.5:9b",
        "qwen3.5:27b",
        "llama3.1",
        "gemma4:e4b",
        "gemma4:e2b",
    ],
}

PROVIDERS = ["bedrock", "openai", "anthropic", "gemini", "ollama"]

_DISPLAY_TO_PROVIDER = {
    "Amazon Bedrock": "bedrock",
    "OpenAI": "openai",
    "Anthropic": "anthropic",
    "Google Gemini": "gemini",
    "Ollama": "ollama",
}


def normalize_provider(provider: str) -> str:
    """Return a GeoAgent provider id from old display labels or provider ids."""
    value = (provider or "openai").strip()
    return _DISPLAY_TO_PROVIDER.get(value, value.lower())


def setting(settings, key: str, default="", value_type=str):
    """Read a plugin setting value."""
    return settings.value(f"{SETTINGS_PREFIX}{key}", default, type=value_type)


def provider_from_settings(settings) -> str:
    """Read the selected provider from QSettings."""
    return normalize_provider(setting(settings, "ai_provider", "openai"))


def model_from_settings(settings, provider: str | None = None) -> str:
    """Read the selected model, falling back to the provider default."""
    provider = provider or provider_from_settings(settings)
    model = setting(settings, "ai_model", "")
    return model or DEFAULT_MODELS.get(provider, "")


def apply_environment_from_settings(settings) -> None:
    """Apply provider credentials from QSettings to the current QGIS process."""
    provider = provider_from_settings(settings)
    legacy_key = setting(settings, "ai_api_key", "").strip()
    legacy_base_url = setting(settings, "ai_base_url", "").strip()

    env_map = {
        "ai_openai_api_key": ("OPENAI_API_KEY",),
        "ai_anthropic_api_key": ("ANTHROPIC_API_KEY",),
        "ai_gemini_api_key": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "ai_aws_region": ("AWS_REGION",),
        "ai_ollama_host": ("OLLAMA_HOST",),
    }
    for key, env_names in env_map.items():
        value = setting(settings, key, "").strip()
        if value:
            for env_name in env_names:
                os.environ[env_name] = value

    if legacy_key:
        fallback_env = {
            "openai": ("OPENAI_API_KEY",),
            "anthropic": ("ANTHROPIC_API_KEY",),
            "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        }.get(provider, ())
        for env_name in fallback_env:
            os.environ.setdefault(env_name, legacy_key)

    if legacy_base_url:
        os.environ.setdefault("OLLAMA_HOST", legacy_base_url)
