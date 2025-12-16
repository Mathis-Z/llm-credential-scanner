"""
Abstraction over langchains ChatOpenAI and ChatOllama to easily switch between local and remote LLMs
"""
import logging
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama

from scanner.settings import get_settings
settings = get_settings()


def get_chat_model(reasoning: bool|None = None) -> BaseChatModel:
    """
    Returns a ChatOpenAI or ChatOllama instance based on the REMOTE flag.
    """
    if settings.use_local_llm:
        return ChatOllama(model=settings.llm_name, reasoning=reasoning)
    else:
        if reasoning:
            logging.warning("Warning: reasoning parameter is ignored for remote LLMs because its not supported.")

        return ChatOpenAI(
            model_name=settings.llm_name,
            base_url=settings.openai_base_url,
            openai_api_key=settings.openai_api_key,
        )
