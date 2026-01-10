"""
Abstraction over langchains ChatOpenAI and ChatOllama to easily switch between local and remote LLMs
"""
import time
import threading
from typing import Any
import logging
import openai
from pydantic import PrivateAttr
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
            try:
                return super().invoke(input, config=config, stop=stop, **kwargs)
            except openai.RateLimitError:
                logger.warning("LLM rate limit exceeded.")
                raise # need to re-raise because langchain expects this


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
