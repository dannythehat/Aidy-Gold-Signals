from __future__ import annotations

import time
from pathlib import Path

import day28_macro_vintage_acceptance as acceptance
import httpx
from aidy.macro_vintages import (
    AlfredSnapshot,
    MacroVintageError,
    alfred_url,
    parse_alfred_csv,
)

_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 6


def _parse_cached(
    raw: bytes,
    *,
    series_id: str,
    vintage,
    url: str,
) -> AlfredSnapshot:
    return parse_alfred_csv(
        raw,
        series_id=series_id,
        vintage_date=vintage,
        observation_start=acceptance.OBSERVATION_START,
        observation_end=acceptance.OBSERVATION_END,
        source_url=url,
    )


def _load_snapshots_v2(cache_dir: Path) -> list[AlfredSnapshot]:
    """Resume cached ALFRED capture and retry only transient transport failures."""

    cache_dir.mkdir(parents=True, exist_ok=True)
    vintages = acceptance._date_range(acceptance.VINTAGE_START, acceptance.VINTAGE_END)
    snapshots: list[AlfredSnapshot] = []
    total = len(acceptance.SERIES) * len(vintages)
    completed = 0

    timeout = httpx.Timeout(connect=30.0, read=180.0, write=60.0, pool=60.0)
    with httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        headers={"User-Agent": "AIDY-Gold-Day28-PIT-Vintage-Acceptance/1.0"},
    ) as client:
        for series_id in acceptance.SERIES:
            series_dir = cache_dir / series_id
            series_dir.mkdir(parents=True, exist_ok=True)
            for vintage in vintages:
                url = alfred_url(
                    series_id=series_id,
                    vintage_date=vintage,
                    observation_start=acceptance.OBSERVATION_START,
                    observation_end=acceptance.OBSERVATION_END,
                )
                path = series_dir / f"{vintage.isoformat()}.csv"
                snapshot: AlfredSnapshot | None = None

                if path.exists() and path.stat().st_size > 0:
                    try:
                        snapshot = _parse_cached(
                            path.read_bytes(),
                            series_id=series_id,
                            vintage=vintage,
                            url=url,
                        )
                    except (MacroVintageError, ValueError, OSError):
                        print(
                            f"DAY28 SOURCE invalid-cache {series_id} {vintage}; refetching",
                            flush=True,
                        )
                        path.unlink(missing_ok=True)

                if snapshot is None:
                    last_error: Exception | None = None
                    for attempt in range(1, _MAX_ATTEMPTS + 1):
                        try:
                            response = client.get(url)
                            if response.status_code == 200:
                                raw = response.content
                                snapshot = _parse_cached(
                                    raw,
                                    series_id=series_id,
                                    vintage=vintage,
                                    url=url,
                                )
                                temp_path = path.with_suffix(".csv.tmp")
                                temp_path.write_bytes(raw)
                                temp_path.replace(path)
                                break
                            if response.status_code not in _RETRYABLE_STATUS:
                                raise RuntimeError(
                                    f"Day 28 ALFRED fetch failed {series_id} {vintage}: "
                                    f"HTTP {response.status_code}"
                                )
                            last_error = RuntimeError(f"HTTP {response.status_code}")
                        except (httpx.TimeoutException, httpx.NetworkError) as exc:
                            last_error = exc

                        if attempt < _MAX_ATTEMPTS:
                            delay = min(30, 2 ** (attempt - 1))
                            print(
                                f"DAY28 SOURCE retry {series_id} {vintage} "
                                f"attempt={attempt + 1}/{_MAX_ATTEMPTS} after={delay}s",
                                flush=True,
                            )
                            time.sleep(delay)

                    if snapshot is None:
                        raise RuntimeError(
                            f"Day 28 ALFRED exhausted retries {series_id} {vintage}"
                        ) from last_error

                snapshots.append(snapshot)
                completed += 1
                if completed == 1 or completed % 20 == 0 or completed == total:
                    print(f"DAY28 SOURCE snapshots={completed}/{total}", flush=True)

    if len(snapshots) != acceptance.EXPECTED_SNAPSHOT_COUNT:
        raise RuntimeError(
            f"Day 28 expected {acceptance.EXPECTED_SNAPSHOT_COUNT} frozen snapshots, "
            f"found {len(snapshots)}."
        )
    return snapshots


def main() -> int:
    acceptance._ALLOWED_CHANGED_FILES.add("scripts/day28_macro_vintage_acceptance_v2.py")
    acceptance._load_snapshots = _load_snapshots_v2
    return acceptance.main()


if __name__ == "__main__":
    raise SystemExit(main())
