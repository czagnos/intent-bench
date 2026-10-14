"""Rebuild the complete persistent catalog embedding index."""
import argparse
import sqlite3
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))

from app.config import Settings
from app.providers import ModelUnavailable
from app.retrieval import Retriever
from app.service import Studio
from app.vector_index import IndexPreparation


@dataclass
class IndexArguments:
    workspace: str = "demo"
    embedding_id: str = "default"
    catalog_version: str | None = None
    representation: Literal["combined", "separate"] | None = None


class IndexSummary(IndexPreparation):
    workspace: str
    embedding_id: str
    model: str
    catalog_version: str
    representation: Literal["combined", "separate"]
    intent_count: int
    path: str


class IndexFailure(BaseModel):
    error: str


@dataclass(frozen=True)
class IndexTarget:
    arguments: IndexArguments
    settings: Settings
    retriever: Retriever

    def summary(self, preparation: IndexPreparation) -> IndexSummary:
        index = self.retriever.vector_index
        assert index is not None
        return IndexSummary(**preparation.model_dump(), workspace=self.arguments.workspace,
                            embedding_id=self.arguments.embedding_id, model=self.settings.embedding_model,
                            catalog_version=self.retriever.version,
                            representation=self.settings.retrieval_representation,
                            intent_count=len(self.retriever.intents), path=str(index.path.resolve()))


def index_arguments(description: str, argv: Sequence[str] | None) -> IndexArguments:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--workspace", default="demo", help="Existing workspace (default: demo).")
    parser.add_argument("--embedding-id", default="default", help="Embedding preset or registered model ID (default: default).")
    parser.add_argument("--catalog-version", help="Existing catalog snapshot; otherwise pin the active catalog.")
    parser.add_argument("--representation", choices=("combined", "separate"),
                        help="Document representation; otherwise use the server setting.")
    return parser.parse_args(argv, namespace=IndexArguments())


@contextmanager
def index_target(arguments: IndexArguments, settings: Settings | None = None,
                 transport: httpx.BaseTransport | None = None) -> Iterator[IndexTarget]:
    studio = Studio(settings or Settings())
    try:
        studio.embeddings.transport = transport
        catalog = studio.store.catalog(arguments.workspace, arguments.catalog_version)
        if catalog is None:
            raise ValueError("Çalışma alanı veya katalog sürümü bulunamadı; mevcut bir katalog seçin.")
        resolved = studio.model_catalog.resolve("embedding", arguments.embedding_id, workspace=arguments.workspace)
        if arguments.representation is not None:
            resolved.retrieval_representation = arguments.representation
        # Freeze the selected version before any embedding request can take place.
        retriever = studio.retriever(arguments.workspace, catalog["version"], resolved)
        yield IndexTarget(arguments, resolved, retriever)
    finally:
        studio.close()


def execute_index(arguments: IndexArguments, operation: Callable[[Retriever], IndexPreparation],
                  settings: Settings | None = None, transport: httpx.BaseTransport | None = None) -> int:
    try:
        with index_target(arguments, settings, transport) as target:
            print(target.summary(operation(target.retriever)).model_dump_json(indent=2))
    except ValidationError:
        print(IndexFailure(error="İndeks veya model ayarları geçersiz; yapılandırmayı kontrol edin.").model_dump_json(), file=sys.stderr)
        return 1
    except (ValueError, ModelUnavailable) as exc:
        print(IndexFailure(error=str(exc)).model_dump_json(), file=sys.stderr)
        return 1
    except (OSError, sqlite3.Error):
        print(IndexFailure(error="Yerel katalog veya indeks dosyası kullanılamıyor; veri dizinini ve izinlerini kontrol edin.").model_dump_json(), file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None,
         transport: httpx.BaseTransport | None = None) -> int:
    arguments = index_arguments("Rebuild every catalog embedding and atomically replace its persistent index (uses model inference).", argv)
    return execute_index(arguments, Retriever.rebuild_index, settings, transport)


if __name__ == "__main__":
    raise SystemExit(main())
