from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def build_session_factory(database_url: str):
    engine = create_engine(database_url, pool_pre_ping=True)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)
