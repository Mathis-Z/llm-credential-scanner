"""
Abstraction over langchains ChatOpenAI and ChatOllama to easily switch between local and remote LLMs
"""
import time
import json
import threading
from typing import Any
import logging
import openai
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.language_models.base import LanguageModelInput
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama

from scanner.settings import get_settings
from .llm_cache import LLMCache

logger = logging.getLogger('scanner.llm')

API_SERIALIZATION_LOCK = threading.Lock() # prevent concurrent invoke() calls

class WrappedInvokeMixin:
    """Mixin to wrap the invoke method with custom error handling for rate limiting."""

    def _make_cache_key(self, input, config, stop, kwargs):
        """Create a cacheable representation of the invoke parameters."""
        cache_dict = {}
        
        # Handle input (messages)
        if isinstance(input, str):
            cache_dict['input'] = input
        elif isinstance(input, list):
            cache_dict['input'] = [
                {'type': msg.type, 'content': msg.content} if isinstance(msg, BaseMessage) else str(msg)
                for msg in input
            ]
        else:
            cache_dict['input'] = str(input)
        
        # Handle stop sequences
        cache_dict['stop'] = stop
        
        # Handle kwargs - only cache relevant parameters
        relevant_kwargs = {}
        for key in ['temperature', 'max_tokens', 'top_p', 'frequency_penalty', 'presence_penalty', 'parallel_tool_calls']:
            if key in kwargs:
                relevant_kwargs[key] = kwargs[key]
        
        # Handle tools if present
        if 'tools' in kwargs:
            try:
                # Try to serialize tools to JSON-compatible format
                relevant_kwargs['tools'] = [
                    {'type': t.get('type'), 'function': t.get('function', {}).get('name')}
                    if isinstance(t, dict) else str(t)
                    for t in kwargs.get('tools', [])
                ]
            except Exception:
                relevant_kwargs['tools'] = str(kwargs['tools'])
        
        cache_dict['kwargs'] = relevant_kwargs
        
        # Convert to JSON string for consistent hashing
        return json.dumps(cache_dict, sort_keys=True)

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
        cache_key = self._make_cache_key(input, config, stop, kwargs)
        result = LLMCache().get(cache_key)
        if result:
            logger.debug("Returning cached LLM response")
            return result

        with API_SERIALIZATION_LOCK:
            result = None
            backoff_seconds = 60 # as per github docs, we should wait at least 60s before retrying after rate limit

            while result is None:
                try:
                    # disable parallel tool calls to avoid issues with wrong order
                    kwargs['parallel_tool_calls'] = False
                    result = super().invoke(input, config=config, stop=stop, **kwargs)
                except openai.RateLimitError as e:
                    retry_after_header = e.response.headers.get("retry-after", e.response.headers.get("x-ratelimit-timeremaining"))
                    ratelimit_reset_header = e.response.headers.get("x-ratelimit-reset")
                    if retry_after_header is not None:
                        backoff_seconds = int(retry_after_header)
                    elif ratelimit_reset_header is not None:
                        backoff_seconds = max(int(ratelimit_reset_header) - time.time(), backoff_seconds)
                    if backoff_seconds > time.time():
                        backoff_seconds = int(backoff_seconds - time.time()) # convert to seconds from epoch to relative seconds

                    logger.debug("Rate limit error details: %s, headers: %s", e, e.response.headers)

                    logger.warning("LLM rate limit exceeded. Trying again after %s seconds...", backoff_seconds)
                    time.sleep(backoff_seconds)
                    backoff_seconds = min(backoff_seconds * 2, 600) # exponential backoff up to 10 minutes

            LLMCache().store(cache_key, result)
            return result

    def bind_tools(
        self,
        tools,
        *,
        tool_choice: dict | str | bool | None = None,
        strict: bool | None = None,
        parallel_tool_calls: bool | None = None,
        response_format = None,
        **kwargs: Any,
    ):
        kwargs.pop("parallel_tool_calls", None)  # remove if present
        return super().bind_tools(
            tools,
            tool_choice=tool_choice,
            strict=strict,
            parallel_tool_calls=False,  # disable parallel tool calls to avoid issues with wrong order
            response_format=response_format,
            **kwargs,
        )

class WrappedChatOllama(WrappedInvokeMixin, ChatOllama):
    """ChatOllama with WrappedInvokeMixin to handle rate limiting."""

class WrappedChatOpenAI(WrappedInvokeMixin, ChatOpenAI):
    """ChatOpenAI with WrappedInvokeMixin to handle rate limiting."""


def get_chat_model(reasoning: bool|None = None) -> WrappedChatOllama|WrappedChatOpenAI:
    """
    Returns a ChatOpenAI or ChatOllama instance based on the USE_LOCAL_LLM setting.
    """
    settings = get_settings()
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
