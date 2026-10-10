"""Scoped, stateless localization without requiring an unpublished companion release."""
import csv
from datetime import date
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal
from string import Formatter

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext, CallNext
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams
from fastmcp.tools.function_tool import FunctionTool

Language = Literal["en", "ru", "de", "es", "zh"]
LANGUAGES = ("en", "ru", "de", "es", "zh")
SCOPED_TOOLS = {"planner_forecast", "planner_compare_modes", "planner_export_report", "client_create",
                "client_get", "client_list", "client_update", "client_set_tax_residency",
                "client_get_tax_residency", "client_save_plan", "client_load_plan", "client_list_plans", "client_forecast"}


@lru_cache
def captions(language: str) -> dict[str, str]:
    """Load complete packaged captions, rejecting unsupported languages."""
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    with files("okama_mcp").joinpath("planner_terminology.csv").open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    seen = set()
    for row in rows:
        key = row.get("key")
        if not key or key in seen:
            raise ValueError("Missing or duplicate localization key")
        seen.add(key)
        expected = None
        for code in LANGUAGES:
            value = row.get(code)
            if not value or not value.strip():
                raise ValueError(f"Missing {code} localization caption: {key}")
            placeholders = {field for _, field, _, _ in Formatter().parse(value) if field is not None}
            if expected is None:
                expected = placeholders
            elif placeholders != expected:
                raise ValueError(f"Inconsistent {code} localization placeholders: {key}")
    return {row["key"]: row[language] for row in rows}


def caption(key: str, language: str) -> str:
    """Translate only known captions; never replace substrings in user data."""
    return captions(language).get(key, key)


def presentation(record: dict[str, Any], language: str) -> list[dict[str, Any]]:
    """Keep a raw record alongside human captions, dates and enum labels."""
    from okama_planner import localization
    helper = getattr(localization, "client_presentation", None)
    if callable(helper):
        return helper(record, language)
    rows = []
    for key, value in record.items():
        if key in {"sex", "primary_channel"} and value is not None:
            value = caption(value, language)
        if key in {"ips_sent_at", "created_at", "updated_at"} and value:
            timestamp = str(value)
            parsed = date.fromisoformat(timestamp[:10])
            patterns = {"ru": "%d.%m.%Y", "de": "%d.%m.%Y", "es": "%d/%m/%Y", "zh": "%Y年%m月%d日"}
            value = (f"{parsed.year}年{parsed.month}月{parsed.day}日" if language == "zh"
                     else parsed.strftime(patterns.get(language, "%m/%d/%Y")))
            if key != "ips_sent_at":
                value += f" {timestamp[11:]}"
        rows.append({"key": key, "label": caption(key, language), "value": value})
    return rows


def present_client(record: dict[str, Any], language: str) -> dict[str, Any]:
    """Preserve the legacy English shape; non-English calls explicitly add presentation."""
    if language == "en":
        return record
    return {"client": record, "presentation": presentation(record, language)}


def localize_error(error: Exception, language: str) -> str:
    """Return only a fixed caption; never inspect exception text or field names."""
    language = language if language in LANGUAGES else "en"
    return caption("invalid", language)


def request_language(arguments: dict[str, Any]) -> str:
    """Read a supported language without echoing an arbitrary argument."""
    language = arguments.get("language", "en")
    report = arguments.get("report")
    if isinstance(report, dict):
        language = report.get("language", language)
    return language if isinstance(language, str) and language in LANGUAGES else "en"


class SafePlannerTool(FunctionTool):
    """Sanitize validation and body errors before FastMCP can log their details."""
    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            return await super().run(arguments)
        except Exception:
            raise ToolError(caption("invalid", request_language(arguments))) from None


class PlannerLanguageMiddleware(Middleware):
    """Sanitize every Planner/registry error, including English and invalid languages."""
    async def on_call_tool(
        self, context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        if context.message.name not in SCOPED_TOOLS:
            return await call_next(context)
        try:
            return await call_next(context)
        except Exception:
            raise ToolError(caption("invalid", request_language(context.message.arguments or {}))) from None


def configure_tool(tool: Any, name: str, language: str) -> None:
    """Overlay JSON-schema captions on this tool only; companion models stay untouched."""
    import copy
    captions(language)
    tool.parameters = copy.deepcopy(tool.parameters)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, field in node.get("properties", {}).items():
                if key in captions(language) and isinstance(field, dict):
                    field["description"] = caption(key, language)
                    field["title"] = caption(key, language)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    # Preserve the exact default schema, except for the new explicit language argument.
    if language != "en":
        visit(tool.parameters)
        tool.description = caption(name, language)
    if "language" in tool.parameters.get("properties", {}):
        tool.parameters["properties"]["language"]["description"] = caption("language", language)


def install_middleware(mcp: Any) -> None:
    """Install one scoped middleware for independently registered optional tools."""
    mcp._mask_error_details = True
    if not any(isinstance(item, PlannerLanguageMiddleware) for item in mcp.middleware):
        mcp.add_middleware(PlannerLanguageMiddleware())


def present_residency(record: dict[str, Any] | None, language: str) -> dict[str, Any] | None:
    """Preserve absent years and raw residency identifiers."""
    if record is None or language == "en":
        return record
    return {"residency": record, "presentation": presentation(record, language)}


def register_tool(mcp: Any, function: Any, name: str, language: str) -> None:
    """Register an independent tool schema using the public FunctionTool API."""
    tool = SafePlannerTool.from_function(function, name=name, description=function.__doc__)
    configure_tool(tool, name, language)
    mcp.add_tool(tool)
