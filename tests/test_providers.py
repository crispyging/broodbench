import pytest


def test_provider_normalizes_urls_and_hides_encrypted_key(tmp_path, monkeypatch):
    from providers import ProviderService
    from storage import Storage

    store = Storage(str(tmp_path / "db.sqlite"))
    service = ProviderService(store, secret="test-secret-that-is-long-enough")
    item = service.create({"name": "Local", "kind": "openai", "base_url": "http://127.0.0.1:8000", "api_key": "secret-token"})
    assert item["base_url"] == "http://127.0.0.1:8000/v1"
    assert item["key_set"] is True
    assert "secret-token" not in repr(item)
    assert "secret-token" not in repr(service.list())


def test_provider_rejects_unsafe_url_and_openrouter_custom_origin(tmp_path):
    from providers import ProviderService, ProviderError
    from storage import Storage

    service = ProviderService(Storage(str(tmp_path / "db.sqlite")), secret="x" * 32)
    for url in ("http://169.254.169.254/latest", "http://user:pass@example.com", "https://example.com/?x=1", "http://metadata.google.internal/computeMetadata/v1", "http://192.0.2.1"):
        with pytest.raises(ProviderError):
            service.create({"name": "bad", "kind": "openai", "base_url": url})
    with pytest.raises(ProviderError):
        service.create({"name": "router", "kind": "openrouter", "base_url": "https://example.com/v1"})


def test_provider_encrypts_key_and_same_origin_guard(tmp_path):
    from providers import ProviderService
    from storage import Storage
    store = Storage(str(tmp_path / "db.sqlite"))
    service = ProviderService(store, secret="test-secret-that-is-long-enough")
    service.create({"name": "x", "kind": "openai", "base_url": "https://api.example.com/v1", "api_key": "topsecret"})
    assert "topsecret" not in open(tmp_path / "db.sqlite", "rb").read().decode("latin1")
    assert service.mutation_origin_allowed("http://testserver", "http://testserver")
    assert not service.mutation_origin_allowed("https://evil.test", "http://testserver")


def test_url_dns_resolves_and_rejects_link_local(monkeypatch):
    from providers import ProviderService, ProviderError
    monkeypatch.setattr("providers.socket.getaddrinfo", lambda *a, **k: [(None,None,None,None,("169.254.1.2",0))])
    with pytest.raises(ProviderError): ProviderService._url("openai", "http://bad.example")
