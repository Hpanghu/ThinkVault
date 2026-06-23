"""安全工具模块 — SSRF/DNS rebinding 防护"""

import ipaddress
import socket
from urllib.parse import urlparse
from typing import Optional, Tuple, Set


# ── SSRF 防护配置 ──────────────────────────────────────────────

# 允许的协议
_ALLOWED_SCHEMES = {"http", "https"}

# 允许的本地主机名（用于连接本地推理后端）
_ALLOWED_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

# 阻止的已知危险主机名
_BLOCKED_HOSTNAMES = {
    # 云元数据服务
    "metadata.google.internal",
    "metadata.goog",
    "169.254.169.254",
    # AWS 元数据
    "ec2-",
    "ec2.internal",
    # Azure 元数据
    "169.254.169.254",
    # GCP 元数据
    "metadata.google.internal",
}

# 阻止的内网/特殊网络段
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("169.254.169.254/32"),   # 云元数据
    ipaddress.ip_network("10.0.0.0/8"),            # RFC 1918 Class A
    ipaddress.ip_network("172.16.0.0/12"),         # RFC 1918 Class B
    ipaddress.ip_network("192.168.0.0/16"),        # RFC 1918 Class C
    ipaddress.ip_network("0.0.0.0/8"),             # 当前网络
    ipaddress.ip_network("127.0.0.0/8"),           # 回环（除明确允许的地址外）
    ipaddress.ip_network("169.254.0.0/16"),        # 链路本地
    ipaddress.ip_network("192.0.0.0/24"),          # IANA 保留
    ipaddress.ip_network("192.0.2.0/24"),          # TEST-NET-1
    ipaddress.ip_network("198.51.100.0/24"),       # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),        # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),           # 多播
    ipaddress.ip_network("255.255.255.255/32"),    # 广播
    ipaddress.ip_network("fe80::/10"),             # IPv6 链路本地
    ipaddress.ip_network("fc00::/7"),              # IPv6 ULA
    ipaddress.ip_network("::1/128"),               # IPv6 回环
    ipaddress.ip_network("::/128"),                # IPv6 未指定地址
    ipaddress.ip_network("2001:db8::/32"),         # IPv6 文档地址
]


def is_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """判断 IP 是否为私有/内网地址"""
    return ip.is_private or ip.is_loopback or ip.is_link_local


def is_in_blocked_network(ip_str: str) -> bool:
    """检查 IP 是否在阻止网络段内"""
    try:
        ip = ipaddress.ip_address(ip_str)
        for network in _BLOCKED_NETWORKS:
            if ip in network:
                return True
        return is_private_ip(ip)
    except ValueError:
        return True


def parse_and_validate_url(url: str) -> Tuple[str, str, int, str]:
    """解析并验证 URL，防止 SSRF 和 DNS rebinding 攻击。

    返回: (scheme, hostname, port, path)
    抛出 ValueError 如果验证失败
    """
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"不允许的协议: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("无效的主机名")

    # 检查已知危险主机名
    lower_host = hostname.lower()
    for blocked in _BLOCKED_HOSTNAMES:
        if blocked in lower_host:
            raise ValueError(f"不允许的主机名: {hostname}")

    # 允许的本地地址直接返回（用于连接本地推理后端）
    if lower_host in _ALLOWED_LOCAL_HOSTNAMES:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return (parsed.scheme, hostname, port, parsed.path or "")

    # DNS rebinding 防护：解析主机名到 IP 地址
    # 关键：记录解析结果，后续请求必须使用该 IP，防止 DNS 重新绑定
    try:
        addr_infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError(f"无法解析主机名: {hostname}") from e

    # 获取所有解析的 IP 地址
    resolved_ips: Set[str] = set()
    for family, _, _, _, sockaddr in addr_infos:
        ip_str = str(sockaddr[0])
        resolved_ips.add(ip_str)

    # 检查所有解析的 IP 是否都在允许范围内
    for ip_str in resolved_ips:
        if is_in_blocked_network(ip_str):
            raise ValueError(f"不允许访问内网地址: {ip_str}")

    # 验证通过，返回第一个解析的 IP（用于后续请求绑定）
    # 这是 DNS rebinding 防护的关键：使用解析后的 IP 而非原始域名
    first_ip = resolved_ips.pop()
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    return (parsed.scheme, first_ip, port, parsed.path or "")


def build_safe_url(scheme: str, hostname: str, port: int, path: str) -> str:
    """使用验证后的组件构建安全 URL"""
    # IPv6 地址需要方括号
    host_part = f"[{hostname}]" if ":" in hostname else hostname
    if port == 80 and scheme == "http":
        return f"{scheme}://{host_part}{path}"
    if port == 443 and scheme == "https":
        return f"{scheme}://{host_part}{path}"
    return f"{scheme}://{host_part}:{port}{path}"


def validate_url_for_ssrf(url: str) -> str:
    """完整的 SSRF/DNS rebinding 防护验证。

    返回验证后的安全 URL（使用解析后的 IP），或抛出 ValueError。
    """
    scheme, hostname, port, path = parse_and_validate_url(url)
    return build_safe_url(scheme, hostname, port, path)
