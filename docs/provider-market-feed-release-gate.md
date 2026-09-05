# Provider market feed release gate

The Super Signals Provider Lab market feed is read-only and release-gated. The endpoint serves only admitted XAUUSD M1 OHLC within a bounded PIT-safe window, reports expected and missing open-session minutes, and includes non-sensitive candle provenance.

The private signing key is held only by the Super Signals caller. AIDY contains only the Ed25519 public verification key. Formal forward remains independent of this provider interface.