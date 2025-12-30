import os
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
            self.llm_name = os.environ.get("LLM_NAME", "qwen3:8b-q4_K_M")
        else:
            self.openai_api_key = self._require_env_var("OPENAI_API_KEY")
            self.openai_base_url = os.environ.get("OPENAI_BASE_URL", "https://models.github.ai/inference")
            self.llm_name = os.getenv("LLM_NAME", "gpt-4o-mini")

        self._initialized = True

    def _require_env_var(self, var_name: str) -> str:
        value = os.getenv(var_name)
        if not value:
            raise EnvironmentError(f"Environment variable '{var_name}' is required but not set.")
        return value
