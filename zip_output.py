from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
ZIP_PATH = ROOT / "output.zip"
EXPECTED_NAMES = [f"EC_{index:03d}.json" for index in range(1, 51)]


def main() -> None:
    actual_names = sorted(path.name for path in OUTPUT_DIR.iterdir() if path.is_file())
    if actual_names != EXPECTED_NAMES:
        missing = sorted(set(EXPECTED_NAMES) - set(actual_names))
        unexpected = sorted(set(actual_names) - set(EXPECTED_NAMES))
        raise SystemExit(
            f"Output validation failed. Missing: {missing or 'none'}; "
            f"unexpected: {unexpected or 'none'}"
        )

    with ZipFile(ZIP_PATH, "w", compression=ZIP_DEFLATED) as archive:
        for name in EXPECTED_NAMES:
            archive.write(OUTPUT_DIR / name, arcname=name)

    print(f"Created {ZIP_PATH} with {len(EXPECTED_NAMES)} JSON files")


if __name__ == "__main__":
    main()
