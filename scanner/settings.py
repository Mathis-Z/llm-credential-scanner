import os
from pathlib import Path
from dotenv import load_dotenv


class Settings:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(Settings, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        load_dotenv()

        self.use_local_llm = os.getenv("USE_LOCAL_LLM", "false").lower() == "true"

        if self.use_local_llm:
            self.reasoning_llm_name = os.environ.get("REASONING_LLM_NAME", "qwen3:8b-q4_K_M")
            self.nonreasoning_llm_name = os.environ.get("NONREASONING_LLM_NAME", "qwen3:4b-instruct-2507-q4_K_M")
        else:
            self.openai_api_key = self._require_env_var("OPENAI_API_KEY")
            self.openai_base_url = os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
            self.reasoning_llm_name = os.getenv("REASONING_LLM_NAME", "gpt-4o-mini")
            self.nonreasoning_llm_name = os.getenv("NONREASONING_LLM_NAME", "gpt-4o-mini") # TODO: is there a non-reasoning model?

        self.artifacts_dir = Path(os.getcwd()) / os.getenv("ARTIFACTS_DIR", "scan_artifacts")
        self.disable_llm_cache = os.getenv("DISABLE_LLM_CACHE", None) is not None
        self._initialized = True

    def _require_env_var(self, var_name: str) -> str:
        value = os.getenv(var_name)
        if not value:
            raise EnvironmentError(f"Environment variable '{var_name}' is required but not set.")
        return value

    def configure_cli_arguments(self, **kwargs):
        self.artifacts_dir = Path(os.getcwd()) / kwargs.get("artifacts_dir", self.artifacts_dir)
        self.disable_llm_cache = kwargs.get("disable_llm_cache", self.disable_llm_cache)

    @property
    def db_path(self) -> str:
        return self.artifacts_dir / "scanner.db"
