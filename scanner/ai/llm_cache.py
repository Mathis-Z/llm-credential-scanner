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

    def store(self, inputs: Any, result: Any) -> None:
        """Store LLM response in cache with timestamp for LRU eviction."""
        cache = self._load_cache()
        self._evict_oldest(cache)
        key = self._hash_inputs(inputs)
        cache[key] = {
            "result": pickle.dumps(result).hex(),
            "timestamp": time.time()
        }
        self._save_cache(cache)

    def get(self, inputs: Any) -> Any | None:
        """
        Retrieve cached LLM response or None if not found.
        
        Updates access timestamp on cache hit for LRU tracking.
        Respects disable_llm_cache setting.
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

        # Update timestamp on access for LRU eviction
        cache[key]["timestamp"] = time.time()
        self._save_cache(cache)

        result_hex = cache[key]["result"]
        return pickle.loads(bytes.fromhex(result_hex))
