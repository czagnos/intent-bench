"""Prepare the configured catalog embeddings before a live demo."""
from collections.abc import Sequence

import httpx

from reindex import execute_index, index_arguments
from app.config import Settings
from app.retrieval import Retriever


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None,
         transport: httpx.BaseTransport | None = None) -> int:
    arguments = index_arguments("Load the persistent catalog index, or build it once when absent (may use model inference).", argv)
    return execute_index(arguments, Retriever.prepare_index, settings, transport)


if __name__ == "__main__":
    raise SystemExit(main())
