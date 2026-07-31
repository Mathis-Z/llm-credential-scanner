# Application configuration using Pydantic settings.
# Supports environment variables and CLI overrides.

import os
import logging
import logging.config
from functools import cached_property
from pathlib import Path
from pydantic import model_validator, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_max_webdrivers() -> int:
    """Cap concurrent browser instances at min(CPU cores, RAM in GB / 4) - each browser is fairly memory-hungry."""
    cpu_cores = os.cpu_count() or 1
    try:
        ram_gb = (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) / (1024 ** 3)
    except (AttributeError, ValueError, OSError):
        ram_gb = cpu_cores * 4  # sysconf unavailable (e.g. non-POSIX); don't let RAM constrain the estimate
    return max(1, min(cpu_cores, int(ram_gb // 4)))


def configure_logging():
    """Configure logging for the scanner application. Filters to only show 'scanner.*' logs."""
    handlers = {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["scanner_only"],
            "formatter": "default",
        }
    }

    Path(get_settings().log_file).parent.mkdir(parents=True, exist_ok=True)
    handlers["file"] = {
        "class": "logging.FileHandler",
        "filters": ["scanner_only"],
        "formatter": "default",
        "filename": str(get_settings().log_file),
        "encoding": "utf-8"
    }

    root_handlers = ["console", "file"]

    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "scanner_only": {
                "()": lambda: logging.Filter("scanner")
            }
        },
        "handlers": handlers,
        "formatters": {
            "default": {
                "format": "[%(asctime)s][%(name)s][%(levelname)s] %(message)s"
            }
        },
        "root": {
            "level": get_settings().log_level.upper(),
            "handlers": root_handlers
        }
    })


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # LLM
    use_local_llm: bool = False
    reasoning_llm_name: str | None = None
    nonreasoning_llm_name: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str = "https://openrouter.ai/api/v1"

    # Scanner
    subnets: list[str] = []
    ports: str | None = None
    artifacts_dir: Path = Path("scan_artifacts")
    _log_file: Path | None = None
    log_level: str = "INFO"
    disable_llm_cache: bool = False
    max_webdrivers: int | None = None
    max_webenum_workers: int = 4
    db_max_connections: int = 32

    # RAG-based credential search
    embedding_model_name: str = "TaylorAI/bge-micro-v2"
    rag_num_search_results: int = 10   # top-N DDGS results fetched per service
    rag_chunk_size: int = 700          # characters per chunk
    rag_chunk_overlap: int = 100       # character overlap between chunks
    rag_query_max_chars: int = 300     # cap on combined search-query length

    @model_validator(mode="after")
    def resolve_dynamic_defaults(self) -> "Settings":
        """Apply defaults that depend on other field values."""
        if self.max_webdrivers is None:
            self.max_webdrivers = _default_max_webdrivers()

        if self.use_local_llm:
            if self.reasoning_llm_name is None:
                self.reasoning_llm_name = "qwen3:8b-q4_K_M"
            if self.nonreasoning_llm_name is None:
                self.nonreasoning_llm_name = "qwen3:4b-instruct-2507-q4_K_M"
        else:
            if self.reasoning_llm_name is None:
                self.reasoning_llm_name = "gpt-4o-mini"
            if self.nonreasoning_llm_name is None:
                self.nonreasoning_llm_name = "gpt-4o-mini"
            if not self.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required when not using a local LLM")
        return self

    @field_validator("artifacts_dir", mode="before")
    @classmethod
    def resolve_artifacts_dir(cls, v) -> Path:
        return Path(os.getcwd()) / v

    @cached_property
    def db_path(self) -> Path:
        return self.artifacts_dir / "scanner.db"

    @property
    def log_file(self) -> Path:
        if self._log_file is not None:
            return self._log_file
        return self.artifacts_dir / "scanner.log"

    @log_file.setter
    def log_file(self, value: Path) -> None:
        self._log_file = self.artifacts_dir / value


# Module-level singleton
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def override_settings(**kwargs) -> None:
    """Apply CLI argument overrides after initial construction."""
    settings = get_settings()
    for key, value in kwargs.items():
        if value is not None:
            setattr(settings, key, value)
