"""Scoped, stateless localization without requiring an unpublished companion release."""
import csv
from datetime import date
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext, CallNext
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams
from pydantic import ValidationError

Language = Literal["en", "ru", "de", "es", "zh"]
LANGUAGES = ("en", "ru", "de", "es", "zh")
SCOPED_TOOLS = {"planner_forecast", "planner_compare_modes", "planner_export_report", "client_create",
                "client_get", "client_list", "client_update", "client_set_tax_residency",
                "client_get_tax_residency"}


@lru_cache
def captions(language: str) -> dict[str, str]:
    """Load complete packaged captions, rejecting unsupported languages."""
    if language not in LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    with files("okama_mcp").joinpath("planner_terminology.csv").open(encoding="utf-8", newline="") as source:
        return {row["key"]: row[language] for row in csv.DictReader(source)}


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
    """Hide validation input values and translate known messages without guessing."""
    from okama_planner import localization
    helper = getattr(localization, "localized_error", None)
    if isinstance(error, ValidationError):
        messages = []
        for item in error.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in item["loc"])
            known_message = item["msg"].removeprefix("Value error, ")
            message = caption(known_message if known_message in captions(language) else item["type"], language)
            if message == item["type"]:
                message = caption("invalid", language)
            messages.append(f"{location}: {message}")
        return "; ".join(messages)
    if str(error) in captions(language):
        return caption(str(error), language)
    if callable(helper):
        return helper(error, language)
    # Unknown runtime messages may contain personal data; keep only known field names.
    fields = [key for key in captions("en") if key.isidentifier() and key in str(error)]
    return f"{caption('invalid', language)}: {', '.join(fields)}" if fields else caption("invalid", language)


class PlannerLanguageMiddleware(Middleware):
    """Localize only Planner/registry errors, including pre-body argument validation."""
    async def on_call_tool(
        self, context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        arguments = context.message.arguments or {}
        language = arguments.get("language", "en")
        if context.message.name == "planner_export_report":
            report = arguments.get("report")
            if isinstance(report, dict):
                language = report.get("language", "en")
        if context.message.name not in SCOPED_TOOLS or language == "en" or language not in LANGUAGES:
            return await call_next(context)
        try:
            return await call_next(context)
        except Exception as error:
            cause = error
            seen = set()
            while cause.__cause__ is not None and id(cause) not in seen:
                seen.add(id(cause))
                cause = cause.__cause__
            raise ToolError(localize_error(cause, language)) from None


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
    if not any(isinstance(item, PlannerLanguageMiddleware) for item in mcp.middleware):
        mcp.add_middleware(PlannerLanguageMiddleware())


def present_residency(record: dict[str, Any] | None, language: str) -> dict[str, Any] | None:
    """Preserve absent years and raw residency identifiers."""
    if record is None or language == "en":
        return record
    return {"residency": record, "presentation": presentation(record, language)}


def register_tool(mcp: Any, function: Any, name: str, language: str) -> None:
    """Register an independent tool schema using the public FunctionTool API."""
    from fastmcp.tools.function_tool import FunctionTool
    tool = FunctionTool.from_function(function, name=name, description=function.__doc__)
    configure_tool(tool, name, language)
    mcp.add_tool(tool)
