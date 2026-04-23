#!/usr/bin/env python3
"""
Focused MCP diagnostic for the whatsapp-ad false-positive.
Goal: find out exactly what get_insights can return, and which fields hold
the 551 real conversions that the compact call missed.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from anthropic import Anthropic

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
PIPEBOARD_API_KEY = os.getenv("PIPEBOARD_API_KEY")
MCP_URL = f"https://meta-ads.mcp.pipeboard.co/?token={PIPEBOARD_API_KEY}"

WHATSAPP_AD_ID = "120244420309950580"
GLOBUSSOFT_ACCOUNT = "act_475821441756869"

prompt = f"""
Diagnostic. Output raw data only.

STEP A: Print the full JSON input schema of the `get_insights` tool (from the
        MCP server's tool list). Include every parameter name, type, and default.

STEP B: Call `get_insights` for ad_id={WHATSAPP_AD_ID} (account {GLOBUSSOFT_ACCOUNT})
        over the last 3 days, requesting the RICHEST field set the tool allows.
        Specifically try to include: actions, action_values, frequency, reach,
        impressions, clicks, spend, conversions, conversion_values, purchase_roas,
        cost_per_action_type, cpc, ctr, cpm, and any action_breakdowns parameter.
        If the tool rejects a field name, note it and retry without that field.

STEP C: Dump the EXACT raw JSON the tool returned, verbatim, inside a ```json block.
        No interpretation, no summary, no commentary.

Do not analyze. Do not evaluate rules. Do not recommend. Just: schema, then raw.
""".strip()

client = Anthropic(api_key=ANTHROPIC_API_KEY)
print("Calling Sonnet with focused MCP probe...\n", flush=True)

response = client.beta.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4000,
    mcp_servers=[{"type": "url", "url": MCP_URL, "name": "pipeboard-meta-ads"}],
    messages=[{"role": "user", "content": prompt}],
    betas=["mcp-client-2025-04-04"],
)

print(f"[response type: {type(response).__name__}]", flush=True)
if response is None:
    print("[response is None - aborting]", file=sys.stderr)
    sys.exit(1)
print(f"[stop_reason: {response.stop_reason}]", flush=True)
print("---", flush=True)

for block in response.content:
    btype = getattr(block, "type", None)
    if btype == "text":
        sys.stdout.buffer.write(block.text.encode("utf-8", "replace"))
        sys.stdout.buffer.write(b"\n")
    elif btype == "mcp_tool_use":
        print(f"\n[tool_use] name={block.name} input={block.input!r}"[:400], flush=True)
    elif btype == "mcp_tool_result":
        print(f"\n[tool_result] tool_use_id={getattr(block, 'tool_use_id', '?')}", flush=True)
        for sub in getattr(block, "content", []) or []:
            if getattr(sub, "type", None) == "text":
                sys.stdout.buffer.write(sub.text.encode("utf-8", "replace"))
                sys.stdout.buffer.write(b"\n")

print("\n--- usage ---")
print(f"input_tokens:  {response.usage.input_tokens}")
print(f"output_tokens: {response.usage.output_tokens}")
cost = (response.usage.input_tokens / 1_000_000) * 3 + (response.usage.output_tokens / 1_000_000) * 15
print(f"approx cost:   ${cost:.4f}")
