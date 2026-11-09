import asyncio
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.orm import Session

# Carga .env al entorno real del proceso (no solo a Settings): lo necesita
# GOOGLE_APPLICATION_CREDENTIALS, que las Application Default Credentials
# de Google leen directo de os.environ, no de la app.
load_dotenv()

from app.catalogo.router import routers as catalogo_routers
from app.comercial.politicas import (
    expirar_reservas_de_todas_las_empresas,
    expirar_ventas_de_todas_las_empresas,
    vencer_solicitudes_de_todas_las_empresas,
    vencer_turnos_de_todas_las_empresas,
)
from app.comercial.router import routers as comercial_routers
from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.core.exceptions import registrar_handlers
from app.core.rate_limit import limiter
from app.core.registro import configurar_logs
from app.core.tenant import contexto_empresa
from app.inteligencia.router import routers as inteligencia_routers
from app.plataforma.politicas import vencer_suscripciones
from app.plataforma.router import routers as plataforma_routers
from app.sincronizacion.router import routers as sincronizacion_routers

logger = logging.getLogger(__name__)

settings = get_settings()


def _correr_tareas_periodicas() -> None:
    """Vence ventas digitales que quedaron sin pagar y reservas vencidas.
    Sesión propia, igual que la generación en segundo plano del probador.
    Las de ventas y reservas recorren todas las empresas activas (una por una,
    con su empresa fijada); la de suscripciones hace una sola pasada sobre
    todas (no toca datos de negocio). Cada tarea va aislada: si una falla, las
    otras corren igual."""
    for nombre, tarea in (
        ("ventas pendientes", expirar_ventas_de_todas_las_empresas),
        ("reservas", expirar_reservas_de_todas_las_empresas),
        ("solicitudes de cambio", vencer_solicitudes_de_todas_las_empresas),
        ("turnos de caja", vencer_turnos_de_todas_las_empresas),
        ("suscripciones", vencer_suscripciones),
    ):
        db = SessionLocal()
        try:
            resultado = tarea(db)
            if resultado and (not isinstance(resultado, dict) or any(resultado.values())):
                logger.info("Tarea periódica de %s: %s", nombre, resultado)
        except Exception:
            logger.exception("Falló la tarea periódica de %s", nombre)
        finally:
            db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Enciende los logs informativos de la aplicación (la sincronización, RNF10); sin esto solo salen avisos y errores.
    configurar_logs(settings.log_level)
    # Uvicorn corre con un solo worker (scripts/start.sh), así que hay una
    # sola copia de este loop; igual es idempotente por los locks de fila.
    tarea = None
    if settings.tareas_automaticas:

        async def loop() -> None:
            while True:
                await asyncio.to_thread(_correr_tareas_periodicas)
                await asyncio.sleep(settings.tareas_intervalo_segundos)

        tarea = asyncio.create_task(loop())
    yield
    if tarea is not None:
        tarea.cancel()


# `contexto_empresa` corre en toda petición: en /api/v1/public/{codigo}/... fija la
# empresa de la tienda; en las demás no hace nada (la fija get_current_user).
app = FastAPI(
    title="FashionStore API",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(contexto_empresa)],
)

# Rate limiting: por ahora solo lo usan los endpoints públicos del
# catálogo (ver catalogo/router.py) — es el punto más expuesto a tráfico
# anónimo desde que existe /catalogo en el web.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Punto donde el backend se abre a la web Angular: solo los orígenes
# listados en settings.cors_origins (core/config.py) pueden llamar esta API
# desde un navegador. El valor de la web debe apuntar a la misma base URL
# que autoriza acá (ver web/src/environments/environment*.ts -> apiUrl).
# La app Flutter no necesita estar en esta lista: CORS no aplica a Dio.
# Compresión gzip de las respuestas grandes (el paquete de descarga offline, E08): solo si el
# cliente la acepta y de más de 1000 bytes. Se agrega ANTES que CORS para que CORS quede por fuera.
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # El ETag del paquete de descarga y el nombre del archivo exportado (Content-Disposition,
    # E10): sin esto el JavaScript de la web no puede leerlos. X-Copia-Id y X-Checksum-SHA256: la
    # copia de seguridad (E22) los entrega junto al ZIP.
    expose_headers=["ETag", "Content-Disposition", "X-Copia-Id", "X-Checksum-SHA256"],
)

registrar_handlers(app)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> JSONResponse:
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check: no se pudo conectar a la base de datos")
        return JSONResponse(status_code=503, content={"status": "error", "detalle": "base de datos no disponible"})
    return JSONResponse(status_code=200, content={"status": "ok"})


# Acá se registran los routers de cada paquete (plataforma, catalogo, comercial, inteligencia,
# sincronizacion).
for router in (
    plataforma_routers
    + catalogo_routers
    + comercial_routers
    + inteligencia_routers
    + sincronizacion_routers
):
    app.include_router(router)
