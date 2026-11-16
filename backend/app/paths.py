"""Where the app's data lives: the SQLite database, the vector store, downloads,
checkpoints and backups.

One folder holds all of it. It is, in order:
  1. the AK_DATA_DIR environment variable;
  2. AK_DATA_DIR in the .env file at the project root;
  3. local_data/ in the project root (git-ignored).

Everything else builds its paths with data_path(), so moving the data means
changing one setting. SPECIES_DB_PATH, CHROMA_DB_PATH and IUCN_CHECKPOINT_PATH
still override single files.
"""

import os
from collections.abc import Mapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"


def dotenv_value(key: str, env_file: Path = ENV_FILE) -> str | None:
    """`key` from a KEY=value file, without quotes; None when absent or blank."""
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        name, sep, value = line.partition("=")
        if sep and name.strip() == key and not name.lstrip().startswith("#"):
            return value.strip().strip('"').strip("'") or None
    return None


def resolve_data_dir(environ: Mapping[str, str] = os.environ, env_file: Path = ENV_FILE) -> Path:
    value = (environ.get("AK_DATA_DIR") or "").strip() or dotenv_value("AK_DATA_DIR", env_file)
    return Path(value) if value else REPO_ROOT / "local_data"


DATA_DIR = resolve_data_dir()


def data_path(*parts: str) -> Path:
    """A path inside the data folder, e.g. data_path("col", "col_xr.db").

    Creates the data folder itself if needed (not subfolders). An unreachable
    folder, such as an unplugged drive, is left for the caller to report when
    it opens the file, so importing a module never fails on it.
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return DATA_DIR.joinpath(*parts)
