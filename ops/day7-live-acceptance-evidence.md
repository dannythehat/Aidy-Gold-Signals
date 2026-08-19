# Day 7 deterministic Gold feature engine live-acceptance evidence

- Trigger commit: 2dfd6958571e65ad17d043402472748ef89e9ff7
- Observed at UTC: 2026-08-19T14:27:35Z
- Dependencies: PASS
- Code gate: FAIL
- Code gate status: ruff=1 compile=0 pytest=1
- Structural boundary: NOT_REACHED_OR_FAILED
- Credential preflight: NOT_REACHED_OR_FAILED
- BigQuery dependency: NOT_REACHED_OR_FAILED
- Warehouse anchors: NOT_REACHED_OR_FAILED
- Deterministic retrospective packet: NOT_REACHED_OR_FAILED
- PIT packet / no retrospective leakage: NOT_REACHED_OR_FAILED
- Compact packet summary: NOT_REACHED_OR_FAILED

## ruff
```text
RUF007 Prefer `itertools.pairwise()` over `zip()` when iterating over successive pairs
   --> src/aidy/feature_engine.py:230:30
    |
228 |     sample = candles[-(period + 1):]
229 |     returns: list[Decimal] = []
230 |     for previous, current in zip(sample, sample[1:], strict=True):
    |                              ^^^
231 |         if previous.close == 0:
232 |             return None
    |
help: Replace `zip()` with `itertools.pairwise()`

FURB157 [*] Verbose expression in `Decimal` constructor
  --> tests/test_feature_engine.py:22:53
   |
20 |     low: Decimal | None = None,
21 | ) -> dict[str, object]:
22 |     price = close if close is not None else Decimal("3300") + Decimal(index) / Decimal(10)
   |                                                     ^^^^^^
23 |     open_price = price - Decimal("0.05")
24 |     high_price = high if high is not None else price + Decimal("0.20")
   |
help: Replace with `3300`
   |
21 | ) -> dict[str, object]:
   -     price = close if close is not None else Decimal("3300") + Decimal(index) / Decimal(10)
22 +     price = close if close is not None else Decimal(3300) + Decimal(index) / Decimal(10)
23 |     open_price = price - Decimal("0.05")
   |

FURB157 [*] Verbose expression in `Decimal` constructor
  --> tests/test_feature_engine.py:47:21
   |
45 | def _pit_row(*, index: int, observed_delay_seconds: int = 5) -> dict[str, object]:
46 |     opened = _BASE + timedelta(minutes=index)
47 |     price = Decimal("3300") + Decimal(index) / Decimal(10)
   |                     ^^^^^^
48 |     return {
49 |         "load_identity": f"pit-{index}",
   |
help: Replace with `3300`
   |
46 |     opened = _BASE + timedelta(minutes=index)
   -     price = Decimal("3300") + Decimal(index) / Decimal(10)
47 +     price = Decimal(3300) + Decimal(index) / Decimal(10)
48 |     return {
   |

FURB157 [*] Verbose expression in `Decimal` constructor
   --> tests/test_feature_engine.py:220:23
    |
218 |         timeframe="M1",
219 |         index=0,
220 |         close=Decimal("3300"),
    |                       ^^^^^^
221 |         high=Decimal("3299"),
222 |         low=Decimal("3298"),
    |
help: Replace with `3300`
    |
219 |         index=0,
    -         close=Decimal("3300"),
220 +         close=Decimal(3300),
221 |         high=Decimal("3299"),
    |

FURB157 [*] Verbose expression in `Decimal` constructor
   --> tests/test_feature_engine.py:221:22
    |
219 |         index=0,
220 |         close=Decimal("3300"),
221 |         high=Decimal("3299"),
    |                      ^^^^^^
222 |         low=Decimal("3298"),
223 |     )
    |
help: Replace with `3299`
    |
220 |         close=Decimal("3300"),
    -         high=Decimal("3299"),
221 +         high=Decimal(3299),
222 |         low=Decimal("3298"),
    |

FURB157 [*] Verbose expression in `Decimal` constructor
   --> tests/test_feature_engine.py:222:21
    |
220 |         close=Decimal("3300"),
221 |         high=Decimal("3299"),
222 |         low=Decimal("3298"),
    |                     ^^^^^^
223 |     )
224 |     with pytest.raises(ValueError, match="OHLC geometry"):
    |
help: Replace with `3298`
    |
221 |         high=Decimal("3299"),
    -         low=Decimal("3298"),
222 +         low=Decimal(3298),
223 |     )
    |

FURB157 [*] Verbose expression in `Decimal` constructor
   --> tests/test_feature_engine.py:250:25
    |
248 |     rows = []
249 |     for index, high_text in enumerate(highs):
250 |         close = Decimal("3300")
    |                         ^^^^^^
251 |         rows.append(
252 |             _research_row(
    |
help: Replace with `3300`
    |
249 |     for index, high_text in enumerate(highs):
    -         close = Decimal("3300")
250 +         close = Decimal(3300)
251 |         rows.append(
    |

FURB157 [*] Verbose expression in `Decimal` constructor
   --> tests/test_feature_engine.py:257:29
    |
255 |                 close=close,
256 |                 high=Decimal(high_text),
257 |                 low=Decimal("3299"),
    |                             ^^^^^^
258 |             )
259 |         )
    |
help: Replace with `3299`
    |
256 |                 high=Decimal(high_text),
    -                 low=Decimal("3299"),
257 +                 low=Decimal(3299),
258 |             )
    |

Found 10 errors.
[*] 8 fixable with the `--fix` option (2 hidden fixes can be enabled with the `--unsafe-fixes` option).
```

