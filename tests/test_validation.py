"""Test input validation — security-critical."""

import pytest

from mcp_hub.tools._validation import validate_hostname, validate_port, validate_url


class TestValidateHostname:
    def test_valid_hostname(self):
        assert validate_hostname("example.com") == "example.com"

    def test_valid_ip(self):
        assert validate_hostname("192.168.1.1") == "192.168.1.1"

    def test_valid_subdomain(self):
        assert validate_hostname("gitlab.steelcanvas.studio") == "gitlab.steelcanvas.studio"

    def test_valid_hyphen(self):
        assert validate_hostname("my-server-01") == "my-server-01"

    def test_strips_whitespace(self):
        assert validate_hostname("  example.com  ") == "example.com"

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="empty"):
            validate_hostname("")

    def test_rejects_command_injection_semicolon(self):
        with pytest.raises(ValueError, match="Invalid hostname"):
            validate_hostname("8.8.8.8; rm -rf /")

    def test_rejects_command_injection_pipe(self):
        with pytest.raises(ValueError, match="Invalid hostname"):
            validate_hostname("8.8.8.8 | cat /etc/passwd")

    def test_rejects_command_injection_backtick(self):
        with pytest.raises(ValueError, match="Invalid hostname"):
            validate_hostname("`whoami`")

    def test_rejects_command_injection_dollar(self):
        with pytest.raises(ValueError, match="Invalid hostname"):
            validate_hostname("$(whoami)")

    def test_rejects_newline(self):
        with pytest.raises(ValueError, match="Invalid hostname"):
            validate_hostname("example.com\nmalicious")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="Invalid hostname"):
            validate_hostname("example .com")

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="too long"):
            validate_hostname("a" * 256)

    def test_valid_ip_boundaries(self):
        assert validate_hostname("0.0.0.0") == "0.0.0.0"
        assert validate_hostname("255.255.255.255") == "255.255.255.255"

    def test_rejects_invalid_ip(self):
        with pytest.raises(ValueError, match="Invalid hostname"):
            validate_hostname("999.999.999.999")


class TestValidatePort:
    def test_valid_port(self):
        assert validate_port(8080) == 8080

    def test_port_min(self):
        assert validate_port(1) == 1

    def test_port_max(self):
        assert validate_port(65535) == 65535

    def test_rejects_zero(self):
        with pytest.raises(ValueError, match="Invalid port"):
            validate_port(0)

    def test_rejects_negative(self):
        with pytest.raises(ValueError, match="Invalid port"):
            validate_port(-1)

    def test_rejects_too_high(self):
        with pytest.raises(ValueError, match="Invalid port"):
            validate_port(65536)


class TestValidateUrl:
    def test_valid_http(self):
        assert validate_url("http://example.com") == "http://example.com"

    def test_valid_https(self):
        assert validate_url("https://example.com/path") == "https://example.com/path"

    def test_strips_whitespace(self):
        assert validate_url("  http://example.com  ") == "http://example.com"

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="empty"):
            validate_url("")

    def test_rejects_ftp(self):
        with pytest.raises(ValueError, match="Invalid URL scheme"):
            validate_url("ftp://example.com")

    def test_rejects_no_scheme(self):
        with pytest.raises(ValueError, match="Invalid URL scheme"):
            validate_url("example.com")

    def test_rejects_javascript(self):
        with pytest.raises(ValueError, match="Invalid URL scheme"):
            validate_url("javascript:alert(1)")

    def test_rejects_no_hostname(self):
        with pytest.raises(ValueError, match="hostname"):
            validate_url("http://")
