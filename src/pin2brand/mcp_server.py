"""MCP server exposing Pin2Brand to coding and creative AI agents with input sandboxing."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp < 2.0 fallback
    from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore[no-redef]

from .exporter import run_pin2brand_pipeline

mcp = MCPServer("pin2brand")


def validate_mcp_request(board_url: str, output_dir: str) -> Path:
    """Enforce security boundaries on MCP tool arguments (prevent path traversal & arbitrary local dir scans)."""
    raw_url = board_url.strip()
    allow_local = os.getenv("PIN2BRAND_MCP_ALLOW_LOCAL_DIRS", "").strip() == "1"

    if raw_url.startswith(("http://", "https://")):
        parsed = urlparse(raw_url)
        if "pinterest." not in parsed.netloc.lower():
            raise ValueError(
                f"MCP only permits Pinterest board URLs (got host '{parsed.netloc}')."
            )
    else:
        if not allow_local:
            raise ValueError(
                "Local directory scanning via MCP is disabled by default for security. "
                "Pass an https://pinterest.com/<user>/<board>/ URL or set PIN2BRAND_MCP_ALLOW_LOCAL_DIRS=1."
            )

    workspace_root = Path(os.getenv("PIN2BRAND_MCP_WORKSPACE_ROOT", str(Path.cwd()))).resolve()
    candidate_out = Path(output_dir)
    resolved_out = (
        candidate_out.resolve()
        if candidate_out.is_absolute()
        else (workspace_root / candidate_out).resolve()
    )
    if not resolved_out.is_relative_to(workspace_root):
        raise ValueError(
            f"Path traversal blocked: output_dir '{output_dir}' resolves outside workspace root '{workspace_root}'."
        )
    return resolved_out


@mcp.tool()
async def extract_pinterest_visual_identity(
    board_url: str,
    max_pins: int = 20,
    provider: str = "auto",
    offline: bool = False,
    output_dir: str = "output",
) -> dict[str, Any]:
    """Extract a Pinterest board's CIELAB color system, UI rules, W3C tokens, and generative prompts.

    Returns the generated artifact paths and the full VisualIdentityManifest dictionary.
    """
    safe_output_root = validate_mcp_request(board_url=board_url, output_dir=output_dir)
    result = await run_pin2brand_pipeline(
        board_url=board_url,
        output_root=safe_output_root,
        max_pins=max_pins,
        force_offline=offline,
        provider=provider,
    )
    return {
        "project_name": result["manifest"].project_name,
        "source_method": result["board"].source_method,
        "synthesis_mode": result["synthesis_mode"],
        "pins_downloaded": len(result["board"].pins),
        "output_dir": str(result["output_dir"].resolve()),
        "artifacts": {k: str(v.resolve()) for k, v in result["artifacts"].items()},
        "visual_identity": result["manifest"].model_dump(),
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
