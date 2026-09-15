from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.relational_db import DEFAULT_DB_PATH, seed_relational_mock_data


def main() -> None:
    seed_relational_mock_data(DEFAULT_DB_PATH)
    print(f"Seeded relational database at {Path(DEFAULT_DB_PATH).resolve()}")


if __name__ == "__main__":
    main()
