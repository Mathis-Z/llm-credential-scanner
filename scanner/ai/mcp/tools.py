import json
import logging

async def get_tools_by_tag(session, allowed_tags):
    all_tools = await session.list_tools()
    filtered_tools = []

    for tool in all_tools.tools:
        tool_tags = tool.meta.get("tags", [])

        if any(tag in allowed_tags for tag in tool_tags):
            filtered_tools.append(tool)

    return filtered_tools

def build_formated_tools(tools):
    formated = []

    def _get(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def _resolve_schema(schema) -> dict:
        """
        Convert MCP inputSchema into OpenAI function-call parameters.
        Resolves top-level $ref and also input-> $ref nested schemas.
        """
        import json

        if isinstance(schema, str):
            schema = json.loads(schema)
        elif not isinstance(schema, dict):
            return {"type": "object", "properties": {}, "required": []}

        # If the top-level is a $ref, resolve it
        if "$ref" in schema:
            ref_path = schema["$ref"]
            ref_name = ref_path.split("/")[-1]
            schema = schema.get("$defs", {}).get(ref_name, {})

        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # Check for nested input with $ref (TypedDict)
        if "input" in properties and "$ref" in properties["input"]:
            ref_path = properties["input"]["$ref"]
            ref_name = ref_path.split("/")[-1]
            ref_schema = schema.get("$defs", {}).get(ref_name, {})
            properties = ref_schema.get("properties", {})
            required = ref_schema.get("required", [])

        return {"type": "object", "properties": properties, "required": required}

    for t in tools:
        name = _get(t, "name")
        description = _get(t, "description", "") or ""
        schema = _get(t, "inputSchema") or _get(t, "input_schema") or _get(t, "schema") or _get(t, "parameters")

        parameters = _resolve_schema(schema)

        formated.append(
            {
                "type": "function",
                "name": name,
                "description": description,
                "parameters": parameters,
            }
        )

    return formated

async def run_tool(session, tool_name, tool_input):
    tools = await session.list_tools()
    tool = next((t for t in tools.tools if t.name == tool_name), None)
    if not tool:
        return f"Tool '{tool_name}' not found."

    # Ensure tool_input is a dict
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except json.JSONDecodeError:
            tool_input = {"input": tool_input}  # fallback if it's plain text

    logging.info("Running tool '%s' with input: %s", tool_name, tool_input)
    result = await session.call_tool(tool_name, tool_input)
    return result


async def run_tools(session, response):
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
                "name": tool_name,
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
