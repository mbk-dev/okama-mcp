"""Install the distributed generic client workflow in a user's project skill directory."""
from pathlib import Path


def install_skill(destination: Path) -> Path:
    """Install once, accept identical content and refuse to overwrite custom instructions."""
    relative = Path(".agents/skills/create-client/SKILL.md")
    source = Path(__file__).resolve().parents[1] / relative
    if not source.is_file():
        # Poetry editable source layout, used by repository development installations.
        source = Path(__file__).resolve().parents[2] / relative
    content = source.read_bytes()
    directory = destination / "create-client"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "SKILL.md"
    if target.exists():
        if target.read_bytes() != content:
            raise FileExistsError(f"Skill already exists with different content: {target}")
        return target
    with target.open("xb") as stream:
        stream.write(content)
    return target
