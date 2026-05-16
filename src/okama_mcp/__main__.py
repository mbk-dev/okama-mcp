"""Allow `python -m okama_mcp <command>` execution."""

from __future__ import annotations

import sys

from okama_mcp.transport import main

if __name__ == "__main__":
    sys.exit(main())