## compile
```text
```

## pytest
```text
...................................FF................................... [ 64%]
.......................................                                  [100%]
=================================== FAILURES ===================================
__ test_retrospective_packet_is_deterministic_and_permanently_pit_ineligible ___

    def test_retrospective_packet_is_deterministic_and_permanently_pit_ineligible() -> None:
        rows, as_of = _research_fixture()
>       first = build_feature_packet(
            as_of=as_of,
            symbol="XAUUSD",
            candle_rows=rows,
            mode="retrospective",
        )

tests/test_feature_engine.py:100: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/aidy/feature_engine.py:522: in build_feature_packet
    timeframe: _timeframe_features(grouped[timeframe])
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
src/aidy/feature_engine.py:343: in _timeframe_features
    "atr_14_bps": _fmt(_atr_bps(candles)),
                       ^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

candles = [Candle(timeframe='M1', open_time_utc=datetime.datetime(2025, 6, 10, 12, 40, tzinfo=datetime.timezone.utc), open=Decim...sha256': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'derivation_version': 'fixture-v1'}), ...]
period = 14

    def _atr_bps(candles: list[Candle], period: int = 14) -> Decimal | None:
        if len(candles) < period + 1:
            return None
        sample = candles[-(period + 1):]
        true_ranges: list[Decimal] = []
>       for previous, current in zip(sample, sample[1:], strict=True):
                                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       ValueError: zip() argument 2 is shorter than argument 1

src/aidy/feature_engine.py:211: ValueError
_____ test_full_research_fixture_produces_technical_features_and_alignment _____

    def test_full_research_fixture_produces_technical_features_and_alignment() -> None:
        rows, as_of = _research_fixture()
>       packet = build_feature_packet(
            as_of=as_of,
            symbol="XAUUSD",
            candle_rows=rows,
            mode="retrospective",
        )

tests/test_feature_engine.py:121: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/aidy/feature_engine.py:522: in build_feature_packet
    timeframe: _timeframe_features(grouped[timeframe])
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
src/aidy/feature_engine.py:343: in _timeframe_features
    "atr_14_bps": _fmt(_atr_bps(candles)),
                       ^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

candles = [Candle(timeframe='M1', open_time_utc=datetime.datetime(2025, 6, 10, 12, 40, tzinfo=datetime.timezone.utc), open=Decim...sha256': 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'derivation_version': 'fixture-v1'}), ...]
period = 14

    def _atr_bps(candles: list[Candle], period: int = 14) -> Decimal | None:
        if len(candles) < period + 1:
            return None
        sample = candles[-(period + 1):]
        true_ranges: list[Decimal] = []
>       for previous, current in zip(sample, sample[1:], strict=True):
                                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       ValueError: zip() argument 2 is shorter than argument 1

src/aidy/feature_engine.py:211: ValueError
=========================== short test summary info ============================
FAILED tests/test_feature_engine.py::test_retrospective_packet_is_deterministic_and_permanently_pit_ineligible - ValueError: zip() argument 2 is shorter than argument 1
FAILED tests/test_feature_engine.py::test_full_research_fixture_produces_technical_features_and_alignment - ValueError: zip() argument 2 is shorter than argument 1
2 failed, 109 passed in 0.80s
```
