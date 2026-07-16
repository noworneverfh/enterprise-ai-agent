import os
import subprocess
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import DEFAULT_DATABASE_URL, Settings  # noqa: E402


EXPECTED_DATABASE_URL = (
    f"sqlite:///{(BACKEND_DIR / 'enterprise_ai_agent.db').resolve().as_posix()}"
)


def test_default_database_url_points_to_backend_directory() -> None:
    settings = Settings(_env_file=None)

    assert DEFAULT_DATABASE_URL == EXPECTED_DATABASE_URL
    assert settings.database_url == EXPECTED_DATABASE_URL


def test_relative_sqlite_database_url_is_resolved_against_backend(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./enterprise_ai_agent.db")

    settings = Settings(_env_file=None)

    assert settings.database_url == EXPECTED_DATABASE_URL


def test_absolute_sqlite_database_url_is_preserved() -> None:
    absolute_path = BACKEND_DIR / "custom.db"

    settings = Settings(
        database_url=f"sqlite:///{absolute_path.as_posix()}",
        _env_file=None,
    )

    assert settings.database_url == f"sqlite:///{absolute_path.as_posix()}"


def test_non_sqlite_database_url_is_preserved() -> None:
    database_url = "postgresql://user:pass@localhost/db"

    settings = Settings(database_url=database_url, _env_file=None)

    assert settings.database_url == database_url


def test_database_url_same_from_project_root_and_backend_cwd() -> None:
    root_output = _read_database_url_from_cwd(PROJECT_ROOT)
    backend_output = _read_database_url_from_cwd(BACKEND_DIR)

    assert root_output == EXPECTED_DATABASE_URL
    assert backend_output == EXPECTED_DATABASE_URL


def _read_database_url_from_cwd(cwd: Path) -> str:
    if cwd == BACKEND_DIR:
        path_setup = "sys.path.insert(0, str(Path('.').resolve()))"
        python_exe = str((PROJECT_ROOT / ".venv" / "Scripts" / "python.exe").resolve())
    else:
        path_setup = "sys.path.insert(0, str(Path('backend').resolve()))"
        python_exe = str((PROJECT_ROOT / ".venv" / "Scripts" / "python.exe").resolve())

    script = (
        "import sys\n"
        "from pathlib import Path\n"
        f"{path_setup}\n"
        "from app.core.config import Settings\n"
        "print(Settings(_env_file=None).database_url)\n"
    )
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    result = subprocess.run(
        [python_exe, "-c", script],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
