"""Acceptance 2 (env precedence) and 14 (SSRF / redirect / rebinding / resource caps)."""

import pytest

from furnishai.config import env_source, get_settings, load_env
from furnishai.safe_fetch import FetchBlocked, FetchFailed, RawResponse, SafeFetcher, ip_is_public, validate_url


def _repo(tmp_path, root_env=None, parent_env=None):
    parent = tmp_path / "parent"
    repo = parent / "repo"
    repo.mkdir(parents=True)
    if parent_env is not None:
        (parent / ".env").write_text(parent_env)
    if root_env is not None:
        (repo / ".env").write_text(root_env)
    return repo


def test_root_env_wins_over_parent(tmp_path):
    repo = _repo(tmp_path, "PORTKEY_API_KEY=root-fake\n", "PORTKEY_API_KEY=parent-fake\nFURNISHAI_DISABLE_LIVE=1\n")
    env = load_env(repo, environ={})
    assert env["PORTKEY_API_KEY"] == "root-fake"
    assert env["FURNISHAI_DISABLE_LIVE"] == "1"  # missing in root -> filled from parent
    assert env_source("PORTKEY_API_KEY", repo, {}) == "repo .env"


def test_parent_env_used_when_root_missing(tmp_path):
    repo = _repo(tmp_path, None, "PORTKEY_API_KEY=parent-fake\n")
    assert load_env(repo, environ={})["PORTKEY_API_KEY"] == "parent-fake"
    assert env_source("PORTKEY_API_KEY", repo, {}) == "parent .env"


def test_process_env_takes_precedence(tmp_path):
    repo = _repo(tmp_path, "PORTKEY_API_KEY=root-fake\n")
    assert load_env(repo, environ={"PORTKEY_API_KEY": "proc-fake"})["PORTKEY_API_KEY"] == "proc-fake"


def test_grandparent_env_is_not_searched(tmp_path):
    repo = _repo(tmp_path)
    (tmp_path / ".env").write_text("PORTKEY_API_KEY=grandparent-fake\n")
    assert "PORTKEY_API_KEY" not in load_env(repo, environ={})


def test_public_status_never_contains_key(tmp_path):
    repo = _repo(tmp_path, "PORTKEY_API_KEY=root-secret-value\n")
    s = get_settings(repo, environ={})
    assert s.live_available and "root-secret-value" not in str(s.public_status()) and "root-secret-value" not in repr(s)


# ------------------------------------------------------------------ SSRF
PUBLIC = lambda host, port: ["93.184.216.34"]  # noqa: E731


@pytest.mark.parametrize("url", [
    "http://localhost/", "http://127.0.0.1/", "http://10.0.0.5/", "http://192.168.1.1/", "http://172.16.3.3/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[fd00::1]/", "http://[::ffff:127.0.0.1]/",
    "http://100.64.0.1/", "http://0.0.0.0/", "file:///etc/passwd", "ftp://example.com/", "http://user:pw@example.com/",
    "http://example.com:8080/", "http://metadata.internal/", "gopher://example.com/",
])
def test_private_and_unsafe_urls_blocked(url):
    with pytest.raises(FetchBlocked):
        validate_url(url, PUBLIC)


def test_dns_to_private_blocked():
    with pytest.raises(FetchBlocked):
        validate_url("https://evil.example/", lambda h, p: ["10.1.2.3"])


def test_mixed_dns_answers_blocked():
    with pytest.raises(FetchBlocked):
        validate_url("https://evil.example/", lambda h, p: ["93.184.216.34", "127.0.0.1"])


def test_ip_public_helper():
    assert ip_is_public("93.184.216.34")
    assert not ip_is_public("169.254.169.254")
    assert not ip_is_public("::ffff:10.0.0.1")


class FakeNet:
    def __init__(self, responses, answers):
        self.responses = list(responses)
        self.answers = list(answers)
        self.connected_ips = []
        self.resolve_calls = 0

    def resolver(self, host, port):
        self.resolve_calls += 1
        return [self.answers.pop(0)] if self.answers else ["93.184.216.34"]

    def opener(self, target, headers, timeout, max_bytes):
        self.connected_ips.append(target.ip)
        return self.responses.pop(0)


def test_redirect_to_metadata_blocked():
    net = FakeNet([RawResponse(302, {"location": "http://169.254.169.254/latest/"}, b"")], [])
    f = SafeFetcher(resolver=net.resolver, opener=net.opener)
    with pytest.raises(FetchBlocked):
        f.fetch("https://shop.example/item")
    assert net.connected_ips == ["93.184.216.34"]  # never connected to the metadata address


def test_redirect_to_host_rebinding_to_private_blocked():
    net = FakeNet([RawResponse(301, {"location": "https://other.example/x"}, b"")], ["93.184.216.34", "127.0.0.1"])
    f = SafeFetcher(resolver=net.resolver, opener=net.opener)
    with pytest.raises(FetchBlocked):
        f.fetch("https://shop.example/item")
    assert net.connected_ips == ["93.184.216.34"]


def test_connection_pinned_to_validated_ip():
    # Rebinding defense: the connection target is the validated address, resolved once per hop.
    net = FakeNet([RawResponse(200, {"content-type": "text/html"}, b"<html></html>")], ["93.184.216.34", "127.0.0.1"])
    f = SafeFetcher(resolver=net.resolver, opener=net.opener)
    res = f.fetch("https://shop.example/item")
    assert res.status == 200 and net.connected_ips == ["93.184.216.34"] and net.resolve_calls == 1


def test_too_many_redirects():
    loops = [RawResponse(302, {"location": f"https://shop.example/{i}"}, b"") for i in range(10)]
    f = SafeFetcher(resolver=PUBLIC, opener=FakeNet(loops, []).opener, max_redirects=3)
    with pytest.raises(FetchBlocked):
        f.fetch("https://shop.example/start")


def test_oversize_and_wrong_type_and_compression_refused():
    big = FakeNet([RawResponse(200, {"content-type": "text/html"}, b"x" * 2000)], [])
    with pytest.raises(FetchFailed):
        SafeFetcher(resolver=PUBLIC, opener=big.opener).fetch("https://a.example/", max_bytes=1000)
    exe = FakeNet([RawResponse(200, {"content-type": "application/octet-stream"}, b"MZ")], [])
    with pytest.raises(FetchFailed):
        SafeFetcher(resolver=PUBLIC, opener=exe.opener).fetch("https://a.example/")
    gz = FakeNet([RawResponse(200, {"content-type": "text/html", "content-encoding": "gzip"}, b"..")], [])
    with pytest.raises(FetchFailed):
        SafeFetcher(resolver=PUBLIC, opener=gz.opener).fetch("https://a.example/")


def test_http_403_is_reported_as_failure_not_tls_error():
    net = FakeNet([RawResponse(403, {"content-type": "text/html"}, b"denied")], [])
    with pytest.raises(FetchFailed, match="HTTP 403"):
        SafeFetcher(resolver=PUBLIC, opener=net.opener).fetch("https://portal.example/")
