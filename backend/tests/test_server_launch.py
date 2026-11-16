"""The backend must not run on the loop whose listener dies on an aborted connection.

On Windows, uvicorn's default ProactorEventLoop closes the listening socket for good
on WinError 64 (clients aborting while the server is busy): the process stays alive
but the port refuses every connection until a restart.
"""

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from uvicorn import Config

ROOT = Path(__file__).resolve().parents[2]
FLAG = "--loop asyncio:SelectorEventLoop"


def _manage_module():
    spec = importlib.util.spec_from_file_location("manage", ROOT / "manage.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manage_starts_the_backend_on_the_selector_loop():
    command = " ".join(_manage_module().backend_command(8010))

    assert FLAG in command
    assert "--port 8010" in command


def test_e2e_server_starts_on_the_selector_loop():
    assert FLAG in (ROOT / "playwright.config.ts").read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform != "win32", reason="the bug and the loop choice are Windows-specific")
def test_flag_gives_a_selector_loop_rather_than_a_proactor():
    loop_factory = Config("app.main:app", loop=FLAG.split()[1]).get_loop_factory()

    loop = loop_factory()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()
