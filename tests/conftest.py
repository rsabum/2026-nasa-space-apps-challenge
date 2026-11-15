"""Shared fixtures. Everything here is offline: the mock services run in-process
on a random localhost port, and each test gets its own temporary data dir."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from field_shift.config import REPO_ROOT, Config, load_config
from field_shift.data import credentials
from field_shift.mock.app import create_app
from field_shift.mock.world import World

FIXTURES = Path(__file__).parent / "fixtures"
REAL = FIXTURES / "real"


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never read the developer's .env or real credentials during tests."""
    monkeypatch.setattr(credentials, "_dotenv_loaded", True)
    for name in ("NASS_API_KEY", "MOCK_EARTHDATA_TOKEN", "EARTHDATA_TOKEN",
                 "EARTHDATA_USERNAME", "EARTHDATA_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def world_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("world")


@pytest.fixture(scope="session")
def mock_world(world_dir: Path) -> World:
    return World(load_config(paths={"data_dir": str(world_dir)}))


@pytest.fixture(scope="session")
def mock_url(mock_world: World) -> Iterator[str]:
    app = create_app(mock_world.config, mock_world)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def config(tmp_path: Path, mock_url: str) -> Config:
    """Mock-mode config with a fresh data dir, pointed at the in-process mock."""
    return load_config(
        paths={"data_dir": str(tmp_path / "data"), "reference_dir": str(REPO_ROOT / "data/reference")},
        endpoints={"mock_base_url": mock_url},
    )


@pytest.fixture
def offline_config(tmp_path: Path) -> Config:
    """Config for pure parsing tests (no server needed)."""
    return load_config(paths={"data_dir": str(tmp_path / "data"),
                              "reference_dir": str(REPO_ROOT / "data/reference")})
