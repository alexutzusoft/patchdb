from .database import PatchDB
from .errors import PatchDBError, InvalidJSONError, ModelSaidNo
from .query import Query, Condition

__all__ = ["PatchDB", "PatchDBError", "InvalidJSONError", "ModelSaidNo", "Query", "Condition"]
__version__ = "0.1.1"


def _autoload_env() -> None:
    """Load environment variables from env/.env relative to CWD or package root."""
    import os
    from pathlib import Path

    project_root = Path(__file__).resolve().parent.parent
    candidate_paths = [
        Path("env/.env"),
        project_root / "env" / ".env",
    ]

    for path in candidate_paths:
        if path.is_file():
            try:
                for line in path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip()
                        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                            val = val[1:-1]
                        if key and key not in os.environ:
                            os.environ[key] = val
                break
            except OSError:
                pass


_autoload_env()