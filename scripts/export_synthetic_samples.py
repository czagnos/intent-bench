"""Regenerate fixed CSV samples from their canonical, validated JSON annotations."""
import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from app.synthetic_samples import SAMPLE_DIRECTORY, WORKSPACES, load_sample_pack, render_sample_csv


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report stale or missing CSVs without writing.")
    args = parser.parse_args(argv)
    # Validate the entire pack before writing any derived artifact.
    exports = [(SAMPLE_DIRECTORY / f"{pack.sector}.csv", render_sample_csv(pack))
               for workspace in WORKSPACES for pack in [load_sample_pack("synthetic-v1", workspace)]]
    if args.check:
        stale = [path.name for path, text in exports if not path.is_file() or path.read_bytes() != text.encode("utf-8")]
        if stale:
            print("Stale synthetic CSV files: " + ", ".join(stale), file=sys.stderr)
            return 1
        print("4 CSV files are current.")
        return 0
    for path, text in exports:
        path.write_text(text, encoding="utf-8", newline="")
    print("Regenerated 4 synthetic CSV files from canonical JSON.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
