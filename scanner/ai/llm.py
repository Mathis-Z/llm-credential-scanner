"""
Abstraction over langchains ChatOpenAI and ChatOllama to easily switch between local and remote LLMs
"""
import time
import threading
from typing import Any
import logging
import openai
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.language_models.base import LanguageModelInput
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama

from scanner.settings import Settings
settings = Settings()

logger = logging.getLogger('scanner.llm')

class WrappedInvokeMixin(BaseChatModel):
    """Mixin to wrap the invoke method with custom error handling for rate limiting."""
    def invoke(
        self,
        input: LanguageModelInput,
        config: RunnableConfig | None = None,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AIMessage:
        try:
            return super().invoke(input, config=config, stop=stop, **kwargs)
        except openai.RateLimitError:
            logger.warning("LLM rate limit exceeded")
            raise # must re-raise here because langchain asserts this never returns None

    def invoke_with_backoff(
        self,
        input: LanguageModelInput,
        config: RunnableConfig | None = None,
        *,
        stop: list[str] | None = None,
        abort_signal: threading.Event = threading.Event(),
        **kwargs: Any,
    ) -> AIMessage:
        """
        Invoke the LLM with exponential backoff on rate limit errors.
        abort_signal can be set to abort the operation.
        """
        backoff_seconds = 1.0
        while not abort_signal.is_set():
            try:
                return super().invoke(input, config=config, stop=stop, **kwargs)
            except openai.RateLimitError as e:
                logger.warning("LLM rate limit exceeded. Waiting %.1f seconds before retrying. Error msg: %s", backoff_seconds, e.message)
                abortable_sleep(backoff_seconds, abort_signal)
                backoff_seconds = min(backoff_seconds * 2, 120.0)


def abortable_sleep(
    total_seconds: float,
    abort_event: threading.Event,
    check_interval: float = 0.5,
):
    elapsed = 0.0
    while elapsed < total_seconds:
        if abort_event.is_set():
            return
        sleep_time = min(check_interval, total_seconds - elapsed)
        time.sleep(sleep_time)
        elapsed += sleep_time


class WrappedChatOllama(ChatOllama, WrappedInvokeMixin):
    """ChatOllama with WrappedInvokeMixin to handle rate limiting."""

class WrappedChatOpenAI(ChatOpenAI, WrappedInvokeMixin):
    """ChatOpenAI with WrappedInvokeMixin to handle rate limiting."""


def get_chat_model(reasoning: bool|None = None) -> WrappedChatOllama|WrappedChatOpenAI:
    """
    Returns a ChatOpenAI or ChatOllama instance based on the USE_LOCAL_LLM setting.
    """
    if settings.use_local_llm:
        return WrappedChatOllama(model=settings.llm_name, reasoning=reasoning)
    else:
        if reasoning:
            logger.warning("Warning: reasoning parameter is ignored for remote LLMs because its not supported.")

        return WrappedChatOpenAI(
            model_name=settings.llm_name,
            base_url=settings.openai_base_url,
            openai_api_key=settings.openai_api_key,
        )
