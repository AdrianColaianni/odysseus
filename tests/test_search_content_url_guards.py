import ipaddress

from services.search import content as service_content


def test_search_content_url_guard_blocks_internal_names_and_address_classes():
    for url in (
        "http://printer.local/",
        "http://nas.lan/",
        "http://admin.internal/",
        "http://service.intranet/",
        "http://[::ffff:169.254.169.254]/latest/meta-data/",
        "http://224.0.0.1/",
        "http://[ff02::1]/",
        "http://[::]/",
    ):
        assert service_content._public_http_url(url) is False, url


def test_search_content_url_guard_blocks_dns_to_multicast(monkeypatch):
    monkeypatch.setattr(
        service_content,
        "_resolve_hostname_ips",
        lambda host: [ipaddress.ip_address("224.0.0.1")],
    )

    assert service_content._public_http_url("https://example.test/page") is False


def test_search_content_url_guard_still_allows_public_ip():
    assert service_content._public_http_url("https://93.184.216.34/") is True
