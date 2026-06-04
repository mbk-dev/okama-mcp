"""Tests for rendering.py: OO-matplotlib figure factory and PNG export."""

import struct

import pytest

from okama_mcp.rendering import DPI, FIGSIZE, fig_to_png, make_figure

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _png_size(data: bytes) -> tuple[int, int]:
    # IHDR width/height are big-endian uint32 at offsets 16 and 20.
    return struct.unpack(">II", data[16:24])


class TestMakeFigure:
    def test_returns_figure_and_axes_with_project_defaults(self) -> None:
        fig, ax = make_figure()
        assert tuple(fig.get_size_inches()) == FIGSIZE
        assert fig.dpi == DPI
        assert ax.figure is fig

    def test_custom_pixel_size_sets_aspect_ratio(self) -> None:
        fig, _ = make_figure(width_px=1200, height_px=1200)  # square
        assert tuple(fig.get_size_inches()) == (8.0, 8.0)    # 1200 / 150 dpi

    def test_out_of_bounds_size_rejected(self) -> None:
        with pytest.raises(ValueError):
            make_figure(width_px=50, height_px=900)
        with pytest.raises(ValueError):
            make_figure(width_px=1500, height_px=10_000)

    def test_rendering_source_never_touches_pyplot(self) -> None:
        # okama itself imports pyplot eagerly, so checking sys.modules is useless.
        # The thread-safety contract is that OUR drawing code never goes through
        # the stateful global API — enforce it statically on the module source.
        import inspect

        import okama_mcp.rendering as rendering

        assert "pyplot" not in inspect.getsource(rendering)


class TestFigToPng:
    def test_png_bytes_with_correct_pixel_size(self) -> None:
        fig, ax = make_figure()
        ax.plot([1, 2, 3], [1, 4, 9])
        data = fig_to_png(fig)
        assert data.startswith(PNG_MAGIC)
        assert _png_size(data) == (1500, 900)
        assert len(data) > 5_000  # a real chart, not an empty stub

    def test_custom_size_renders_to_requested_pixels(self) -> None:
        fig, ax = make_figure(width_px=900, height_px=600)
        ax.plot([1, 2], [1, 2])
        assert _png_size(fig_to_png(fig)) == (900, 600)
