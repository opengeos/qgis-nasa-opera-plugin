"""Compatibility exports for GeoAgent model configuration.

The NASA OPERA AI assistant now uses GeoAgent's Strands provider stack
directly. New code should import from ``nasa_opera.ai.model_config``.
"""

from .model_config import AVAILABLE_MODELS, DEFAULT_MODELS, PROVIDERS

__all__ = ["AVAILABLE_MODELS", "DEFAULT_MODELS", "PROVIDERS"]
