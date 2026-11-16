"""The data folder: AK_DATA_DIR from the environment, then .env, then <repo>/local_data."""

from pathlib import Path

from app import paths


def test_environment_variable_wins(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("AK_DATA_DIR=/from/dotenv\n", encoding="utf-8")
    assert paths.resolve_data_dir({"AK_DATA_DIR": "/from/env"}, env_file) == Path("/from/env")


def test_dotenv_used_when_environment_lacks_it(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text('IUCN_API_TOKEN=abc\nAK_DATA_DIR="D:/My Data"\n', encoding="utf-8")
    assert paths.resolve_data_dir({}, env_file) == Path("D:/My Data")


def test_falls_back_to_local_data_in_the_repo(tmp_path):
    assert paths.resolve_data_dir({}, tmp_path / "missing.env") == paths.REPO_ROOT / "local_data"


def test_blank_values_are_ignored(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("AK_DATA_DIR=\n", encoding="utf-8")
    assert paths.resolve_data_dir({"AK_DATA_DIR": "  "}, env_file) == paths.REPO_ROOT / "local_data"


def test_dotenv_value_reads_quoted_and_unquoted_keys(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\nA=1\nB = 'two'\n", encoding="utf-8")
    assert paths.dotenv_value("A", env_file) == "1"
    assert paths.dotenv_value("B", env_file) == "two"
    assert paths.dotenv_value("C", env_file) is None


def test_data_path_joins_under_the_data_dir():
    assert paths.data_path("col", "col_xr.db") == paths.DATA_DIR / "col" / "col_xr.db"


def test_data_path_creates_the_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DATA_DIR", tmp_path / "fresh")
    assert paths.data_path("species.db") == tmp_path / "fresh" / "species.db"
    assert (tmp_path / "fresh").is_dir()


def test_data_path_survives_an_unreachable_data_dir(monkeypatch):
    """An unplugged drive must not break imports; the error comes when the file is used."""
    monkeypatch.setattr(paths, "DATA_DIR", Path("Q:/surely/not/mounted"))
    assert paths.data_path("x.db") == Path("Q:/surely/not/mounted/x.db")


def test_no_drive_letter_in_code():
    """Every data location is built from DATA_DIR, so no script names a drive."""
    roots = [paths.REPO_ROOT / "backend" / "app", paths.REPO_ROOT / "data"]
    offenders = [
        str(p.relative_to(paths.REPO_ROOT))
        for root in roots for p in root.rglob("*.py")
        if "AnimalKingdomSystem" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_no_process_wide_tls_bypass():
    """TLS verification stays on; scripts may only switch it off per run (--no-verify-ssl)."""
    roots = [paths.REPO_ROOT / "backend" / "app", paths.REPO_ROOT / "data"]
    offenders = [
        str(p.relative_to(paths.REPO_ROOT))
        for root in roots for p in root.rglob("*.py")
        if "_create_unverified_context" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_no_browser_user_agent_in_scripts():
    """Scripts name themselves honestly instead of posing as a browser."""
    roots = [paths.REPO_ROOT / "backend" / "app", paths.REPO_ROOT / "data"]
    offenders = [
        str(p.relative_to(paths.REPO_ROOT))
        for root in roots for p in root.rglob("*.py")
        if "Mozilla/5.0" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []
