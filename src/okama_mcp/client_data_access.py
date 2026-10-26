"""Persist MCP access policy beside the configured database, never inside its schema."""
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from okama_mcp.schemas import ClientDataAccessSettings, ClientDataMode


class PersonalDataAccessRequired(ValueError):
    """A fixed public error category with no client or filesystem details."""


class ClientDataAccess:
    """Read policy for every call so connections and server restarts share one setting."""

    def __init__(self, database: Path) -> None:
        database = database.resolve(strict=True)
        self.path = database.with_name(f"{database.name}.mcp-access.json")

    def get(self) -> ClientDataAccessSettings:
        """Default to anonymous only when no policy exists; corrupt policy fails closed."""
        try:
            content = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ClientDataAccessSettings(mode="anonymous")
        return ClientDataAccessSettings.model_validate_json(content)

    def set(self, mode: ClientDataMode, *, only_if_absent: bool = False) -> ClientDataAccessSettings:
        """Atomically replace an owner-only policy file; never store client data."""
        settings = ClientDataAccessSettings(mode=mode)
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                    prefix=f".{self.path.name}.", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(settings.model_dump_json())
                stream.flush()
                os.fsync(stream.fileno())
            if only_if_absent:
                try:
                    os.link(temporary, self.path)
                except FileExistsError:
                    return self.get()
            else:
                temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return settings
