import csv
from pathlib import Path


ROOT = Path(__file__).parent
CLASS_CSV = ROOT / "processed" / "tank_online_1-dev" / "class_data.csv"
OUT_MD = ROOT / "tank_online_1-dev_structure.md"


def main() -> int:
    if not CLASS_CSV.exists():
        print(f"class_data.csv not found at {CLASS_CSV}")
        return 1

    by_file = {}
    with CLASS_CSV.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            file_path = row["file_path"]
            class_name = row.get("class_name") or "(anonymous / no class)"
            by_file.setdefault(file_path, set()).add(class_name)

    lines = []
    lines.append("# C# Classes and Files in `tank_online_1-dev`")
    lines.append("")

    for file_path in sorted(by_file.keys()):
        # Show path relative to tank_online_1-dev root
        parts = file_path.split("tank_online_1-dev", 1)
        rel = parts[-1].lstrip("\\/") if len(parts) > 1 else file_path
        lines.append(f"## `{rel}`")
        for cls in sorted(by_file[file_path]):
            lines.append(f"- **class**: `{cls}`")
        lines.append("")

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote markdown summary to: {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())





