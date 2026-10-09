"""Prepare the repository-local directory for pytest's temporary fixtures."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Allow the configured tmp/pytest base to work in a fresh checkout."""
    (config.rootpath / "tmp").mkdir(exist_ok=True)
