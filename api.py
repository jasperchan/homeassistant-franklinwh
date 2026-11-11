"""Thin helpers for FranklinWH cloud endpoints the library does not wrap yet.

Everything goes through ``client._get`` / ``client.url_base`` so these can be
moved into franklinwh-python unchanged.
"""

from typing import Any

from franklinwh import Client


class FranklinWHApiError(Exception):
    """The cloud answered with a non-200 application code."""

    def __init__(self, code: int | None, message: str | None) -> None:
        """Initialize the error."""
        super().__init__(f"API error {code}: {message}")
        self.code = code
        self.message = message


async def _result(client: Client, path: str, params: dict | None = None) -> Any:
    """GET ``url_base + path`` and return the ``result`` of a code-200 reply."""
    res = await client._get(client.url_base + path, params)  # noqa: SLF001
    if res.get("code") != 200:
        raise FranklinWHApiError(res.get("code"), res.get("message"))
    return res["result"]


async def get_apowers_info(client: Client) -> list[dict[str, Any]]:
    """Per-aPower firmware versions, ratings, remaining energy and SOC."""
    return await _result(client, "hes-gateway/terminal/obtainApowersInfo")


async def get_warranty_info(client: Client) -> dict[str, Any]:
    """Warranty expirations, throughput allowance and installer contact."""
    return await _result(client, "hes-gateway/terminal/v2/warrantyInfo")


async def get_system_setting(client: Client) -> dict[str, Any]:
    """Installer-level system settings (grid export, rapid shutdown, ...)."""
    return await _result(client, "hes-gateway/terminal/getGatewaySystemSetting")


async def get_gateway_info(client: Client) -> dict[str, Any] | None:
    """Return the ``getHomeGatewayList`` entry for this client's gateway."""
    gateways = await client.get_home_gateway_list()
    for gateway in gateways or ():
        if gateway.get("id") == client.gateway:
            return gateway
    return None
