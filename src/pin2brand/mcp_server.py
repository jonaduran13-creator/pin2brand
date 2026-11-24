"""MCP server exposing Pin2Brand to coding and creative AI agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp < 2.0 fallback
    from mcp.server.fastmcp import FastMCP as MCPServer  # type: ignore[no-redef]

from .exporter import run_pin2brand_pipeline

mcp = MCPServer("pin2brand")


@mcp.tool()
async def extract_pinterest_visual_identity(
    board_url: str,
    max_pins: int = 20,
    provider: str = "auto",
    offline: bool = False,
    output_dir: str = "output",
) -> dict[str, Any]:
    """Extract a Pinterest board's (or local image folder's) CIELAB color system, UI rules, W3C tokens, and generative prompts.

    Returns the generated artifact paths and the full VisualIdentityManifest dictionary.
    """
    result = await run_pin2brand_pipeline(
        board_url=board_url,
        output_root=Path(output_dir),
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
