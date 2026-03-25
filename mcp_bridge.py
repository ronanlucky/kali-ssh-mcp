#!/usr/bin/env python3
"""
mcp_bridge.py — MCP Server: Claude Desktop ↔ Kali Linux SSH Bridge

Exposes a run_command tool via the Model Context Protocol (MCP) stdio transport,
allowing Claude Desktop to execute commands on a remote Kali Linux host over SSH.
"""

import sys
import json
import subprocess
import paramiko
import logging

logging.basicConfig(
    filename="mcp_bridge.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ── SSH Configuration ──────────────────────────────────────────────────────────
SSH_HOST = "192.168.3.50"   # kali_in IP — update as needed
SSH_PORT = 22
SSH_USER = "kali"
SSH_PASS = "kali"           # Replace with key-based auth in production
TIMEOUT  = 30               # seconds
# ──────────────────────────────────────────────────────────────────────────────

TOOL_MANIFEST = {
    "tools": [
        {
            "name": "run_command",
            "description": (
                "Execute a shell command on the remote Kali Linux host via SSH. "
                "Returns stdout and stderr. Use for network recon, log analysis, "
                "and firewall inspection tasks."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to run on the Kali host."
                    }
                },
                "required": ["command"]
            }
        }
    ]
}


def ssh_exec(command: str) -> dict:
    """Open an SSH session, run command, return stdout/stderr."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            SSH_HOST, port=SSH_PORT,
            username=SSH_USER, password=SSH_PASS,
            timeout=TIMEOUT
        )
        logging.info("SSH connected. Running: %s", command)
        _, stdout, stderr = client.exec_command(command, timeout=TIMEOUT)
        out = stdout.read().decode(errors="replace").strip()
        err = stderr.read().decode(errors="replace").strip()
        logging.info("stdout: %s | stderr: %s", out[:200], err[:200])
        return {"stdout": out, "stderr": err}
    except Exception as e:
        logging.error("SSH error: %s", e)
        return {"stdout": "", "stderr": str(e)}
    finally:
        client.close()


def handle_message(msg: dict) -> dict | None:
    method = msg.get("method")
    msg_id = msg.get("id")

    # Capability negotiation
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "kali-ssh", "version": "1.0.0"}
            }
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": TOOL_MANIFEST}

    if method == "tools/call":
        tool_name = msg.get("params", {}).get("name")
        args      = msg.get("params", {}).get("arguments", {})

        if tool_name == "run_command":
            command = args.get("command", "").strip()
            if not command:
                return {
                    "jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32602, "message": "No command provided."}
                }
            result = ssh_exec(command)
            output = result["stdout"] or result["stderr"] or "(no output)"
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": output}],
                    "isError": bool(result["stderr"] and not result["stdout"])
                }
            }

        return {
            "jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
        }

    # Notifications (no id) — no response needed
    if msg_id is None:
        return None

    return {
        "jsonrpc": "2.0", "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }


def main():
    logging.info("mcp_bridge starting on stdio transport.")
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            msg = json.loads(raw_line)
        except json.JSONDecodeError as e:
            logging.warning("Bad JSON: %s", e)
            continue

        response = handle_message(msg)
        if response is not None:
            print(json.dumps(response), flush=True)


if __name__ == "__main__":
    main()
