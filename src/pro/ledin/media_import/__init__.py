"""Faithful media and document imports into Markdown corpora."""

from .config import Config, ConfigError, load_config

__all__ = ["Config", "ConfigError", "load_config"]
__version__ = "0.1.0"
