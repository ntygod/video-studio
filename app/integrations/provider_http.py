from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit


class ProviderHTTPConfigurationError(ValueError):
    pass


def provider_settings(provider: dict[str, Any]) -> dict[str, Any]:
    settings = provider.get("settings") or {}
    return settings if isinstance(settings, dict) else {}


def provider_api_root(provider: dict[str, Any]) -> str:
    """返回协议根地址；grok2api 统一补齐 /v1，且兼容用户已经填写 /v1。"""
    base_url = str(provider.get("base_url") or "").strip().rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProviderHTTPConfigurationError("Base URL 必须是有效的 http:// 或 https:// 地址")
    if str(provider.get("adapter") or "").lower() == "grok2api" and not parsed.path.rstrip("/").endswith("/v1"):
        parsed = parsed._replace(path=parsed.path.rstrip("/") + "/v1")
        return urlunsplit(parsed).rstrip("/")
    return base_url


def provider_endpoint(
    provider: dict[str, Any],
    default_path: str,
    setting_key: str | None = None,
) -> str:
    """拼接上游接口；高级设置中的绝对路径只替换 path，不允许换主机。"""
    api_root = provider_api_root(provider)
    settings = provider_settings(provider)
    override = str(settings.get(setting_key) or "").strip() if setting_key else ""
    if not override:
        return api_root.rstrip("/") + "/" + default_path.lstrip("/")
    if "://" in override:
        raise ProviderHTTPConfigurationError(f"{setting_key} 只能填写路径，不能填写完整 URL")
    if override.startswith("/"):
        parsed = urlsplit(api_root)
        return urlunsplit((parsed.scheme, parsed.netloc, override, "", ""))
    return api_root.rstrip("/") + "/" + override.lstrip("/")


def provider_headers(provider: dict[str, Any]) -> dict[str, str]:
    """构造通用请求头，支持自定义 header 名称、scheme 与附加 headers。"""
    settings = provider_settings(provider)
    raw_headers = settings.get("headers") or {}
    headers = (
        {str(key): str(value) for key, value in raw_headers.items()}
        if isinstance(raw_headers, dict)
        else {}
    )
    api_key = str(provider.get("api_key") or "")
    if not api_key:
        return headers
    header_name = str(settings.get("api_key_header") or "Authorization").strip()
    scheme = str(settings.get("api_key_scheme") if "api_key_scheme" in settings else "Bearer").strip()
    if not any(key.lower() == header_name.lower() for key in headers):
        headers[header_name] = f"{scheme} {api_key}".strip()
    return headers
