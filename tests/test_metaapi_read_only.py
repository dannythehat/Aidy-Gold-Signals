from __future__ import annotations

import inspect

from aidy.metaapi_read_gateway import MetaApiReadGateway


def test_metaapi_gateway_public_surface_is_read_only() -> None:
    public_methods = {
        name
        for name, member in inspect.getmembers(MetaApiReadGateway, inspect.isfunction)
        if not name.startswith("_")
    }

    assert public_methods == {
        "read_historical_candles",
        "read_positions",
        "read_symbol_price",
        "resolve_account_region",
    }
