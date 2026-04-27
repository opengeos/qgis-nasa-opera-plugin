"""
LLM Client for NASA OPERA Plugin.

Wraps litellm to provide a unified interface for multiple LLM providers
including OpenAI, Anthropic, Amazon Bedrock, Google Gemini, and Ollama.
"""

import os
from typing import Dict, Generator, List, Optional, Tuple, Union

# Default models per provider
DEFAULT_MODELS = {
    "openai": "gpt-4.1",
    "anthropic": "claude-sonnet-4-6",
    "bedrock": "anthropic.claude-sonnet-4-20250514-v1:0",
    "gemini": "gemini-3.1-flash-lite-preview",
    "ollama": "llama3.1",
}

# Available models per provider
AVAILABLE_MODELS = {
    "openai": [
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
    ],
    "anthropic": [
        "claude-sonnet-4-6",
        "claude-opus-4-7",
        "claude-haiku-4-5-20251001",
    ],
    "bedrock": [
        "anthropic.claude-sonnet-4-20250514-v1:0",
        "anthropic.claude-opus-4-20250514-v1:0",
        "anthropic.claude-haiku-4-5-20251001-v1:0",
    ],
    "gemini": [
        "gemini-3.1-flash-lite-preview",
        "gemini-3.1-pro-preview",
        "gemini-3-flash-preview",
    ],
    "ollama": [
        "llama3.1",
        "qwen3",
        "gemma3",
        "deepseek-r1",
        "mistral",
    ],
}


class LLMClient:
    """Unified LLM client wrapping litellm for multi-provider support."""

    def __init__(
        self,
        provider: str,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        aws_region: Optional[str] = None,
    ):
        """Initialize the LLM client.

        Args:
            provider: LLM provider name (openai, anthropic, bedrock, gemini, ollama).
            model: Model name (without provider prefix).
            api_key: API key for the provider.
            base_url: Base URL for API calls (required for Ollama).
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Maximum tokens in response.
            aws_region: AWS region for Bedrock provider.
        """
        self.provider = provider.lower()
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.aws_region = aws_region

    def _get_model_string(self) -> str:
        """Get the litellm model string with provider prefix.

        Returns:
            Model string in litellm format (e.g., 'openai/gpt-4o').
        """
        return f"{self.provider}/{self.model}"

    def _get_completion_kwargs(self) -> Dict:
        """Build keyword arguments for litellm.completion().

        Returns:
            Dict of kwargs for the litellm completion call.
        """
        kwargs = {
            "model": self._get_model_string(),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        if self.api_key:
            kwargs["api_key"] = self.api_key

        if self.base_url:
            kwargs["api_base"] = self.base_url
        elif self.provider == "ollama":
            kwargs["api_base"] = "http://localhost:11434"

        if self.provider == "bedrock" and self.aws_region:
            os.environ["AWS_REGION_NAME"] = self.aws_region

        return kwargs

    def complete(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        stream: bool = False,
    ) -> Union[object, Generator]:
        """Send a completion request to the LLM.

        Args:
            messages: List of message dicts (role, content).
            tools: Optional list of tool definitions in OpenAI format.
            stream: Whether to stream the response.

        Returns:
            litellm response object, or a generator if streaming.
        """
        import litellm

        kwargs = self._get_completion_kwargs()
        kwargs["messages"] = messages
        kwargs["stream"] = stream

        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        return litellm.completion(**kwargs)

    def validate_connection(self) -> Tuple[bool, str]:
        """Test the LLM connection with a simple prompt.

        Returns:
            Tuple of (success, message).
        """
        try:
            response = self.complete(
                messages=[{"role": "user", "content": "Say hello in one word."}],
                stream=False,
            )
            content = response.choices[0].message.content
            return True, f"Connected successfully. Response: {content}"
        except Exception as e:
            error_msg = str(e)
            if len(error_msg) > 300:
                error_msg = error_msg[:300] + "..."
            return False, f"Connection failed: {error_msg}"
