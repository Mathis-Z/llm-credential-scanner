"""
Abstraction over langchains ChatOpenAI and ChatOllama to easily switch between local and remote LLMs
"""
import time
import threading
from typing import Any
import logging
import openai
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.language_models.base import LanguageModelInput
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama

from scanner.settings import Settings
settings = Settings()

logger = logging.getLogger('scanner.llm')

API_SERIALIZATION_LOCK = threading.Lock() # prevent concurrent invoke() calls

class WrappedInvokeMixin:
    """Mixin to wrap the invoke method with custom error handling for rate limiting."""

    def invoke(
        self,
        input: LanguageModelInput,
        config: RunnableConfig | None = None,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AIMessage:
        """
        Invoke the LLM and handle rate limiting by serializing calls.
        """
        with API_SERIALIZATION_LOCK:
            result = None
            backoff_seconds = 60 # as per github docs, we should wait at least 60s before retrying after rate limit

            while result is None:
                try:
                    result = super().invoke(input, config=config, stop=stop, **kwargs)
                except openai.RateLimitError as e:
                    retry_after_header = e.response.headers.get("Retry-After")
                    ratelimit_reset_header = e.response.headers.get("X-Ratelimit-Reset")
                    if retry_after_header is not None:
                        backoff_seconds = int(retry_after_header)
                    elif ratelimit_reset_header is not None:
                        backoff_seconds = max(int(ratelimit_reset_header) - time.time(), backoff_seconds)

                    logger.debug("Rate limit error details: %s, headers: %s", e, e.response.headers)

                    logger.warning("LLM rate limit exceeded. Trying again after %s seconds...", backoff_seconds)
                    time.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2, 600) # exponential backoff up to 10 minutes
            return result


class WrappedChatOllama(WrappedInvokeMixin, ChatOllama):
    """ChatOllama with WrappedInvokeMixin to handle rate limiting."""

class WrappedChatOpenAI(WrappedInvokeMixin, ChatOpenAI):
    """ChatOpenAI with WrappedInvokeMixin to handle rate limiting."""


def get_chat_model(reasoning: bool|None = None) -> WrappedChatOllama|WrappedChatOpenAI:
    """
    Returns a ChatOpenAI or ChatOllama instance based on the USE_LOCAL_LLM setting.
    """
    model_name = settings.reasoning_llm_name if reasoning else settings.nonreasoning_llm_name

    if settings.use_local_llm:
        return WrappedChatOllama(model=model_name, reasoning=reasoning)
    else:
        if reasoning:
            logger.warning("Warning: reasoning parameter is ignored for remote LLMs because its not supported.")

        return WrappedChatOpenAI(
            model_name=model_name,
            base_url=settings.openai_base_url,
            openai_api_key=settings.openai_api_key,
        )
