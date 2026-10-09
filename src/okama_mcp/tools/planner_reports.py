"""Local report export delegates calculations and workbook rendering to Planner."""
import json
import os
from pathlib import Path
from typing import Any
from fastmcp import FastMCP
from okama_mcp.schemas import PlannerReportBrand, PlannerReportSpec


def register(mcp: FastMCP, output_dir: Path, brand_path: Path | None = None) -> None:
    """Enable only with an explicitly selected local directory and optional brand file."""
    from okama_planner.reports import ReportBrand, export_report
    if not output_dir.is_absolute() or not output_dir.is_dir():
        raise ValueError("--reports-dir must be an absolute existing directory")
    output_dir = output_dir.resolve()
    settings = PlannerReportBrand()
    if brand_path is not None:
        if not brand_path.is_absolute():
            raise ValueError("--report-brand must be absolute")
        settings = PlannerReportBrand.model_validate(json.loads(brand_path.read_text()))
    brand_data = settings.model_dump()
    if settings.logo:
        logo = Path(settings.logo)
        if not logo.is_absolute():
            logo = brand_path.parent / logo
        brand_data["logo"] = logo.resolve(strict=True)
    brand = ReportBrand(**brand_data)

    @mcp.tool
    def planner_export_report(report: PlannerReportSpec) -> dict[str, Any]:
        """Export saved household request/result pairs as a local Excel workbook.
        No forecasts are rerun. Filename must be a new .xlsx basename; local branding
        is configured by the server. Requires the Planner reports companion extra.
        """
        filename = report.filename
        if not filename or "/" in filename or "\\" in filename or not filename.endswith(".xlsx"):
            raise ValueError("filename must be a .xlsx basename within --reports-dir")
        target = output_dir / filename
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        try:
            export_report([s.model_dump() for s in report.scenarios], target,
                          brand=brand, language=report.language)
        except BaseException:
            target.unlink()
            raise
        return {"path": str(target), "language": report.language, "scenarios": len(report.scenarios)}
