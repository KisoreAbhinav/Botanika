#!/usr/bin/env python3
"""Measure an already-installed quantized local LLM without network access."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import resource
import sys
import time
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SOURCE = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

from botanika.core.settings import AppSettings
from botanika.knowledge.llm import LocalLLM


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=AppSettings().llm_model_path)
    parser.add_argument("--backend", choices=("auto", "llama-cpp-python", "llama-cli"), default="auto")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.runs <= 0:
        raise SystemExit("--runs must be positive")
    llm = LocalLLM(
        args.model,
        backend=args.backend,
        context_tokens=2048,
        threads=4,
        batch_size=128,
        temperature=0.1,
        max_tokens=256,
        timeout_seconds=20,
    )
    initial = llm.status()
    if not initial.available:
        result = {
            "status": "blocked",
            "detail": initial.detail,
            "model": initial.to_dict(),
            "network": "not used",
        }
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    evidence = (
        SimpleNamespace(
            chunk_id="benchmark:chunk-1",
            content="Banyan is a reviewed example plant in the local benchmark evidence.",
        ),
    )
    samples: list[dict[str, object]] = []
    for index in range(args.runs):
        started = time.perf_counter()
        try:
            output = llm.generate("What is the benchmark plant?", evidence)
            error = None
        except Exception as exc:
            output = None
            error = str(exc)
        samples.append(
            {
                "run": index + 1,
                "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
                "grounded_output": bool(output),
                "error": error,
            }
        )
    latencies = [float(item["latency_ms"]) for item in samples]
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        "status": "ok" if all(item["grounded_output"] for item in samples) else "degraded",
        "host": {"platform": platform.platform(), "machine": platform.machine()},
        "settings": {"backend": args.backend, "threads": 4, "batch_size": 128, "context_tokens": 2048, "max_tokens": 256, "temperature": 0.1},
        "model": llm.status().to_dict(),
        "runs": samples,
        "latency_ms": {"min": min(latencies), "p50": sorted(latencies)[len(latencies) // 2], "max": max(latencies)},
        "max_rss_mb": round(float(usage.ru_maxrss) / 1024.0, 2),
        "network": "not used",
    }
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
