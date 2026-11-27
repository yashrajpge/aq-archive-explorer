"""Transient archive failures are retried; permanent ones are not (no network)."""
import http.client
import io
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openaq_explorer import s3archive


URL = "https://example.invalid/x"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def scripted(monkeypatch):
    """Script urlopen outcomes in order; record calls and sleeps."""
    calls, sleeps = [], []
    def install(*outcomes):
        queue = list(outcomes)
        def fake(req, timeout=None):
            calls.append(req.full_url)
            out = queue.pop(0)
            if isinstance(out, Exception):
                raise out
            return FakeResponse(out)
        monkeypatch.setattr(s3archive.urllib.request, "urlopen", fake)
    monkeypatch.setattr(s3archive, "_sleep", sleeps.append)
    return install, calls, sleeps


def http_error(code):
    return urllib.error.HTTPError("u", code, "x", {}, None)


def test_503_then_success_is_retried_with_backoff(scripted):
    install, calls, sleeps = scripted
    install(http_error(503), http_error(503), b"ok")
    assert s3archive._get(URL) == b"ok"
    assert len(calls) == 3 and sleeps == [0.5, 1.0]


@pytest.mark.parametrize("failure", [TimeoutError("slow"), ConnectionResetError("reset"),
                                     urllib.error.URLError("dns"),
                                     http.client.IncompleteRead(b"x")])
def test_transient_failure_then_success(scripted, failure):
    install, calls, _ = scripted
    install(failure, b"ok")
    assert s3archive._get(URL) == b"ok" and len(calls) == 2


@pytest.mark.parametrize("code", [404, 403, 400])
def test_permanent_http_errors_are_not_retried(scripted, code):
    install, calls, sleeps = scripted
    install(http_error(code))
    with pytest.raises(urllib.error.HTTPError) as caught:
        s3archive._get(URL)
    assert caught.value.code == code and len(calls) == 1 and sleeps == []


def test_gives_up_after_three_attempts_with_oserror(scripted):
    install, calls, _ = scripted
    install(http_error(503), http_error(503), http_error(503))
    with pytest.raises(urllib.error.HTTPError):
        s3archive._get(URL)
    assert len(calls) == 3
    install(http.client.IncompleteRead(b"x"), http.client.IncompleteRead(b"x"),
            http.client.IncompleteRead(b"x"))
    with pytest.raises(OSError):
        s3archive._get(URL)


def test_missing_day_file_still_means_no_data(scripted):
    install, calls, _ = scripted
    install(http_error(404))
    assert s3archive.fetch_day_counted(1, 2025, 3, 1) == ([], 0)
    assert len(calls) == 1
