"""Record how an eval run was produced, and refuse to mix two setups in one results file.

Runs resume: questions already in the output file are skipped. Without a check, stopping a v1
run halfway and resuming into the same file with v2 would leave a file that is half one prompt
and half the other, and nothing in it would show that.

So every results file gets a manifest next to it, written when the run starts. It has three
parts:

- identity: the settings that change the results. The prompt, the model and retrieval
  settings, the model and embedding model digests when the server reports them, the corpus,
  and a hash of the agent's own code, which includes the scorer. A resume must match it.
- questions: each question's id with a hash of its text, gold answer and supporting titles,
  in order. A resume must ask the same questions in the same order. It may ask for more or
  fewer, so a run can be extended, but the questions both lists have must be identical.
- info: useful but not enforced, like the git commit and when the run started. A docs-only
  commit shouldn't block a resume, which is why the code is checked by its hash.

What it can't see: a server that reports no digest can swap model weights behind the same
name. Then the digests are None and only the name is checked.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from signalfloor_agent.data import Passage, Question

DATASET = "hotpotqa/hotpot_qa distractor validation"
MANIFEST_VERSION = 2
# Digests the server may not report. None means unknown, so it can't be checked.
_DIGESTS = {"model_digest", "embedding_model_digest"}
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


def question_fingerprints(questions: Iterable[Question]) -> list[list[str]]:
    """Each question's id with a short hash of everything the score depends on."""
    return [
        [q.id, sha256("\0".join([q.question, q.answer, *q.supporting_titles]))[:16]]
        for q in questions
    ]


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
    out: Path,
    identity: Mapping[str, Any],
    info: Mapping[str, Any] | None = None,
    questions: Sequence[Sequence[str]] = (),
) -> None:
    """Write the manifest for a new run, or check that a resumed run has the same setup.

    questions comes from question_fingerprints. On a resume that asks for more questions, the
    manifest is rewritten with the longer list.
    """
    path = manifest_path(out)
    has_results = out.exists() and out.read_text(encoding="utf-8").strip() != ""
    current = [list(q) for q in questions]

    if not has_results:
        out.parent.mkdir(parents=True, exist_ok=True)
        _write(
            path,
            {
                "manifest_version": MANIFEST_VERSION,
                "identity": dict(identity),
                "questions": current,
                "info": {"created_at": datetime.now(UTC).isoformat(), **(info or {})},
            },
        )
        return

    if not path.exists():
        raise ManifestMismatch(
            f"{out} already has results but no manifest, so there's no way to check they came "
            "from this setup. Write this run to a new file."
        )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise ManifestMismatch(
            f"{out} was written by an older signalfloor-agent, which did not record the "
            "questions or the model digests. Write this run to a new file."
        )
    saved = manifest["identity"]
    changed = sorted(
        k
        for k in saved.keys() | identity.keys()
        if saved.get(k) != identity.get(k) and not (k in _DIGESTS and saved.get(k) is None)
    )
    if changed:
        lines = [f"  {k}: {saved.get(k)!r} before, {identity.get(k)!r} now" for k in changed]
        raise ManifestMismatch(
            f"{out} was started with a different setup. Resuming would mix two setups in one "
            "file:\n" + "\n".join(lines) + "\nWrite this run to a new file, or undo the change."
        )

    before = manifest.get("questions", [])
    for position, (old, new) in enumerate(zip(before, current, strict=False), start=1):
        if old != new:
            what = "a different question" if old[0] != new[0] else "the same id with changes"
            raise ManifestMismatch(
                f"{out} was started with other questions. Question {position} was {old[0]!r} "
                f"and is now {what} ({new[0]!r}): its text, gold answer or supporting facts "
                "differ. Write this run to a new file."
            )
    if len(current) > len(before):
        _write(path, {**manifest, "questions": current})


def _write(path: Path, manifest: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
