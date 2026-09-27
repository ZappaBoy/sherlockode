from typing import Any

from fastmcp.client.transports import StdioTransport
from pydantic import SecretStr
from pydantic_ai import AbstractToolset
from pydantic_ai.mcp import MCPToolset

from sherlockcode.config.models import McpServerConfig, ProviderIntegration
from sherlockcode.providers.base import Provider


def uses_mcp(provider: Provider) -> bool:
    return provider.config.integration in (ProviderIntegration.MCP, ProviderIntegration.BOTH)


def uses_native_tools(provider: Provider) -> bool:
    return provider.config.integration in (ProviderIntegration.NATIVE, ProviderIntegration.BOTH)


def build_mcp_toolset(provider: Provider) -> AbstractToolset[Any]:
    # Expose a provider's official MCP server to the agent, namespaced by the provider name.
    config = provider.config.mcp
    if config is None:
        raise ValueError(f"provider '{provider.name}' has no MCP server configured")
    token = provider.config.token.get_secret_value() if provider.config.token else None
    toolset: AbstractToolset[Any] = (
        _stdio_toolset(config, token) if config.transport == "stdio" else _http_toolset(config, token)
    )
    if config.allowed_tools is not None:
        allowed = set(config.allowed_tools)
        toolset = toolset.filtered(lambda _ctx, tool: tool.name in allowed)
    return toolset.prefixed(f"{provider.name}_mcp")


def _stdio_toolset(config: McpServerConfig, token: str | None) -> MCPToolset[Any]:
    assert config.command is not None
    env = _reveal(config.env)
    if config.token_env and token:
        env[config.token_env] = token
    return MCPToolset(StdioTransport(command=config.command, args=config.args, env=env))


def _http_toolset(config: McpServerConfig, token: str | None) -> MCPToolset[Any]:
    assert config.url is not None
    headers = _reveal(config.headers)
    if config.forward_token and token:
        headers["Authorization"] = f"Bearer {token}"
    return MCPToolset(config.url, headers=headers)


def _reveal(values: dict[str, SecretStr]) -> dict[str, str]:
    return {key: value.get_secret_value() for key, value in values.items()}
