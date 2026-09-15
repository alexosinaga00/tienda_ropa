import asyncio
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.orm import Session

# Carga .env al entorno real del proceso (no solo a Settings): lo necesita
# GOOGLE_APPLICATION_CREDENTIALS, que las Application Default Credentials
# de Google leen directo de os.environ, no de la app.
load_dotenv()

from app.core.config import get_settings
from app.core.database import SessionLocal, get_db
from app.pagos import service as pagos_service
from app.reservas import service as reservas_service
from app.core.exceptions import registrar_handlers
from app.core.rate_limit import limiter
from app.abastecimiento.router import routers as abastecimiento_routers
from app.catalogo.router import routers as catalogo_routers
from app.core.router import routers as core_routers
from app.entregas.router import routers as entregas_routers
from app.inteligencia.router import routers as inteligencia_routers
from app.inventario.router import routers as inventario_routers
from app.organizacion.router import routers as organizacion_routers
from app.pagos.router import routers as pagos_routers
from app.probador.router import routers as probador_routers
from app.reportes.router import routers as reportes_routers
from app.reservas.router import routers as reservas_routers
from app.seguridad.router import routers as seguridad_routers
from app.ventas.router import routers as ventas_routers

logger = logging.getLogger(__name__)

settings = get_settings()


def _correr_tareas_periodicas() -> None:
    """Vence ventas digitales que quedaron sin pagar y reservas vencidas.
    Sesión propia, igual que la generación en segundo plano del probador."""
    db = SessionLocal()
    try:
        resultado = pagos_service.expirar_ventas_pendientes(db)
        expiradas = reservas_service.expirar_reservas(db)
        if resultado["anuladas"] or resultado["pagadas"] or expiradas:
            logger.info("Tareas periódicas: ventas %s, reservas expiradas %s", resultado, expiradas)
    except Exception:
        logger.exception("Falló la tarea periódica")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
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


app = FastAPI(title="FashionStore API", version="0.1.0", lifespan=lifespan)

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


# Los routers de cada paquete de negocio se registran acá a medida que existen.
for router in (
    core_routers
    + seguridad_routers
    + organizacion_routers
    + catalogo_routers
    + probador_routers
    + inventario_routers
    + abastecimiento_routers
    + reservas_routers
    + ventas_routers
    + pagos_routers
    + entregas_routers
    + inteligencia_routers
    + reportes_routers
):
    app.include_router(router)
