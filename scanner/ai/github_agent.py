import asyncio
import logging
import os
import click
from dotenv import load_dotenv
from openai import OpenAI
from types import SimpleNamespace
import json

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from tools import (
    build_formated_tools,
    run_tools,
    extract_text,
    get_tools_by_tag,
)

load_dotenv()

MODEL = "openai/gpt-4o-mini"   # GitHub Models name
GITHUB_API_KEY = os.getenv("GITHUB_API_KEY")

client = OpenAI(
    base_url="https://models.github.ai/inference",
    api_key=GITHUB_API_KEY,
)

MCP_SERVER_URL = "http://127.0.0.1:8000/mcp"


def mcp_tools_to_openai_chat_tools(mcp_tools):
    """
    Convert MCP tool definitions to OpenAI chat.completions tool schema
    """
    chat_tools = []

    for tool in mcp_tools:
        chat_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("parameters", {}),
            },
        })

    return chat_tools




def chat_completion_to_responses_style(response):
    """
    Convert GitHub ChatCompletion to MCP Responses-style object
    """
    output = []

    message = response.choices[0].message

    # Assistant text
    if message.content:
        output.append(
            SimpleNamespace(
                type="output_text",
                content=message.content,
            )
        )

    # Tool calls
    for tc in getattr(message, "tool_calls", []) or []:
        output.append(
            SimpleNamespace(
                type="function_call",
                name=tc.function.name,
                arguments=tc.function.arguments,
                call_id=str(getattr(tc, "id", "")),
            )
        )

    return SimpleNamespace(output=output)



async def answer_with_tools(question: str, allowed_tool_tags=None):
    async with streamablehttp_client(MCP_SERVER_URL) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            mcp_tools = await get_tools_by_tag(session, allowed_tool_tags)
            logging.info("Available MCP tools: %s", ", ".join(t.name for t in mcp_tools))


            formatted_tools = mcp_tools_to_openai_chat_tools(
                [t.model_dump() for t in mcp_tools]
            )

            logging.info("Formatted tools: %s", formatted_tools)

            messages = [
                {"role": "user", "content": question}
            ]

            repeat = True
            final_text = ""

            while repeat:
                # Call GitHub LLM
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    tools=formatted_tools,
                    tool_choice="auto",
                )

                message = response.choices[0].message

                if message.content:
                    final_text += message.content

                messages.append({
                    "role": message.role or "assistant",
                    "content": message.content or "",
                    "tool_calls": getattr(message, "tool_calls", None)
                })

                adapted_response = chat_completion_to_responses_style(response)
                tool_inputs = await run_tools(session, adapted_response)

                if not tool_inputs:
                    repeat = False
                else:

                    for t in tool_inputs:
                        call_id = t.get("call_id")

                        raw_output = t.get("output")
                        content = None
                        if raw_output:
                            try:
                                parsed = json.loads(raw_output)
                                first_key = next(iter(parsed.keys()))
                                items = parsed[first_key].get("content", [])
                                content = " ".join([item.get("text", "") for item in items])
                            except Exception as e:
                                content = raw_output

                        messages.append({
                            "role": "tool",
                            "name": t.get("name", ""),
                            "content": content,
                            "arguments": t.get("arguments", None),
                            "tool_call_id": call_id,
                        })

            return final_text

@click.command()
@click.option("--log-level", default="INFO", help="Logging level")
def main(log_level="INFO"):
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), None),
        format="[%(asctime)s][%(levelname)s] %(message)s",
    )

    question = input("Enter your question: ")
    response = asyncio.run(
        answer_with_tools(
            question,
            allowed_tool_tags=["credential_search"],
        )
    )
    print("AI response:", response)


if __name__ == "__main__":
    main()
