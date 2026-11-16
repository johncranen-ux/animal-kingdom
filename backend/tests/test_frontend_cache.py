"""Frontend files must be revalidated, so a browser never runs stale JS or CSS."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.mark.parametrize("path", ["/", "/index.html", "/js/app.js", "/css/style.css"])
def test_frontend_file_must_be_revalidated(path):
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_unchanged_frontend_file_is_answered_with_304():
    # no-cache must not cost a full download when nothing changed
    etag = client.get("/js/app.js").headers["etag"]

    response = client.get("/js/app.js", headers={"If-None-Match": etag})

    assert response.status_code == 304
    assert response.content == b""
    assert response.headers["cache-control"] == "no-cache"
