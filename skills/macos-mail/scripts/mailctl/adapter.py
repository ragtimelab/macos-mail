from __future__ import annotations

import os
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path

from .core import canonical_hash, sha256_file


MAX_COMPILED_ADAPTERS = 8


@contextmanager
def _compile_lock(cache: Path):
    """Serialize cache misses without holding a lock while an adapter executes."""
    import fcntl

    lock_path = cache / ".compile.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    handle = None
    try:
        handle = os.fdopen(descriptor, "a+")
        descriptor = -1
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        if handle is not None:
            handle.close()
        elif descriptor >= 0:
            os.close(descriptor)


def _prune_cache(cache: Path, keep: Path) -> None:
    """Bound stale compiled artifacts only after a successful cache miss."""
    try:
        artifacts = sorted(cache.glob("*.scpt"), key=lambda item: item.stat().st_mtime, reverse=True)
    except OSError:
        return
    retained = set(artifacts[:MAX_COMPILED_ADAPTERS]) | {keep}
    for artifact in artifacts:
        if artifact not in retained:
            try:
                artifact.unlink()
            except OSError:
                continue


def compiled_adapter(source: Path, sdef: Path, state_root: Path, timeout: int) -> Path:
    key = canonical_hash(
        {
            "source_sha256": sha256_file(source),
            "sdef_sha256": sha256_file(sdef),
        }
    )
    cache = state_root / "adapter-cache"
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(cache, 0o700)
    output = cache / f"{key}.scpt"
    if output.is_file():
        return output
    with _compile_lock(cache):
        if output.is_file():
            return output
        temporary = cache / f".{key}.{uuid.uuid4().hex}.tmp.scpt"
        result = subprocess.run(
            ["/usr/bin/osacompile", "-o", str(temporary), str(source)],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(result.stderr.strip() or "osacompile failed")
        os.chmod(temporary, 0o600)
        os.replace(temporary, output)
        _prune_cache(cache, output)
    return output
