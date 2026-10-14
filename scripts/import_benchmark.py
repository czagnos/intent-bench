"""Import a customer CSV into the local, git-ignored workspace database."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from app.config import Settings
from app.importer import import_benchmark
from app.service import Studio

parser = argparse.ArgumentParser()
parser.add_argument("file", type=Path)
parser.add_argument("--workspace", default="demo")
args = parser.parse_args()
studio = Studio(Settings())
studio.ensure_workspace(args.workspace)
cases, report = import_benchmark(args.file.read_bytes(), args.file.name)
studio.store.save_cases(args.workspace, cases)
studio.store.save_import(args.workspace, report)
studio.close()
print(json.dumps(report, ensure_ascii=False, indent=2))
