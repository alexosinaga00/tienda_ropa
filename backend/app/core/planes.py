"""Plan y suscripción de la empresa: lo que el backend exige antes de operar.

Infraestructura transversal (no es un paquete de negocio). Sigue el patrón de
`core/security.py` (`core` ← `plataforma`): para saber el plan de la empresa
importa `plataforma.politicas` de forma diferida, dentro de cada función.

- `verificar_suscripcion_activa`: sin suscripción activa (suspendida, vencida,
  cancelada, inexistente) o con la empresa inactiva, una empresa no opera
  (`ErrorFuncional` 403 `suscripcion_no_activa`). La corren `get_current_user`
  (rutas autenticadas) y `contexto_empresa` (tienda pública), salvo en las
  rutas de `RUTAS_SIN_SUSCRIPCION`.
- `exigir_funcionalidad`: dependencia de FastAPI que exige que el plan incluya
  una funcionalidad (403 `plan_no_incluye_funcionalidad`). Lo que incluye cada
  plan se lee de la tabla `plan`, no del código.

Orden de errores: 401 (sin sesión) → 403 `suscripcion_no_activa` → 403
`plan_no_incluye_funcionalidad` → 403 falta el permiso → reglas de negocio.
"""

from __future__ import annotations

import re

from fastapi import Depends, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import ErrorFuncional

# Funcionalidades que un plan puede incluir. La cadena es el nombre de la
# columna del plan; la lista es cerrada.
FUNC_GESTION_PRODUCTOS = "gestion_productos"
FUNC_GESTION_VENTAS = "gestion_ventas"
FUNC_RESERVAS = "reservas"
FUNC_REPORTES_CONVENCIONALES = "reportes_convencionales"
FUNC_REPORTES_IA = "reportes_ia"
FUNC_OPERACION_OFFLINE = "operacion_offline"
FUNC_ANALITICA_ML = "analitica_ml"
FUNC_COPIAS_SEGURIDAD = "copias_seguridad"

FUNCIONALIDADES = (
    FUNC_GESTION_PRODUCTOS,
    FUNC_GESTION_VENTAS,
    FUNC_RESERVAS,
    FUNC_REPORTES_CONVENCIONALES,
    FUNC_REPORTES_IA,
    FUNC_OPERACION_OFFLINE,
    FUNC_ANALITICA_ML,
    FUNC_COPIAS_SEGURIDAD,
)

# Rutas que NO exigen suscripción activa: la sesión, la propia empresa y su
# suscripción (para poder renovar), la plataforma, los pagos que ya movieron
# dinero (webhook y pantalla QR), las tareas de servicio y la salud. Por
# prefijo; todo lo demás queda protegido por defecto.
RUTAS_SIN_SUSCRIPCION = (
    "/health",
    "/api/v1/auth/",
    "/api/v1/mi-empresa",
    "/api/v1/plataforma/",
    "/api/v1/public/tiendas",
    "/api/v1/public/planes",
    # Contratación pública (prueba gratuita y compra con PayPal, incluidas las rutas con `{token}` del pedido). Con
    # barra final: "contratacion" es un código reservado, así que ninguna tienda cuelga de este prefijo.
    "/api/v1/public/contratacion/",
    "/api/v1/pagos/webhook/",
    "/api/v1/pagos/qr/",
    "/api/v1/tareas/",
    # El lote offline se atiende aunque la suscripción o el plan no alcancen, para GUARDAR
    # el rechazo de cada operación con su motivo (D16). Las consultas (GET) sí exigen ambos.
    "/api/v1/sincronizacion/lote",
)
# /api/v1/public/{codigo}/tienda: los datos públicos de la tienda.
_RUTA_TIENDA_PUBLICA = re.compile(r"^/api/v1/public/[^/]+/tienda$")


def ruta_exenta_de_suscripcion(ruta: str) -> bool:
    """Si `ruta` se atiende aunque la suscripción no esté activa."""
    return ruta.startswith(RUTAS_SIN_SUSCRIPCION) or bool(_RUTA_TIENDA_PUBLICA.match(ruta))


def _situacion(db: Session, request: Request | None = None):
    """La situación de la empresa de la sesión. Con `request`, se calcula una
    sola vez por petición (queda en `request.state`)."""
    from app.core.tenant import exigir_empresa
    from app.plataforma import politicas as plataforma_politicas

    if request is None:
        return plataforma_politicas.situacion_de_la_empresa(db)
    empresa_id = exigir_empresa(db)
    guardada = getattr(request.state, "situacion_empresa", None)
    if guardada is not None and guardada[0] == empresa_id:
        return guardada[1]
    situacion = plataforma_politicas.situacion_de_la_empresa(db)
    request.state.situacion_empresa = (empresa_id, situacion)
    return situacion


def verificar_suscripcion_activa(db: Session, request: Request | None = None) -> None:
    """Lanza `suscripcion_no_activa` (403) si la empresa de la sesión no tiene
    una suscripción activa y vigente por fecha, o está inactiva."""
    situacion = _situacion(db, request)
    if situacion.estado != "activa":
        raise ErrorFuncional(
            "suscripcion_no_activa",
            "La suscripción de la empresa no está activa",
            status.HTTP_403_FORBIDDEN,
            estado=situacion.estado,
        )


def _exigir(situacion, funcionalidad: str) -> None:
    plan = situacion.plan
    if plan is None or not getattr(plan, funcionalidad):
        raise ErrorFuncional(
            "plan_no_incluye_funcionalidad",
            "Su plan no incluye esta funcionalidad",
            status.HTTP_403_FORBIDDEN,
            funcionalidad=funcionalidad,
            plan=plan.codigo if plan is not None else None,
        )


def verificar_funcionalidad(db: Session, funcionalidad: str, request: Request | None = None) -> None:
    """La misma comprobación de `exigir_funcionalidad`, para llamarla desde un
    caso de uso (sincronización, copias de seguridad) fuera de una dependencia."""
    _validar_nombre(funcionalidad)
    _exigir(_situacion(db, request), funcionalidad)


def _validar_nombre(funcionalidad: str) -> None:
    if funcionalidad not in FUNCIONALIDADES:
        raise ValueError(f"Funcionalidad desconocida: {funcionalidad!r}. Válidas: {', '.join(FUNCIONALIDADES)}")


def exigir_funcionalidad(funcionalidad: str):
    """Fábrica de dependencias: la ruta solo responde si el plan de la empresa
    incluye `funcionalidad`. El nombre se valida AL IMPORTAR: un error de tipeo
    falla al arrancar, no en producción.

    Declara `get_current_user` para ejecutarse con la empresa ya fijada. Ponerla
    ANTES de `require_permission` en la lista de dependencias de la ruta, para
    que el orden de errores sea el documentado."""
    _validar_nombre(funcionalidad)
    from app.core.security import get_current_user

    def verificador(request: Request, usuario=Depends(get_current_user), db: Session = Depends(get_db)):
        _exigir(_situacion(db, request), funcionalidad)
        return usuario

    # Solo lectura: permite auditar cada ruta por introspección (tests/aislamiento).
    verificador.funcionalidad = funcionalidad
    return verificador
