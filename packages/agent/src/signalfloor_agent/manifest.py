"""Record how an eval run was produced, and refuse to mix two setups in one results file.

Runs resume: questions already in the output file are skipped. Without a check, stopping a v1
run halfway and resuming into the same file with v2 would leave a file that is half one prompt
and half the other, and nothing in it would show that.

So every results file gets a manifest next to it, written when the run starts. It has two
parts:

- identity: everything that changes the results. The prompt, the model and retrieval
  settings, which questions and corpus, and a hash of the agent's own code, which includes the
  scorer. A resume must match it exactly.
- info: useful but not enforced, like the git commit, the model's digest when the server
  reports one, and when the run started. A docs-only commit shouldn't block a resume, which is
  why the code is checked by its hash, not by commit.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from signalfloor_agent.data import Passage

DATASET = "hotpotqa/hotpot_qa distractor validation"
MANIFEST_VERSION = 1
_PACKAGE = Path(__file__).parent
# Test helpers live in the package but never run during an eval.
_NOT_EVAL_CODE = {"testing.py"}


class ManifestMismatch(ValueError):
    pass


def manifest_path(out: Path) -> Path:
    return out.with_suffix(".manifest.json")


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def corpus_hash(corpus: Iterable[Passage]) -> str:
    return sha256("\n".join(f"{p.title}\0{p.text}" for p in corpus))


def code_hash(package: Path = _PACKAGE) -> str:
    """A hash of the agent's source files, so any change to its behavior shows up."""
    digest = hashlib.sha256()
    for path in sorted(package.glob("*.py")):
        if path.name in _NOT_EVAL_CODE:
            continue
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_PACKAGE,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def model_digest(model: str, base_url: str, client: httpx.Client | None = None) -> str | None:
    """The model's digest from an Ollama server, or None for servers that don't report one."""
    root = base_url.removesuffix("/").removesuffix("/v1")
    try:
        with client or httpx.Client(timeout=5) as http:
            response = http.get(f"{root}/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    for entry in models:
        if isinstance(entry, dict) and model in (entry.get("name"), entry.get("model")):
            digest = entry.get("digest")
            return str(digest) if digest else None
    return None


def check_or_write(
    out: Path, identity: Mapping[str, Any], info: Mapping[str, Any] | None = None
) -> None:
    """Write the manifest for a new run, or check that a resumed run has the same identity."""
    path = manifest_path(out)
    has_results = out.exists() and out.read_text(encoding="utf-8").strip() != ""

    if not has_results:
        out.parent.mkdir(parents=True, exist_ok=True)
        manifest = {
            "manifest_version": MANIFEST_VERSION,
            "identity": dict(identity),
            "info": {"created_at": datetime.now(UTC).isoformat(), **(info or {})},
        }
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return

    if not path.exists():
        raise ManifestMismatch(
            f"{out} already has results but no manifest, so there's no way to check they came "
            "from this setup. Write this run to a new file."
        )
    saved = json.loads(path.read_text(encoding="utf-8"))["identity"]
    changed = sorted(k for k in saved.keys() | identity.keys() if saved.get(k) != identity.get(k))
    if changed:
        lines = [f"  {k}: {saved.get(k)!r} before, {identity.get(k)!r} now" for k in changed]
        raise ManifestMismatch(
            f"{out} was started with a different setup. Resuming would mix two setups in one "
            "file:\n" + "\n".join(lines) + "\nWrite this run to a new file, or undo the change."
        )
