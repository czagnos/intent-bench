"""Import a customer CSV into the local, git-ignored workspace database."""
import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TypedDict

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from app.config import Settings
from app.service import Studio


class ImportFailure(TypedDict):
    error: str


def main(argv: Sequence[str] | None = None, *, settings: Settings | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--workspace", default="demo")
    args = parser.parse_args(argv)
    studio = Studio(settings or Settings())
    try:
        report = studio.import_benchmark(args.workspace, args.file.read_bytes(), args.file.name)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except ValidationError as exc:
        error: ImportFailure = {"error": "Invalid transcript: " + "; ".join(
            ".".join(str(part) for part in item["loc"]) + ": " + item["msg"] for item in exc.errors(include_input=False)
        )}
        print(json.dumps(error), file=sys.stderr)
        return 1
    except UnicodeError:
        error = {"error": "The CSV must be UTF-8 encoded."}
        print(json.dumps(error), file=sys.stderr)
        return 1
    except ValueError as exc:
        error = {"error": str(exc)}
        print(json.dumps(error), file=sys.stderr)
        return 1
    except (OSError, sqlite3.Error):
        error = {"error": "Local CSV or workspace unavailable; check the file and data directory permissions."}
        print(json.dumps(error), file=sys.stderr)
        return 1
    finally:
        studio.close()


if __name__ == "__main__":
    raise SystemExit(main())
