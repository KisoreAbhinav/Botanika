"""Optional local llama.cpp adapter with a strict grounded prompt boundary.

The adapter is deliberately lazy.  A missing GGUF or llama runtime is a
reported capability state, not a reason to disable the deterministic
extractive guide.  Generated text is accepted only when it explicitly cites
retrieved chunk IDs, which keeps the default answer path safe on small or
poorly tuned local models.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Iterable


_CITATION_RE = re.compile(r"\[([A-Za-z0-9:._-]+)\]")


@dataclass(frozen=True, slots=True)
class LocalLLMStatus:
    available: bool
    backend: str
    model_path: str
    detail: str
    model_loaded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "backend": self.backend,
            "model_path": self.model_path,
            "detail": self.detail,
            "model_loaded": self.model_loaded,
        }


class LocalLLM:
    """Lazy local generator.  It never performs downloads or shell parsing."""

    def __init__(
        self,
        model_path: Path,
        *,
        backend: str = "auto",
        context_tokens: int = 2048,
        threads: int = 4,
        batch_size: int = 128,
        temperature: float = 0.1,
        max_tokens: int = 256,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.model_path = Path(model_path)
        self.backend = str(backend).lower()
        self.context_tokens = int(context_tokens)
        self.threads = int(threads)
        self.batch_size = int(batch_size)
        self.temperature = float(temperature)
        self.max_tokens = int(max_tokens)
        self.timeout_seconds = float(timeout_seconds)
        self._model: Any = None
        self._resolved_backend: str | None = None
        self._load_error: str | None = None

    def status(self, *, load: bool = False) -> LocalLLMStatus:
        if self.backend == "disabled":
            return LocalLLMStatus(False, "disabled", str(self.model_path), "Local generation is disabled.")
        if not self.model_path.is_file():
            return LocalLLMStatus(False, self._choose_backend(), str(self.model_path), f"Local GGUF model is unavailable: {self.model_path}")
        backend = self._resolved_backend or self._choose_backend()
        if backend == "unavailable":
            return LocalLLMStatus(
                False,
                backend,
                str(self.model_path),
                "No supported local llama.cpp runtime is installed.",
            )
        if load:
            try:
                self._ensure_loaded()
            except RuntimeError:
                pass
        if self._load_error:
            return LocalLLMStatus(False, self._resolved_backend or backend, str(self.model_path), self._load_error)
        return LocalLLMStatus(True, self._resolved_backend or backend, str(self.model_path), "Local model is available; generation remains evidence-gated.", self._model is not None)

    def generate(self, question: str, evidence: Iterable[Any]) -> str | None:
        hits = tuple(evidence)
        if not question.strip() or not hits:
            return None
        self._ensure_loaded()
        prompt = grounded_prompt(question, hits, self.context_tokens)
        if self._resolved_backend == "llama-cpp-python":
            response = self._model(
                prompt,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                stop=["\n\nQuestion:", "\nUser:"],
            )
            text = str(response.get("choices", [{}])[0].get("text", "")).strip()
        elif self._resolved_backend == "llama-cli":
            completed = subprocess.run(
                [
                    "llama-cli",
                    "-m", str(self.model_path),
                    "-c", str(self.context_tokens),
                    "-t", str(self.threads),
                    "-b", str(self.batch_size),
                    "--temp", str(self.temperature),
                    "-n", str(self.max_tokens),
                    "-p", prompt,
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError(completed.stderr.strip() or "llama-cli failed")
            text = completed.stdout.strip()
        else:  # pragma: no cover - defensive after _ensure_loaded
            return None
        allowed = {str(getattr(hit, "chunk_id", "")) for hit in hits if str(getattr(hit, "chunk_id", ""))}
        if not validate_grounded_output(text, allowed):
            return None
        return text

    def _choose_backend(self) -> str:
        if self.backend == "llama-cpp-python":
            return self.backend if importlib.util.find_spec("llama_cpp") is not None else "unavailable"
        if self.backend == "llama-cli":
            return self.backend if shutil.which("llama-cli") else "unavailable"
        if importlib.util.find_spec("llama_cpp") is not None:
            return "llama-cpp-python"
        if shutil.which("llama-cli"):
            return "llama-cli"
        return "unavailable"

    def _ensure_loaded(self) -> None:
        if self._model is not None or self._load_error:
            if self._load_error:
                raise RuntimeError(self._load_error)
            return
        if not self.model_path.is_file():
            self._load_error = f"Local GGUF model is unavailable: {self.model_path}"
            raise RuntimeError(self._load_error)
        backend = self._choose_backend()
        try:
            if backend == "llama-cpp-python":
                from llama_cpp import Llama

                self._model = Llama(
                    model_path=str(self.model_path),
                    n_ctx=self.context_tokens,
                    n_threads=self.threads,
                    n_batch=self.batch_size,
                    verbose=False,
                )
            elif backend == "llama-cli":
                self._model = object()
            else:
                raise RuntimeError("neither llama-cpp-python nor llama-cli is installed")
            self._resolved_backend = backend
        except Exception as exc:
            self._load_error = f"could not load local LLM: {exc}"
            raise RuntimeError(self._load_error) from exc


def grounded_prompt(question: str, evidence: Iterable[Any], context_tokens: int = 2048) -> str:
    """Build a short prompt that makes source boundaries visible to a model."""

    budget = max(512, int(context_tokens))
    lines = [
        "You are Botanika's offline botanical guide.",
        "Answer only from the evidence below. If it is insufficient, say so.",
        "Cite each factual statement with the exact chunk ID in square brackets.",
        "Do not invent species, locations, conservation status, or measurements.",
        "",
        "Evidence:",
    ]
    used = sum(len(item) for item in lines)
    for hit in evidence:
        chunk_id = str(getattr(hit, "chunk_id", ""))
        content = str(getattr(hit, "content", "")).strip()
        line = f"[{chunk_id}] {content}"
        if used + len(line) + 1 > budget * 3:
            break
        lines.append(line)
        used += len(line) + 1
    lines.extend(("", f"Question: {question.strip()}", "Answer:"))
    return "\n".join(lines)


def validate_grounded_output(text: str, allowed_chunk_ids: Iterable[str]) -> bool:
    """Accept generated wording only when every statement cites local evidence.

    Citation presence alone is insufficient: a model could append one valid
    chunk ID to a paragraph containing unrelated claims. We therefore reject
    empty output, unknown IDs, uncited lines, and uncited sentence fragments.
    The deterministic extractive answer remains the caller's fallback.
    """

    value = str(text or "").strip()
    if not value:
        return False
    allowed = {str(item) for item in allowed_chunk_ids if str(item)}
    citations = set(_CITATION_RE.findall(value))
    if not citations or not citations.issubset(allowed):
        return False
    for line in value.splitlines():
        statement = line.strip()
        if not statement:
            continue
        # Keep markdown bullets/numbering harmless, but require real text in
        # addition to the citation marker.
        without_citations = _CITATION_RE.sub("", statement).strip(" -*•\t")
        if not without_citations:
            return False
        fragments = _statement_fragments(statement)
        if any(not _CITATION_RE.search(fragment) for fragment in fragments):
            return False
    return True


def _statement_fragments(value: str) -> list[str]:
    """Split prose at sentence boundaries without splitting chunk IDs."""

    fragments: list[str] = []
    start = 0
    index = 0
    in_citation = False
    length = len(value)
    while index < length:
        character = value[index]
        if character == "[":
            in_citation = True
        elif character == "]":
            in_citation = False
        elif not in_citation and character in ".!?":
            cursor = index + 1
            while cursor < length and value[cursor] in "\"')":
                cursor += 1
            while cursor < length and value[cursor].isspace():
                cursor += 1
            citation_cursor = cursor
            while citation_cursor < length and value[citation_cursor] == "[":
                match = _CITATION_RE.match(value, citation_cursor)
                if match is None:
                    break
                citation_cursor = match.end()
                while citation_cursor < length and value[citation_cursor].isspace():
                    citation_cursor += 1
            if cursor < length:
                boundary = citation_cursor if citation_cursor != cursor else cursor
                fragments.append(value[start:boundary].strip())
                start = boundary
                index = boundary - 1
        index += 1
    tail = value[start:].strip()
    if tail:
        fragments.append(tail)
    return fragments


__all__ = ["LocalLLM", "LocalLLMStatus", "grounded_prompt", "validate_grounded_output"]
