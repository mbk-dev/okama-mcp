"""Local MCP creation receipts; Planner owns all client validation and database writes."""
from contextlib import contextmanager
from collections.abc import Iterator
import hashlib
import json
import os
from pathlib import Path
from typing import Any


def _atomic_receipt(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(".new")
    descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(data, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _creation_lock(database: Path) -> Iterator[Path]:
    # POSIX locking is intentionally limited to explicitly configured local registry tools.
    import fcntl

    directory = database.with_name(database.name + ".mcp-receipts")
    directory.mkdir(mode=0o700, exist_ok=True)
    descriptor = os.open(directory / "lock", os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield directory
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def create_client(
    database: Path, details: dict[str, Any], request_id: str, allow_duplicate: bool = False,
) -> dict[str, Any]:
    """Persist once per request ID; unresolved interruption is never silently retried."""
    from okama_planner.storage import PlannerStore
    from okama_planner.storage.validation import ClientDetails

    if not request_id.strip() or len(request_id) > 200:
        raise ValueError("request_id must contain 1 to 200 characters; reuse it for retries")
    data = ClientDetails.model_validate(details).model_dump(mode="json")
    payload = {"details": data, "allow_duplicate": allow_duplicate}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    database = database.resolve(strict=True)
    with _creation_lock(database) as directory, PlannerStore.open(database) as store:
        receipt = directory / (hashlib.sha256(request_id.encode()).hexdigest() + ".json")
        if receipt.exists():
            saved = json.loads(receipt.read_text())
            if saved["digest"] != digest:
                raise ValueError("request_id was already used with different inputs")
            if saved["status"] == "pending":
                raise ValueError("Creation receipt is pending; use client_list/client_get to inspect before recovery. "
                                 "Do not repeat creation with a new request_id")
            return {"status": "replayed", "client": store.get_client(saved["code"])}
        name = " ".join(data["full_name"].split()).casefold()
        candidates = [row for row in store.list_clients()
                      if " ".join(row["full_name"].split()).casefold() == name]
        if candidates and not allow_duplicate:
            return {"status": "duplicate", "candidates": candidates}
        _atomic_receipt(receipt, {"digest": digest, "status": "pending"})
        client = store.create_client(data)
        _atomic_receipt(receipt, {"digest": digest, "status": "complete", "code": client["code"]})
        return {"status": "created", "client": client}
