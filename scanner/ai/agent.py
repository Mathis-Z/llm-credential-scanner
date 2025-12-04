import asyncio
import logging
import os
import click
from dotenv import load_dotenv
from openai import OpenAI

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from tools import build_formated_tools, run_tools, extract_text

load_dotenv()
api_key = os.getenv("OPENROUTER_API_KEY")

MODEL = "arcee-ai/trinity-mini:free"

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=api_key
)

MCP_SERVER_URL = "http://127.0.0.1:8000/mcp"


async def answer_with_tools(question: str):
    async with streamablehttp_client(MCP_SERVER_URL) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            # print("Available MCP tools:", [t.name for t in tools.tools])

            formated_tools = build_formated_tools(tools)

            user_message = question
            input_list = [
                {"role": "user", "content": user_message}
            ]

            # Tool execution loop
            repeat = True
            while repeat:

                # Send message to OpenRouter
                response = client.responses.create(
                    model=MODEL,
                    tools=formated_tools,
                    input=input_list,
                )

                # Flatten AI output
                ai_text = extract_text(response.output)

                input_list += (response.output)

                tool_inputs = await run_tools(session, response)
                if not tool_inputs:
                    repeat = False

                input_list += tool_inputs

    return ai_text

@click.command()
@click.option('--log-level', default='INFO', help='Logging level')
def main(log_level='INFO'):
    logging.basicConfig(level=getattr(logging, log_level.upper(), None), format='[%(asctime)s][%(levelname)s] %(message)s')

    question = input("Enter your question: ")
    response = asyncio.run(answer_with_tools(question))
    print("AI response:", response)

if __name__ == "__main__":
    main()
