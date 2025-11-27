import asyncio
import os
from dotenv import load_dotenv
from openai import OpenAI
from openai.types.responses import CustomToolParam

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from tools import build_formated_tools, run_tools, extract_text

load_dotenv()
api_key = os.getenv("OPENROUTER_API_KEY")

MODEL = "x-ai/grok-4.1-fast"

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=api_key
)

MCP_SERVER_URL = "http://127.0.0.1:8000/mcp"

async def main():
    async with streamablehttp_client(MCP_SERVER_URL) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Available MCP tools:", [t.name for t in tools.tools])

            formated_tools = build_formated_tools(tools)

            user_message = input("Enter your message for the AI: ")
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
                print("\nAI response:\n", ai_text)
                
                input_list += (response.output)

                # Handle tool calls
                tool_inputs = await run_tools(session, response)
                if not tool_inputs:
                    repeat = False

                input_list += tool_inputs
                # print("\nFinal input list for AI:\n", input_list)



if __name__ == "__main__":
    asyncio.run(main())
