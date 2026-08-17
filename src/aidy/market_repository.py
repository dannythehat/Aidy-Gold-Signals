from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker


def _persisted_position_state_json(snapshot: dict[str, object]) -> object | None:
    """Discard broker-position payloads in the retained PostgreSQL prototype."""

    del snapshot
    return None


class AidyMarketRepository:
    """Append-only persistence for AIDY point-in-time market evidence."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def store_candle(self, candle: dict[str, object]) -> tuple[UUID, int, bool]:
        params = dict(candle)
        with self._session_factory() as session:
            existing = session.execute(
                text(
                    """
                    SELECT id, revision_index
                    FROM market_candles
                    WHERE source=:source AND symbol=:symbol AND timeframe=:timeframe
                      AND open_time_utc=:open_time_utc AND payload_digest=:payload_digest
                    LIMIT 1
                    """
                ),
                params,
            ).mappings().first()
            if existing is not None:
                return existing["id"], int(existing["revision_index"]), False
            revision_index = int(
                session.execute(
                    text(
                        """
                        SELECT COALESCE(MAX(revision_index),0) + 1
                        FROM market_candles
                        WHERE source=:source AND symbol=:symbol AND timeframe=:timeframe
                          AND open_time_utc=:open_time_utc
                        """
                    ),
                    params,
                ).scalar_one()
            )
            candle_id = session.execute(
                text(
                    """
                    INSERT INTO market_candles (
                        symbol,timeframe,open_time_utc,broker_open_time,
                        open,high,low,close,tick_volume,spread,volume,
                        source,revision_index,payload_digest,first_observed_at
                    ) VALUES (
                        :symbol,:timeframe,:open_time_utc,:broker_open_time,
                        :open,:high,:low,:close,:tick_volume,:spread,:volume,
                        :source,:revision_index,:payload_digest,:first_observed_at
                    ) RETURNING id
                    """
                ),
                {**params, "revision_index": revision_index},
            ).scalar_one()
            session.commit()
            return candle_id, revision_index, True

    def latest_candle_ids(self, *, symbol: str) -> dict[str, UUID]:
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    """
                    SELECT DISTINCT ON (timeframe) timeframe, id
                    FROM market_candles
                    WHERE source='metaapi' AND symbol=:symbol
                    ORDER BY timeframe, open_time_utc DESC, revision_index DESC
                    """
                ),
                {"symbol": symbol},
            ).mappings().all()
        return {str(row["timeframe"]): row["id"] for row in rows}

    def event_observation_ids_known_at(
        self, *, captured_at: datetime, lookback_hours: int = 24
    ) -> list[UUID]:
        if lookback_hours <= 0:
            raise ValueError("Event lookback must be positive.")
        with self._session_factory() as session:
            rows = session.execute(
                text(
                    """
                    SELECT id FROM (
                        SELECT DISTINCT ON (source, external_id)
                            id, source, external_id, first_observed_at, revision_index
                        FROM market_event_observations
                        WHERE first_observed_at <= :captured_at
                          AND first_observed_at >= (
                              :captured_at - make_interval(hours => :lookback_hours)
                          )
                        ORDER BY source, external_id, revision_index DESC, first_observed_at DESC
                    ) AS known
                    ORDER BY first_observed_at, source, external_id
                    """
                ),
                {"captured_at": captured_at, "lookback_hours": lookback_hours},
            ).all()
        return [row[0] for row in rows]

    def store_snapshot(self, snapshot: dict[str, object]) -> UUID:
        params = dict(snapshot)
        params["position_state_json"] = _persisted_position_state_json(params)
        with self._session_factory() as session:
            snapshot_id = session.execute(
                text(
                    """
                    INSERT INTO market_snapshots (
                        captured_at,symbol,capture_status,bid,ask,mid,spread,
                        quote_time,quote_age_seconds,session_code,
                        position_state_json,data_availability_json,
                        event_observation_ids_json,latest_m1_id,latest_m5_id,
                        latest_m15_id,latest_h1_id,latest_h4_id,latest_d1_id,snapshot_digest
                    ) VALUES (
                        :captured_at,:symbol,:capture_status,:bid,:ask,:mid,:spread,
                        :quote_time,:quote_age_seconds,:session_code,
                        CAST(:position_state_json AS jsonb),CAST(:data_availability_json AS jsonb),
                        CAST(:event_observation_ids_json AS jsonb),:latest_m1_id,:latest_m5_id,
                        :latest_m15_id,:latest_h1_id,:latest_h4_id,:latest_d1_id,:snapshot_digest
                    ) RETURNING id
                    """
                ),
                params,
            ).scalar_one()
            session.commit()
            return snapshot_id

    def store_event_observation(
        self,
        *,
        source: str,
        external_id: str,
        event_type: str,
        published_at: datetime | None,
        first_observed_at: datetime,
        headline: str | None,
        structured_data_json: str,
        raw_payload_json: str,
        payload_digest: str,
    ) -> tuple[UUID, int, bool]:
        with self._session_factory() as session:
            existing = session.execute(
                text(
                    """
                    SELECT id, revision_index FROM market_event_observations
                    WHERE source=:source AND external_id=:external_id
                      AND payload_digest=:payload_digest LIMIT 1
                    """
                ),
                {"source": source, "external_id": external_id, "payload_digest": payload_digest},
            ).mappings().first()
            if existing is not None:
                return existing["id"], int(existing["revision_index"]), False
            revision_index = int(
                session.execute(
                    text(
                        """
                        SELECT COALESCE(MAX(revision_index),0) + 1
                        FROM market_event_observations
                        WHERE source=:source AND external_id=:external_id
                        """
                    ),
                    {"source": source, "external_id": external_id},
                ).scalar_one()
            )
            event_id = session.execute(
                text(
                    """
                    INSERT INTO market_event_observations (
                        source,external_id,event_type,published_at,first_observed_at,
                        revision_index,headline,structured_data_json,raw_payload_json,payload_digest
                    ) VALUES (
                        :source,:external_id,:event_type,:published_at,:first_observed_at,
                        :revision_index,:headline,CAST(:structured_data_json AS jsonb),
                        CAST(:raw_payload_json AS jsonb),:payload_digest
                    ) RETURNING id
                    """
                ),
                {
                    "source": source,
                    "external_id": external_id,
                    "event_type": event_type,
                    "published_at": published_at,
                    "first_observed_at": first_observed_at,
                    "revision_index": revision_index,
                    "headline": headline,
                    "structured_data_json": structured_data_json,
                    "raw_payload_json": raw_payload_json,
                    "payload_digest": payload_digest,
                },
            ).scalar_one()
            session.commit()
            return event_id, revision_index, True
