"""The former personal-data intake skill is unavailable to AI clients."""
from pathlib import Path


def install_skill(destination: Path) -> Path:
    """Fail closed instead of installing the legacy personal-data workflow."""
    raise ValueError("Client intake is local human input in okama-planner; the AI intake skill is retired")
