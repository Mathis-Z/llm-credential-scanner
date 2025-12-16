import os
from dotenv import load_dotenv


class Settings:
    def __init__(self):
        load_dotenv()

        self.use_local_llm = os.getenv("USE_LOCAL_LLM", "false").lower() == "true"

        if self.use_local_llm:
            self.llm_name = os.environ.get("LLM_NAME", "qwen3:8b-q4_K_M")
        else:
            self.openai_api_key = self.require_env_var("OPENAI_API_KEY")
            self.openai_base_url = os.environ.get("OPENAI_BASE_URL", "https://models.github.ai/inference")
            self.llm_name = os.getenv("LLM_NAME", "gpt-4o-mini")

    def require_env_var(self, var_name: str) -> str:
        value = os.getenv(var_name)
        if not value:
            raise EnvironmentError(f"Environment variable '{var_name}' is required but not set.")
        return value

_settings: Settings | None = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
