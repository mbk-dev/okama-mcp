"""Chart rendering helpers: matplotlib OO API only.

FastMCP executes sync tools in worker threads. matplotlib's stateful global
API is not thread-safe, so every figure here is built with the
object-oriented API (`Figure` + `FigureCanvasAgg`) and rendered to PNG bytes
in isolation. Default render size comes from the project spec: 10x6 in @
150 dpi = 1500x900 px; callers may request a custom pixel size / aspect
ratio within [MIN_PX, MAX_PX].
"""

from __future__ import annotations

import io

from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

FIGSIZE: tuple[float, float] = (10.0, 6.0)
DPI: int = 150
MIN_PX: int = 300
MAX_PX: int = 4000


def make_figure(width_px: int = 1500, height_px: int = 900) -> tuple[Figure, Axes]:
    """Create a Figure + single Axes; size given in pixels, rendered at fixed DPI.

    Defaults to the project standard 1500x900. MCP callers may request a custom
    size or aspect ratio within [MIN_PX, MAX_PX] on each side.
    """
    for name, value in (("width", width_px), ("height", height_px)):
        if not MIN_PX <= value <= MAX_PX:
            raise ValueError(
                f"{name} must be between {MIN_PX} and {MAX_PX} pixels, got {value}"
            )
    fig = Figure(figsize=(width_px / DPI, height_px / DPI), dpi=DPI)
    FigureCanvasAgg(fig)  # attach a canvas so the figure can render itself
    ax = fig.add_subplot(111)
    ax.grid(True, alpha=0.3)
    return fig, ax


def fig_to_png(fig: Figure) -> bytes:
    """Render the figure to PNG bytes at the figure's DPI."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI)
    return buf.getvalue()
