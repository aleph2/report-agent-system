"""Lazy, local multilingual embeddings. Only model files are downloaded."""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path
from threading import RLock

MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
MODEL_REPO = "Qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q"
MODEL_REVISION = "faf4aa4225822f3bc6376869cb1164e8e3feedd0"
MODEL_SHA256 = "634d0f66c29dc934c8fa72b8a4fe91dd4d420a22f1d82a241058d4316e659a99"
_LOCK = RLock()


@lru_cache(maxsize=2)
def _load(cache_dir: str, local_only: bool = False):
    from fastembed import TextEmbedding
    from huggingface_hub import snapshot_download

    from huggingface_hub.errors import LocalEntryNotFoundError

    options = dict(repo_id=MODEL_REPO, revision=MODEL_REVISION, cache_dir=cache_dir,
                   allow_patterns=["*.json", "*.txt", "*.model", "model_optimized.onnx"], max_workers=1)
    try:
        path = snapshot_download(**options, local_files_only=True)
    except LocalEntryNotFoundError:
        if local_only:
            raise
        path = snapshot_download(**options)
    with (Path(path) / "model_optimized.onnx").open("rb") as model_file:
        if hashlib.file_digest(model_file, "sha256").hexdigest() != MODEL_SHA256:
            raise RuntimeError("LOCAL_EMBEDDING_MODEL_CHECKSUM_MISMATCH")
    return TextEmbedding(
        model_name=MODEL_NAME, specific_model_path=path, threads=2,
        providers=["CPUExecutionProvider"], local_files_only=True,
    )


class LocalEmbedding:
    """One pinned 384-dimensional ONNX model shared by local callers.

    Full facts remain in Neo4j. The model indexes at most its first 512 tokens;
    retrieval is candidate discovery, never a claim of complete source coverage.
    """

    model_id = f"{MODEL_REPO}@{MODEL_REVISION}"
    dimensions = 384
    coverage_note = "First 512 model tokens of title + body; full text remains readable."

    def __init__(self, cache_dir: str | None = None, *, local_only: bool = False):
        self.local_only = local_only
        self.cache_dir = cache_dir or os.environ.get(
            "REPORT_EMBEDDING_CACHE", str(Path.home() / ".cache/report-agent-system/embeddings")
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        with _LOCK:
            model = _load(self.cache_dir, self.local_only)
            return [row.tolist() for row in model.embed(texts, batch_size=8, parallel=None)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]

    def describe(self) -> dict:
        return {"model": MODEL_NAME, "model_id": self.model_id,
                "dimensions": self.dimensions, "local": True,
                "coverage_note": self.coverage_note}
