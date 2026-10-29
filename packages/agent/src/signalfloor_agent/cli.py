"""Command line entry point: `signalfloor-agent eval`.

Example, two prompt versions compared with signalfloor:

    signalfloor-agent eval --questions 100 --prompt v1 --out runs/v1.jsonl
    signalfloor-agent eval --questions 100 --prompt v2 --out runs/v2.jsonl
    signalfloor compare runs/v1.jsonl runs/v2.jsonl
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import httpx
import openai

from signalfloor_agent import manifest, tracing
from signalfloor_agent.agent import PROMPTS, Agent, AgentConfig, openai_compatible_chat_model
from signalfloor_agent.data import Dataset, default_cache_dir, load_hotpot
from signalfloor_agent.embeddings import NOMIC_PREFIXES, OpenAICompatibleEmbedder
from signalfloor_agent.evaluate import run_eval, summarize
from signalfloor_agent.retrieval import (
    DenseRetriever,
    HybridRetriever,
    KeywordRetriever,
    Retriever,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="signalfloor-agent")
    commands = parser.add_subparsers(required=True)

    ev = commands.add_parser("eval", help="run the agent on HotpotQA and write a results file")
    ev.add_argument("--out", type=Path, required=True, help="results file to write or resume")
    ev.add_argument("--questions", type=int, default=100, help="how many questions (default 100)")
    ev.add_argument("--offset", type=int, default=0, help="first question to use (default 0)")
    ev.add_argument(
        "--corpus-questions",
        type=int,
        default=200,
        help="passages from this many questions form the search corpus (default 200)",
    )
    ev.add_argument("--prompt", choices=sorted(PROMPTS), default="v1")
    ev.add_argument("--retriever", choices=["dense", "keyword", "hybrid"], default="dense")
    ev.add_argument("--max-searches", type=int, default=4)
    ev.add_argument("--passages", type=int, default=4, help="passages per search (default 4)")
    ev.add_argument("--model", default="qwen3:1.7b")
    ev.add_argument("--embedding-model", default="nomic-embed-text")
    ev.add_argument("--base-url", default="http://localhost:11434/v1")
    ev.add_argument(
        "--otlp-endpoint",
        help="send OpenTelemetry traces here, e.g. http://localhost:8000/v1/traces",
    )
    ev.add_argument("--quiet", action="store_true", help="do not print each question")
    ev.set_defaults(handler=_run_eval)

    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except ValueError as e:
        print(f"signalfloor-agent: error: {e}", file=sys.stderr)
        return 2
    except (openai.APIConnectionError, httpx.ConnectError):
        # One clear line instead of a hundred lines of traceback from inside LangChain.
        print(
            f"signalfloor-agent: error: can't reach the model server at {args.base_url}. "
            "Is Ollama running? Results so far are saved, and running the same command again "
            "resumes.",
            file=sys.stderr,
        )
        return 1


def _run_eval(args: argparse.Namespace) -> int:
    if args.questions > args.corpus_questions:
        raise ValueError("--questions cannot be more than --corpus-questions")

    dataset = load_hotpot(args.corpus_questions, offset=args.offset)
    questions = dataset.questions[: args.questions]
    # Before any work, so a mismatched resume fails at once instead of after building indexes.
    manifest.check_or_write(
        args.out,
        run_identity(args, dataset),
        {"git_commit": manifest.git_commit()},
        manifest.question_fingerprints(questions),
    )
    agent = build_agent(args, dataset)

    provider = tracing.configure(args.otlp_endpoint) if args.otlp_endpoint else None
    try:
        results = run_eval(agent, questions, args.out, progress=None if args.quiet else print)
    finally:
        if provider:
            # Spans are sent in batches. Shutting down sends the last batch.
            provider.shutdown()
    s = summarize(results)
    print(
        f"\ncases {s.cases}  f1 {s.mean_f1:.3f}  exact match {s.mean_exact_match:.3f}  "
        f"searches {s.mean_searches:.2f}  supporting recall {s.mean_supporting_recall:.3f}  "
        f"hit search limit {s.hit_search_limit}  time {s.total_seconds / 60:.1f} min"
    )
    print(f"results in {args.out}")
    return 0


def run_identity(args: argparse.Namespace, dataset: Dataset) -> dict[str, object]:
    """The settings that change the results of a run. See manifest.py.

    The questions are checked separately, so a run can be extended with more questions from
    the same offset.
    """
    dense = args.retriever != "keyword"
    return {
        "prompt": args.prompt,
        "prompt_sha256": manifest.sha256(PROMPTS[args.prompt]),
        "model": args.model,
        "model_digest": manifest.model_digest(args.model, args.base_url),
        "base_url": args.base_url,
        "retriever": args.retriever,
        "embedding_model": args.embedding_model if dense else None,
        "embedding_model_digest": (
            manifest.model_digest(args.embedding_model, args.base_url) if dense else None
        ),
        "max_searches": args.max_searches,
        "passages_per_search": args.passages,
        "dataset": manifest.DATASET,
        "offset": args.offset,
        "corpus_questions": args.corpus_questions,
        "corpus_sha256": manifest.corpus_hash(dataset.corpus),
        "code_sha256": manifest.code_hash(),
    }


def build_agent(args: argparse.Namespace, dataset: Dataset) -> Agent:
    config = AgentConfig(
        max_searches=args.max_searches,
        passages_per_search=args.passages,
        system_prompt=PROMPTS[args.prompt],
    )
    model = openai_compatible_chat_model(args.model, base_url=args.base_url)
    return Agent(model, build_retriever(args, dataset), config)


def build_retriever(args: argparse.Namespace, dataset: Dataset) -> Retriever:
    keyword = KeywordRetriever(dataset.corpus)
    if args.retriever == "keyword":
        return keyword
    nomic = args.embedding_model.startswith("nomic-embed")
    embedder = OpenAICompatibleEmbedder(
        args.embedding_model,
        base_url=args.base_url,
        document_prefix=NOMIC_PREFIXES["document_prefix"] if nomic else "",
        query_prefix=NOMIC_PREFIXES["query_prefix"] if nomic else "",
        # New weights under the same name must not reuse cached vectors.
        revision=manifest.model_digest(args.embedding_model, args.base_url),
    )
    dense = DenseRetriever(dataset.corpus, embedder, cache_dir=default_cache_dir())
    return dense if args.retriever == "dense" else HybridRetriever(keyword, dense)
