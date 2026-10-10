"""Local report export delegates calculations and workbook rendering to Planner."""
import os
from pathlib import Path
from typing import Any
from uuid import uuid4
from fastmcp import FastMCP
from okama_mcp.schemas import PlannerReportSpec
from okama_mcp.planner_localization import Language, register_tool, install_middleware


def register(mcp: FastMCP, output_dir: Path, brand_path: Path | None = None, language: Language = "en") -> None:
    """Enable only anonymous export into an explicitly selected local directory."""
    install_middleware(mcp)
    from okama_planner.ai import export_report
    if not output_dir.is_absolute() or not output_dir.is_dir():
        raise ValueError("--reports-dir must be an absolute existing directory")
    output_dir = output_dir.resolve()
    # Keep the startup argument compatible, but never read private brand files in MCP.
    # Named/ branded client deliverables belong to Planner's human interface.

    def planner_export_report(report: PlannerReportSpec) -> dict[str, Any]:
        """Export saved household request/result pairs as a local Excel workbook.
        No forecasts are rerun. Filename must be a new .xlsx basename; local branding
        is configured by the server. Requires the Planner reports companion extra.
        """
        filename = report.filename
        if not filename or "/" in filename or "\\" in filename or not filename.endswith(".xlsx"):
            raise ValueError("filename must be a .xlsx basename within --reports-dir")
        filename = f"report-{uuid4().hex}.xlsx"
        target = output_dir / filename
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            export_report([s.model_dump() for s in report.scenarios], target,
                          language=report.language)
        except BaseException:
            target.unlink()
            raise
        return {"filename": filename, "language": report.language, "scenarios": len(report.scenarios)}

    register_tool(mcp, planner_export_report, "planner_export_report", language)
