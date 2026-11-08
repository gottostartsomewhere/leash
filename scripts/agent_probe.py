"""Connect to a Leash MCP endpoint the way an outside agent would.

    python scripts/agent_probe.py                                       # local
    python scripts/agent_probe.py https://leash-api-sm0h.onrender.com/mcp

Speaks the real Model Context Protocol over streamable HTTP, through the
official client, so it exercises exactly what Claude or ChatGPT would: the
handshake, the tool list, and the three beats of the demo. A model picks
too expensive and is told what would clear, it comes back inside the cap,
and a purchase split across one merchant's two addresses is caught.

It makes holds against the shared demo mandate and moves no money: the
endpoint has no tool that can. Press Reset on the screen afterwards.
"""

from __future__ import annotations

import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/mcp"


def payload(result) -> dict:
    """A tool result's structured content, or its text parsed as JSON."""
    if getattr(result, "structured_content", None):
        data = result.structured_content
        return data.get("result", data) if isinstance(data, dict) else data
    text = "".join(getattr(c, "text", "") for c in result.content)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"text": text}


async def main() -> int:
    print(f"connecting to {URL}\n")
    async with streamable_http_client(URL) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            server = init.server_info
            print(f"server       {server.name} {server.version or ''}".rstrip())
            tools = (await session.list_tools()).tools
            print(f"tools        {', '.join(t.name for t in tools)}")
            print(f"instructions {len(init.instructions or '')} characters\n")

            async def call(name: str, **args) -> dict:
                result = await session.call_tool(name, args)
                if result.is_error:
                    raise RuntimeError(f"{name} failed: {payload(result)}")
                return payload(result)

            m = await call("read_mandate")
            t = m["terms"]
            print(f"mandate      {m['status']}, {m['available']} available")
            print(f"             {t['per_purchase']} a purchase, {t['per_merchant']} a merchant, "
                  f"categories {t['categories']}\n")

            found = (await call("search_products", query="office chair"))["results"]
            print(f"search       {len(found)} office chairs")
            over = next((r for r in found if float(r["amount"]) > 100), None)
            under = next((r for r in found if float(r["amount"]) <= 100), None)

            failures = 0

            if over:
                d = await call("request_purchase", payee=over["payee"], amount=over["amount"],
                               category=over["category"], description=over["title"])
                ok = d["verdict"] == "block" and d["largest_that_would_clear"]
                failures += not ok
                print(f"\n1. too much  {over['title'][:40]} at {over['price']}")
                print(f"             {d['verdict']}: {d['reason']}")
                print(f"             largest that would clear: {d['largest_that_would_clear']}"
                      f"   {'ok' if ok else 'WRONG'}")

                # What a good agent does with a refusal: search again under the
                # ceiling it was given, rather than give up or retry blindly.
                if under is None and d["largest_that_would_clear"]:
                    ceiling = float(d["largest_that_would_clear"].split()[0])
                    again = (await call("search_products", query="office chair",
                                        max_price=ceiling))["results"]
                    print(f"             searched again under {ceiling:.2f}: {len(again)} found")
                    under = again[0] if again else None

            if under:
                d = await call("request_purchase", payee=under["payee"], amount=under["amount"],
                               category=under["category"], description=under["title"])
                ok = d["verdict"] == "allow"
                failures += not ok
                print(f"\n2. inside    {under['title'][:40]} at {under['price']}")
                print(f"             {d['verdict']}, {d['remaining_after']} left   {'ok' if ok else 'WRONG'}")
                print(f"             {d['next']}")

            first = await call("request_purchase", payee="acme_us", amount="75",
                               category="furniture", description="half of a split purchase")
            second = await call("request_purchase", payee="acme_eu", amount="75",
                                category="furniture", description="the other half")
            caught = [r["rule"] for r in second["refused_by"]]
            ok = first["verdict"] == "allow" and "structuring" in caught
            failures += not ok
            print("\n3. split     75.00 to acme_us, then 75.00 to acme_eu")
            print(f"             first {first['verdict']}, second {second['verdict']} by {caught}"
                  f"   {'ok' if ok else 'WRONG'}")

            recent = (await call("recent_decisions", limit=5))["decisions"]
            print(f"\nrecent       {len(recent)} decisions on record, newest: "
                  f"{recent[0]['verdict']} {recent[0]['payee']} {recent[0]['amount']}")

    print("\nheld only; nothing moved. Reset the demo from the screen when done.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
