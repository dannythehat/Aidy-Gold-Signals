from __future__ import annotations

import inspect

from provider_entry import Default as ProviderDefault


def test_provider_entry_declares_concrete_queue_handler() -> None:
    """The configured Worker entrypoint must expose queue directly.

    Provider HTTP routing lives in a subclass of the core Worker. Cloudflare queue
    delivery must not depend on inherited event-handler discovery: if this method
    disappears, scheduled market capture can strand messages while HTTP health stays green.
    """

    assert "queue" in ProviderDefault.__dict__
    assert inspect.iscoroutinefunction(ProviderDefault.__dict__["queue"])
