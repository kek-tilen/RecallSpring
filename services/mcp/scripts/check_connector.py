"""Read-only self-check of the connector setup, without Claude: starts the MCP server over stdio exactly like
Claude Desktop does and calls a few read tools against your running RecallSpring API.

    services/mcp/.venv/Scripts/python services/mcp/scripts/check_connector.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import Client, StdioServerParameters


async def main() -> int:
    params = StdioServerParameters(command=sys.executable, args=["-m", "recallspring_mcp"])
    async with Client(params) as client:
        tools = [t.name for t in (await client.list_tools()).tools]
        print(f"Connector started with {len(tools)} tools.")
        result = await client.call_tool("list_courses", {})
        text = "".join(c.text for c in result.content if c.type == "text")
        if result.is_error:
            print(f"Problem: {text}")
            return 1
        courses = json.loads(text)
        print(f"RecallSpring reachable: {len(courses)} course(s).")
        plan = await client.call_tool("get_study_plan", {})
        items = json.loads("".join(c.text for c in plan.content if c.type == "text"))["items"]
        print(f"Today's plan has {len(items)} item(s). Connector OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
