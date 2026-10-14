"""Versioned catalog vectors; no query text or authentication is stored here."""
from collections.abc import Callable, Iterator
from contextlib import contextmanager
import fcntl
from dataclasses import dataclass
import hashlib
import json
import os
import tempfile
from zipfile import BadZipFile
from pathlib import Path
from typing import Literal, NamedTuple
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field

from .contracts import Intent
from .providers import ModelUnavailable

VectorMatrix = NDArray[np.float32]
Representation = Literal["combined", "separate"]
IndexSource = Literal["memory", "disk", "built", "rebuilt"]


class CorpusRow(NamedTuple):
    intent_id: str
    evidence: str
    text: str


def build_corpus(intents: list[Intent], representation: Representation) -> list[CorpusRow]:
    if representation == "separate":
        return ([CorpusRow(i.intent_id, example, example) for i in intents for example in i.examples]
                + [CorpusRow(i.intent_id, i.description, f"{i.name}. {i.description}") for i in intents])
    return [CorpusRow(i.intent_id, example, f"{i.name}. {i.description} {example}")
            for i in intents for example in i.examples]


class IndexIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    schema_version: Literal[1] = 1
    text_version: Literal[1] = 1
    workspace: str
    catalog_version: str
    embedding_key: str
    representation: Representation
    corpus_sha256: str
    document_count: int = Field(ge=1)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


def make_identity(workspace: str, catalog_version: str, embedding_key: str,
                  representation: Representation, rows: list[CorpusRow]) -> IndexIdentity:
    corpus = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    return IndexIdentity(workspace=workspace, catalog_version=catalog_version,
                         embedding_key=embedding_key, representation=representation,
                         corpus_sha256=hashlib.sha256(corpus).hexdigest(), document_count=len(rows))


class IndexMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    identity: IndexIdentity
    generation: str = Field(min_length=1)
    dimensions: int = Field(ge=1)
    dtype: Literal["float32"] = "float32"


@dataclass(frozen=True)
class FileRevision:
    device: int
    inode: int
    size: int
    modified_ns: int

    @classmethod
    def from_stat(cls, stat: os.stat_result) -> "FileRevision":
        return cls(stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


@dataclass(frozen=True)
class IndexSnapshot:
    matrix: VectorMatrix
    metadata: IndexMetadata
    revision: FileRevision


@dataclass(frozen=True)
class IndexAcquisition:
    snapshot: IndexSnapshot
    source: IndexSource


class IndexPreparation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source: IndexSource
    generation: str | None
    document_count: int
    dimensions: int
    elapsed_ms: float


class VectorIndex:
    def __init__(self, directory: Path, identity: IndexIdentity):
        self.directory = directory
        self.identity = identity
        self.path = directory / f"{identity.digest}.npz"

    def revision(self) -> FileRevision | None:
        try:
            return FileRevision.from_stat(self.path.stat())
        except FileNotFoundError:
            return None

    def _validate_matrix(self, matrix: VectorMatrix, dimensions: int) -> None:
        if (matrix.dtype != np.dtype("float32")
                or matrix.shape != (self.identity.document_count, dimensions)
                or dimensions < 1 or not np.isfinite(matrix).all()):
            raise ValueError("Invalid vector shape or values")
        norms = np.linalg.norm(matrix, axis=1)
        if not np.allclose(norms, 1., rtol=1e-4, atol=1e-5):
            raise ValueError("Vectors must have unit norm")

    def load(self) -> IndexSnapshot:
        try:
            with self.path.open("rb") as stream:
                with np.load(stream, allow_pickle=False) as bundle:
                    metadata = IndexMetadata.model_validate_json(str(bundle["metadata"].item()))
                    if metadata.identity != self.identity:
                        raise ValueError("Index identity mismatch")
                    matrix = bundle["matrix"]
                    self._validate_matrix(matrix, metadata.dimensions)
                revision = FileRevision.from_stat(os.fstat(stream.fileno()))
        except FileNotFoundError:
            raise
        except (OSError, ValueError, TypeError, KeyError, EOFError, BadZipFile) as exc:
            raise ModelUnavailable("Kalıcı indeks geçersiz veya okunamadı; scripts/reindex.py ile yeniden oluşturun.") from exc
        matrix.setflags(write=False)
        return IndexSnapshot(matrix, metadata, revision)

    @contextmanager
    def _writer_lock(self) -> Iterator[None]:
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            stream = self.path.with_suffix(".lock").open("a+b")
        except OSError as exc:
            raise ModelUnavailable("Kalıcı indeks kilidi açılamadı; depolama izinlerini kontrol edin.") from exc
        with stream:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            except OSError as exc:
                raise ModelUnavailable("Kalıcı indeks kilidi alınamadı; depolamayı kontrol edin.") from exc
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        # Keep the lock inode stable: unlinking creates independent competing locks.

    def create_missing(self, builder: Callable[[], VectorMatrix]) -> IndexAcquisition:
        try:
            return IndexAcquisition(self.load(), "disk")
        except FileNotFoundError:
            pass
        with self._writer_lock():
            try:
                return IndexAcquisition(self.load(), "disk")
            except FileNotFoundError:
                return self._publish(builder)

    def rebuild(self, builder: Callable[[], VectorMatrix]) -> IndexAcquisition:
        with self._writer_lock():
            return IndexAcquisition(self._publish(builder).snapshot, "rebuilt")

    def _publish(self, builder: Callable[[], VectorMatrix]) -> IndexAcquisition:
        matrix = builder()
        temporary: Path | None = None
        try:
            dimensions = matrix.shape[1] if matrix.ndim == 2 else 0
            self._validate_matrix(matrix, dimensions)
            metadata = IndexMetadata(identity=self.identity, generation=uuid4().hex, dimensions=dimensions)
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self.directory, prefix=f"{self.identity.digest}.", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                np.savez(stream, matrix=matrix, metadata=np.asarray(metadata.model_dump_json()))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
        except (OSError, ValueError, TypeError) as exc:
            raise ModelUnavailable("Kalıcı indeks yazılamadı; mevcut indeks korundu. Depolamayı kontrol edip reindex çalıştırın.") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return IndexAcquisition(self.load(), "built")
