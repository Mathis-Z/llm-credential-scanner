"""
Abstraction over langchains ChatOpenAI and ChatOllama to easily switch between local and remote LLMs
"""
import time
import threading
from typing import Any
import logging
import openai
from pydantic import PrivateAttr
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.language_models.base import LanguageModelInput
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama

from scanner.settings import Settings
settings = Settings()

logger = logging.getLogger('scanner.llm')

BACKOFF_MINIMUM = 30
BACKOFF_DURATION = BACKOFF_MINIMUM
RATE_LIMITED_UNTIL = 0
API_SERIALIZATION_LOCK = threading.Lock() # prevent concurrent invoke() calls

class WrappedInvokeMixin:
    """Mixin to wrap the invoke method with custom error handling for rate limiting."""
    _abort_event: threading.Event = PrivateAttr()

    def __init__(self, *args, **kwargs):
        abort_event = kwargs.pop("abort_event", None)
        super().__init__(*args, **kwargs)
        self._abort_event = abort_event or threading.Event()

    def invoke(
        self,
        input: LanguageModelInput,
        config: RunnableConfig | None = None,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AIMessage:
        """
        Invoke the LLM with exponential backoff on rate limit errors.
        abort_event can be set to abort the operation.
        """

        global API_SERIALIZATION_LOCK, RATE_LIMITED_UNTIL, BACKOFF_DURATION, BACKOFF_MINIMUM
        with API_SERIALIZATION_LOCK:
            # wait if rate limited
            time_to_wait = max(0, RATE_LIMITED_UNTIL - time.time())
            abortable_sleep(time_to_wait, self._abort_event)

            if self._abort_event.is_set():
                raise RuntimeError("Abort event set")
            try:
                result = super().invoke(input, config=config, stop=stop, **kwargs)
                BACKOFF_DURATION = BACKOFF_MINIMUM # reset on success
                return result
            except openai.RateLimitError:
                RATE_LIMITED_UNTIL = time.time() + BACKOFF_DURATION
                logger.warning("LLM rate limit exceeded. Waiting %.1f seconds before retrying.", BACKOFF_DURATION)
                BACKOFF_DURATION *= 2
                raise # need to re-raise because langchain expects this


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
