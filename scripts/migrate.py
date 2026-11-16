"""Apply pending migrations to the database named by APP_DB (default data/app.db)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.foundation.db import applied_versions, db_path_from_env, migrate  # noqa: E402

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else db_path_from_env()
    applied = migrate(path)
    print(f"{path}: applied {applied or 'nothing new'}; now at {applied_versions(path)}")
