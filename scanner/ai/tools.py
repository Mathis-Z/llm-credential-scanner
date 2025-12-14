import json
import logging


def build_formated_tools(tools):
    formated = []

    def _get(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    for t in tools:
        name = _get(t, "name")
        description = _get(t, "description", "") or ""
        schema = _get(t, "input_schema") or _get(t, "schema") or _get(t, "parameters")

        if isinstance(schema, dict) and "properties" in schema:
            parameters = {
                "type": "object",
                "properties": schema.get("properties", {}),
                "required": schema.get("required", []),
            }
        else:
            parameters = {
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "Free-text input for the tool",
                    }
                },
                "required": [],
            }

        formated.append(
            {
                "type": "function",
                "name": name,
                "description": description,
                "parameters": parameters,
            }
        )

    return formated

async def run_tool(session, tool_name, tool_input, context: str = None):
    tools = await session.list_tools()
    tool = next((t for t in tools.tools if t.name == tool_name), None)
    if not tool:
        return f"Tool '{tool_name}' not found."

    # Ensure tool_input is a dict
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
            # Add context if available
            if context:
                tool_input['context'] = context
        except json.JSONDecodeError:
            tool_input = {"input": tool_input}  # fallback if it's plain text
            # Add context if available
            if context:
                tool_input['context'] = context

    logging.info("Running tool '%s' with input: %s", tool_name, tool_input)
    result = await session.call_tool(tool_name, tool_input)
    return result


async def run_tools(session, response, context: str = None):
    input_list = []
    for item in response.output:
        if item.type == "function_call":
            tool_name = item.name
            tool_input = item.arguments

            logging.info("Preparing to run tool '%s' with input: %s", tool_name, tool_input)

            # Run the tool
            tool_result = await run_tool(session, tool_name, tool_input)

            # Convert the result to a dict if it has a .dict() method
            if hasattr(tool_result, "dict"):
                serializable_result = tool_result.dict()
            else:
                serializable_result = tool_result  # fallback

            input_list.append({
                "type": "function_call_output",
                "call_id": item.call_id,
                "output": json.dumps({
                    f"{tool_name}": serializable_result
                })
            })
    return input_list

def extract_text(output_items):
    if not output_items:
        return ""
    texts = []
    for item in output_items:
        if hasattr(item, "content") and item.content:
            for c in item.content:
                if hasattr(c, "text") and c.text:
                    texts.append(c.text)
        elif hasattr(item, "summary") and item.summary:
            texts.extend(item.summary)
        elif item.type == "function_call":
            texts.append(f"[Function call: {item.name} with args {item.arguments}]")
    return "\n".join(texts)
