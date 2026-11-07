from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# Los instantes se guardan en UTC (TIMESTAMP sin zona con `server_default=func.now()`): en PostgreSQL `now()` usa la zona
# horaria de la SESIÓN, así que se fija en UTC y un servidor o una base con otra zona no guarda hora local.
_argumentos_conexion = {"options": "-c timezone=UTC"} if settings.database_url.startswith("postgresql") else {}

engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=_argumentos_conexion)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        # Explícito en vez de confiar en que close() revierta la
        # transacción abierta: si un router/service propaga una excepción
        # con cambios ya hechos vía flush() (no comiteados), esto asegura
        # que no queden pendientes en la conexión antes de devolverla al pool.
        db.rollback()
        raise
    finally:
        db.close()
