"""Not a unit test: drives the MCP adapter over stdio the way a model would. Needs the mcp package."""
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(app_dir):
    params = StdioServerParameters(command=sys.executable, args=["-m", "storecheck.mcp_server"])
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("tools:", ", ".join(t.name for t in tools.tools))
            res = await s.call_tool("audit_run", {"app_dir": app_dir, "offline": True})
            out = json.loads(res.content[0].text)
            if "error" in out:
                print("audit_run:", out["error"]); return
            print("audit_run:", out["counts"], "awaiting:", out["awaiting_judgement"])
            res = await s.call_tool("audit_get_rule", {"rule_id": "apple.purpose-strings-say-why"})
            rule = json.loads(res.content[0].text)
            print("audit_get_rule:", rule["id"], "records:", [(c["id"], c["status"], len(c["text"] or "")) for c in rule["corpus_records"]])
            res = await s.call_tool("fix_propose", {"app_dir": app_dir, "rule_id": "apple.built-matches-source"})
            print("fix_propose:", json.loads(res.content[0].text)["kind"])
            res = await s.call_tool("audit_adversarial", {"app_dir": app_dir})
            print("audit_adversarial:", json.loads(res.content[0].text)["summary"])


asyncio.run(main(sys.argv[1]))
