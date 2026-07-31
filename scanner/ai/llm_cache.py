# File-based cache for LLM responses to avoid redundant API calls.

import pickle
import hashlib
import json
import time
from pathlib import Path
from typing import Any
from scanner.settings import get_settings


class LLMCache:
    """Singleton cache for LLM responses stored on disk as JSON."""
    _instance = None
    total_requests = 0
    cached_requests = 0
    total_input_tokens = 0
    total_output_tokens = 0
    estimated_tokens_used = False

    def __new__(cls, cache_file: str = "/tmp/llm_cache.json", max_entries: int = 1000):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, cache_file: str = "/tmp/llm_cache.json", max_entries: int = 1000):
        if self._initialized:
            return
        self.cache_file = Path(cache_file)
        self.max_entries = max_entries
        self._ensure_cache_file()
        self._initialized = True

    def _ensure_cache_file(self):
        """Create cache file if it doesn't exist."""
        if not self.cache_file.exists():
            self.cache_file.write_text("{}")

    def _load_cache(self) -> dict:
        """Load the cache from disk."""
        try:
            return json.loads(self.cache_file.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save_cache(self, cache: dict) -> None:
        """Save the cache to disk."""
        self.cache_file.write_text(json.dumps(cache, indent=2))

    def _hash_inputs(self, inputs: Any) -> str:
        """Create cache key by hashing serialized inputs with MD5."""
        pickled = pickle.dumps(inputs)
        return hashlib.md5(pickled).hexdigest()

    def _evict_oldest(self, cache: dict) -> None:
        """Remove oldest entry when cache reaches max_entries limit."""
        if len(cache) >= self.max_entries:
            oldest_key = min(cache.keys(), key=lambda k: cache[k]["timestamp"])
            del cache[oldest_key]

    def record_usage(self, input_tokens: int, output_tokens: int, estimated: bool = False) -> None:
        """
        Track token usage for an LLM call (fresh or replayed from cache).

        Cached responses still count toward the totals, since they represent tokens
        the pipeline logically processed even though no new API call was made.
        """
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        if estimated:
            self.estimated_tokens_used = True

    def store(self, inputs: Any, result: Any, input_tokens: int = 0, output_tokens: int = 0, estimated: bool = False) -> None:
        """Store LLM response in cache with timestamp for LRU eviction, along with its token usage."""
        cache = self._load_cache()
        self._evict_oldest(cache)
        key = self._hash_inputs(inputs)
        cache[key] = {
            "result": pickle.dumps(result).hex(),
            "timestamp": time.time(),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated": estimated,
        }
        self._save_cache(cache)

    def get(self, inputs: Any) -> Any | None:
        """
        Retrieve cached LLM response or None if not found.

        Updates access timestamp on cache hit for LRU tracking.
        Respects disable_llm_cache setting. On a hit, re-applies the token usage
        recorded when the response was first generated (see record_usage).
        """
        self.total_requests += 1

        if get_settings().disable_llm_cache:
            return None

        cache = self._load_cache()
        key = self._hash_inputs(inputs)

        if key not in cache:
            return None
        else:
            self.cached_requests += 1

        entry = cache[key]
        # Update timestamp on access for LRU eviction
        entry["timestamp"] = time.time()
        self._save_cache(cache)

        self.record_usage(entry.get("input_tokens", 0), entry.get("output_tokens", 0), estimated=entry.get("estimated", False))

        result_hex = entry["result"]
        return pickle.loads(bytes.fromhex(result_hex))
