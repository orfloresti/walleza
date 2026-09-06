"""Smoke tests for `app.db`'s module-scope engine wiring (design D1/D2).

No live Postgres is reachable in this environment. `create_engine()` is
lazy (it never opens a network connection until first checkout), so
these tests only assert the engine is wired correctly and that using the
`get_db` dependency never attempts a real connection.
"""

from sqlalchemy.pool import NullPool

from app import db


def test_engine_uses_null_pool_not_a_client_side_pool() -> None:
    assert isinstance(db.engine.pool, NullPool)


def test_engine_targets_the_psycopg_driver() -> None:
    assert db.engine.url.drivername == "postgresql+psycopg"


def test_get_db_yields_and_closes_a_session_without_connecting() -> None:
    generator = db.get_db()

    session = next(generator)
    assert session is not None

    generator.close()
