"""Send one Python snippet to the 'MCP for Blender' addon on localhost:9876.

Usage (Blender open, addon connected):
    python assets/avatar/source/blender_bridge.py "print(gp.build_all())"

The snippet runs inside the open Blender; `gp` is build_grandpa_avatar,
freshly reloaded from this folder, and `json` is imported. print() output
comes back here. Only talks to 127.0.0.1.
"""

import json
import socket
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRELUDE = f"""
import importlib, sys, json
sys.path.insert(0, {str(HERE)!r})
import build_grandpa_avatar as gp
importlib.reload(gp)
"""


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    code = PRELUDE + sys.argv[1]
    with socket.create_connection(("127.0.0.1", 9876), timeout=170) as s:
        s.sendall(
            json.dumps({"type": "execute_code", "params": {"code": code}}).encode()
        )
        buf = b""
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            try:
                reply = json.loads(buf.decode())
                break
            except ValueError:
                continue
    print(json.dumps(reply, indent=1))
    return 0 if reply.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
