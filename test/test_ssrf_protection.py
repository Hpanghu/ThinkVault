"""SSRF/DNS rebinding 防护测试"""

import pytest

from thinkvault.utils.security import (
    validate_url_for_ssrf,
    parse_and_validate_url,
    is_private_ip,
    is_in_blocked_network,
)


class TestSSRFProtection:
    """SSRF 防护测试"""

    def test_allowed_localhost(self):
        """允许本地推理后端地址"""
        assert validate_url_for_ssrf("http://localhost:8080/v1") == "http://localhost:8080/v1"
        assert validate_url_for_ssrf("http://127.0.0.1:8080/v1") == "http://127.0.0.1:8080/v1"
        assert validate_url_for_ssrf("http://[::1]:8080/v1") == "http://[::1]:8080/v1"
        assert validate_url_for_ssrf("http://0.0.0.0:8080/v1") == "http://0.0.0.0:8080/v1"

    def test_block_private_ip_direct(self):
        """直接阻止私有 IP"""
        with pytest.raises(ValueError):
            validate_url_for_ssrf("http://192.168.1.1:8080/v1")
        with pytest.raises(ValueError):
            validate_url_for_ssrf("http://10.0.0.1:8080/v1")
        with pytest.raises(ValueError):
            validate_url_for_ssrf("http://172.16.0.1:8080/v1")

    def test_block_metadata_endpoints(self):
        """阻止云元数据端点"""
        with pytest.raises(ValueError):
            validate_url_for_ssrf("http://169.254.169.254/latest/meta-data/")
        with pytest.raises(ValueError):
            validate_url_for_ssrf("http://metadata.google.internal/computeMetadata/v1/")

    def test_block_invalid_scheme(self):
        """阻止不允许的协议"""
        with pytest.raises(ValueError):
            validate_url_for_ssrf("file:///etc/passwd")
        with pytest.raises(ValueError):
            validate_url_for_ssrf("ftp://evil.com/file")
        with pytest.raises(ValueError):
            validate_url_for_ssrf("gopher://evil.com/")

    def test_block_link_local(self):
        """阻止链路本地地址"""
        with pytest.raises(ValueError):
            validate_url_for_ssrf("http://169.254.1.1:8080/v1")

    def test_block_multicast(self):
        """阻止多播地址"""
        with pytest.raises(ValueError):
            validate_url_for_ssrf("http://224.0.0.1:8080/v1")

    def test_block_broadcast(self):
        """阻止广播地址"""
        with pytest.raises(ValueError):
            validate_url_for_ssrf("http://255.255.255.255:8080/v1")

    def test_allowed_public_ip(self):
        """允许公网 IP（需联网解析）"""
        try:
            result = validate_url_for_ssrf("http://api.openai.com/v1")
            assert result.startswith("http://")
        except ValueError:
            pytest.skip("无法解析公网域名")

    def test_parse_url_components(self):
        """解析 URL 组件"""
        scheme, hostname, port, path = parse_and_validate_url("http://localhost:8080/v1/models")
        assert scheme == "http"
        assert hostname == "localhost"
        assert port == 8080
        assert path == "/v1/models"

    def test_is_private_ip(self):
        """私有 IP 检测"""
        import ipaddress
        assert is_private_ip(ipaddress.ip_address("192.168.1.1"))
        assert is_private_ip(ipaddress.ip_address("10.0.0.1"))
        assert is_private_ip(ipaddress.ip_address("127.0.0.1"))
        assert is_private_ip(ipaddress.ip_address("::1"))
        assert not is_private_ip(ipaddress.ip_address("8.8.8.8"))

    def test_is_in_blocked_network(self):
        """阻止网络段检测"""
        assert is_in_blocked_network("192.168.1.1")
        assert is_in_blocked_network("10.0.0.1")
        assert is_in_blocked_network("172.16.0.1")
        assert is_in_blocked_network("169.254.169.254")
        assert is_in_blocked_network("127.0.0.1")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
