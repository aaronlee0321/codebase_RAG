import csv
import json
import os
from pathlib import Path


ROOT = Path(__file__).parent
PARENT_ROOT = ROOT.parent

# CSVs that contain per-symbol rows with a file_path column
# Reading from Scripts (_GamePlay), _GameData, _ExternalAssets, and _GameModules folders
# Check both code_qa/processed and parent/processed directories
CSV_PATHS = [
    ROOT / "processed" / "Scripts" / "class_data.csv",
    ROOT / "processed" / "Scripts" / "method_data.csv",
    PARENT_ROOT / "processed" / "_GameData" / "class_data.csv",
    PARENT_ROOT / "processed" / "_GameData" / "method_data.csv",
    ROOT / "processed" / "_ExternalAssets" / "class_data.csv",
    ROOT / "processed" / "_ExternalAssets" / "method_data.csv",
    ROOT / "processed" / "_GameModules" / "class_data.csv",
    ROOT / "processed" / "_GameModules" / "method_data.csv",
]

OUT_JSON = ROOT / "indexed_cs_files.json"


def collect_indexed_files() -> dict[str, str]:
    """Return mapping of absolute_path -> file_name for all indexed .cs files."""
    files: dict[str, str] = {}

    for csv_path in CSV_PATHS:
        if not csv_path.exists():
            continue

        with csv_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                file_path = row.get("file_path")
                if not file_path:
                    continue

                # Normalize to absolute Windows-style path
                abs_path = os.path.abspath(file_path)

                # Only keep C# source files
                if not abs_path.lower().endswith(".cs"):
                    continue

                files.setdefault(abs_path, os.path.basename(abs_path))

    return files


def main() -> int:
    files = collect_indexed_files()

    data = [
        {
            "file_name": name,
            "absolute_path": path,
        }
        for path, name in sorted(files.items(), key=lambda kv: kv[1].lower())
    ]

    OUT_JSON.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Wrote {len(data)} indexed .cs files to {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



