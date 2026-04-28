#!/usr/bin/env python3
"""
Update Retell agent llm_websocket_url to point to this server.
(Retell 에이전트 llm_websocket_url을 현재 서버 URL로 업데이트)

Usage:
    python scripts/update_retell_agents.py [--dry-run]

Reads SERVER_URL from .env, converts https → wss, patches each agent.
"""

import asyncio
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

RETELL_API_KEY = os.environ["RETELL_API_KEY"]
RETELL_API_URL = os.environ.get("RETELL_API_URL", "https://api.retellai.com")
SERVER_URL      = os.environ["SERVER_URL"].rstrip("/")

# Convert https:// → wss:// for WebSocket
WS_BASE = SERVER_URL.replace("https://", "wss://").replace("http://", "ws://")
WS_PATH = f"{WS_BASE}/llm-websocket"

HEADERS = {
    "Authorization": f"Bearer {RETELL_API_KEY}",
    "Content-Type":  "application/json",
}

# The 4 demo agents (Rule 2 naming: [INDUSTRY]-[BRAND]-[CHARACTER])
AGENTS = [
    {"id": "agent_68e9f01ec4d5502b990755d2ef", "name": "CAFE-JM-Aria"},
    {"id": "agent_1fb403be0c5428e1a4539ce531", "name": "HOME-JM-Rex"},
    {"id": "agent_8dc7692ae9cbee72d548abe967", "name": "BEAUTY-JM-Luna"},
    {"id": "agent_40679cdb10a1f29eddbcbe10af", "name": "AUTO-JM-Alex"},
]


async def get_agent(client: httpx.AsyncClient, agent_id: str) -> dict:
    resp = await client.get(f"{RETELL_API_URL}/get-agent/{agent_id}", headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


async def update_agent_ws_url(
    client: httpx.AsyncClient,
    agent_id: str,
    ws_url: str,
    dry_run: bool,
) -> dict:
    payload = {
        "response_engine": {
            "type":              "custom-llm",  # Retell uses hyphen, not underscore
            "llm_websocket_url": ws_url,
        }
    }
    if dry_run:
        return {"dry_run": True, "would_set": ws_url}
    resp = await client.patch(
        f"{RETELL_API_URL}/update-agent/{agent_id}",
        headers=HEADERS,
        json=payload,
    )
    resp.raise_for_status()
    return resp.json()


async def main(dry_run: bool = False) -> None:
    print(f"\n{'DRY RUN — ' if dry_run else ''}Retell Agent WebSocket URL Update")
    print(f"Target URL: {WS_PATH}\n")

    async with httpx.AsyncClient(timeout=15) as client:
        for agent in AGENTS:
            agent_id = agent["id"]
            name     = agent["name"]

            # Fetch current config
            try:
                current = await get_agent(client, agent_id)
                engine  = current.get("response_engine", {})
                old_url = engine.get("llm_websocket_url", "—")
            except Exception as exc:
                print(f"  [{name}] FETCH ERROR: {exc}")
                continue

            if old_url == WS_PATH:
                print(f"  [{name}] ✓ Already up to date ({WS_PATH})")
                continue

            # Update
            try:
                result = await update_agent_ws_url(client, agent_id, WS_PATH, dry_run)
                if dry_run:
                    print(f"  [{name}] DRY RUN — would change:")
                    print(f"    FROM: {old_url}")
                    print(f"    TO:   {WS_PATH}")
                else:
                    new_url = (
                        result.get("response_engine", {}).get("llm_websocket_url", "?")
                    )
                    print(f"  [{name}] ✅ Updated")
                    print(f"    FROM: {old_url}")
                    print(f"    TO:   {new_url}")
            except Exception as exc:
                print(f"  [{name}] UPDATE ERROR: {exc}")

    print(f"\n{'DRY RUN complete.' if dry_run else 'Done.'}")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    asyncio.run(main(dry_run=dry_run))
