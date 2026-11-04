"""Infraestructura de la bitácora de auditoría: quién hizo algo y desde dónde
(`ContextoAuditoria`), los nombres de entidades y acciones, y el sanitizador
que deja `datos` libre de secretos y de datos personales.

No tiene tablas ni casos de uso: la tabla `bitacora` y la función que escribe
(`registrar_bitacora`) viven en `plataforma`. Convención para quien llama: pasar
IDS y CÓDIGOS, no nombres ni correos; para un cambio de campos, la lista de
NOMBRES de campo (`diff_campos`), no sus valores."""

import datetime as dt
import enum
import json
import math
import re
import unicodedata
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import Depends, Request

from app.core.rate_limit import direccion_cliente
from app.core.security import get_current_user

# ---- Entidades ----
ENTIDAD_SESION = "sesion"
ENTIDAD_USUARIO = "usuario"
ENTIDAD_ROL = "rol"
ENTIDAD_SUCURSAL = "sucursal"
ENTIDAD_EMPLEADO = "empleado"
ENTIDAD_EMPRESA = "empresa"
ENTIDAD_PLAN = "plan"
ENTIDAD_SUSCRIPCION = "suscripcion"
ENTIDAD_VENTA = "venta"
ENTIDAD_DEVOLUCION = "devolucion"
ENTIDAD_MOVIMIENTO_INVENTARIO = "movimiento_inventario"
ENTIDAD_BITACORA = "bitacora"
ENTIDAD_REPORTE_IA = "reporte_ia"  # E09
ENTIDAD_REPORTE = "reporte"  # E10 (descarga de los reportes convencionales)
# Reservadas: las registran etapas posteriores con la misma función.
ENTIDAD_LOTE_SYNC = "lote_sync"  # E07
ENTIDAD_OPERACION_SYNC = "operacion_sync"  # E08
ENTIDAD_COPIA_SEGURIDAD = "copia_seguridad"  # E22
ENTIDAD_CIERRE_CAJA = "cierre_caja"  # E21
ENTIDAD_MODELO_ML = "modelo_ml"  # E11
ENTIDAD_PEDIDO_CONTRATACION = "pedido_contratacion"  # compra de un plan con PayPal (CU-04)

# ---- Acciones (máximo 40 caracteres: columna `accion`) ----
ACCION_CREAR = "crear"
ACCION_ACTUALIZAR = "actualizar"
ACCION_DESACTIVAR = "desactivar"
ACCION_ASIGNAR_ROLES = "asignar_roles"
ACCION_ASIGNAR_PERMISOS = "asignar_permisos"
ACCION_LOGIN_EXITOSO = "login_exitoso"
ACCION_LOGIN_FALLIDO = "login_fallido"
ACCION_CONTRASENA_RESTABLECIDA = "contrasena_restablecida"
ACCION_ASIGNAR_PLAN = "asignar_plan"
ACCION_CAMBIAR_PLAN = "cambiar_plan"
ACCION_CAMBIAR_ESTADO = "cambiar_estado"
ACCION_RENOVAR = "renovar"
ACCION_ANULAR_PAGO = "anular_pago"
ACCION_REGISTRAR = "registrar"
ACCION_AJUSTE = "ajuste"
ACCION_PURGAR = "purgar"
ACCION_EJECUTAR = "ejecutar"  # E09
ACCION_RECHAZAR = "rechazar"  # E09
ACCION_EXPORTAR = "exportar"  # E10
# Reservadas.
ACCION_SINCRONIZAR_LOTE = "sincronizar_lote"  # E07
ACCION_RESOLVER_CONFLICTO = "resolver_conflicto"  # E08
ACCION_CAMBIAR_PLAZO_CAMBIO = "cambiar_plazo_cambio"  # E08
ACCION_DESCARGAR = "descargar"  # E22 (la copia se creó y se entregó)
ACCION_ELIMINAR = "eliminar"  # E22 (copias que salen del historial por el límite del plan)
ACCION_FALLAR = "fallar"  # E22 (la copia no se pudo crear)
ACCION_ABRIR = "abrir"  # E21
ACCION_CERRAR = "cerrar"  # E21
ACCION_ENTRENAR = "entrenar"  # E11
# Compra de un plan con PayPal (pedido_contratacion).
ACCION_CAPTURAR = "capturar"  # el pago se cobró y la empresa se creó
ACCION_CANCELAR = "cancelar"
ACCION_SOLICITAR = "solicitar"  # el cliente pide un cambio de talla o color (CU-17, Etapa 2)
ACCION_APROBAR = "aprobar"  # el personal aprueba esa solicitud
ACCION_VENCER = "vencer"
ACCION_PAGADO_SIN_EMPRESA = "pagado_sin_empresa"  # se cobró pero la empresa no se pudo crear (reembolso manual)
ACCION_PAGO_NO_COINCIDE = "pago_no_coincide"  # PayPal informó otro monto u otra moneda: no se cobró

# ---- Contexto: quién y desde dónde ----


@dataclass(frozen=True)
class ContextoAuditoria:
    usuario_id: int | None
    empresa_id: int | None
    ip: str | None


def contexto_anonimo(request: Request) -> ContextoAuditoria:
    """Para lo que ocurre sin sesión (el login): solo se conoce la IP."""
    return ContextoAuditoria(usuario_id=None, empresa_id=None, ip=direccion_cliente(request))


def obtener_contexto_auditoria(request: Request, usuario=Depends(get_current_user)) -> ContextoAuditoria:
    """Dependencia de FastAPI: el usuario autenticado, su empresa (NULL para el
    superadministrador) y la IP real del cliente."""
    return ContextoAuditoria(usuario_id=usuario.id, empresa_id=usuario.empresa_id, ip=direccion_cliente(request))


# ---- Sanitizador ----

MARCA_OMITIDO = "[omitido]"
PROFUNDIDAD_MAXIMA = 4
LARGO_MAXIMO_TEXTO = 200
ELEMENTOS_MAXIMOS = 50
BYTES_MAXIMOS = 4096

# Claves cuyo valor jamás se guarda (comparación sin mayúsculas ni tildes, "contiene").
_CLAVES_SECRETAS = (
    "password", "contrasena", "clave", "secret", "token", "hash", "authorization",
    "bearer", "jwt", "api_key", "apikey", "cvv", "tarjeta", "card",
)  # fmt: skip
# Datos personales (también "contiene"). `ci` y `nit` se comparan por palabra
# entera: "ciudad_id" y "unidades" no son datos personales.
_CLAVES_PERSONALES = (
    "email", "correo", "telefono", "celular", "direccion", "ci_nit", "fecha_nacimiento",
    "estatura", "razon_social", "latitud", "longitud",
)  # fmt: skip
_PALABRAS_PERSONALES = frozenset({"ci", "nit"})

_RE_JWT = re.compile(r"^eyJ[\w-]*\.[\w-]*\.[\w-]*")
_RE_BCRYPT = re.compile(r"^\$2[abxy]?\$\d{2}\$")
_RE_CORREO = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _normalizar_clave(clave: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", clave).encode("ascii", "ignore").decode()
    return sin_tildes.lower()


def _es_clave_prohibida(clave: str, valor: Any) -> bool:
    texto = _normalizar_clave(clave)
    if any(parte in texto for parte in _CLAVES_SECRETAS):
        return True
    # Una referencia numérica (`direccion_id`, `cliente_id`) es un id, no un dato personal.
    if texto.endswith("_id") and isinstance(valor, int) and not isinstance(valor, bool):
        return False
    if any(parte in texto for parte in _CLAVES_PERSONALES):
        return True
    return bool(_PALABRAS_PERSONALES.intersection(re.split(r"[^a-z0-9]+", texto)))


def _es_texto_sospechoso(texto: str) -> bool:
    return bool(_RE_JWT.match(texto) or _RE_BCRYPT.match(texto) or _RE_CORREO.search(texto))


def _limpiar(valor: Any, profundidad: int) -> Any:
    if isinstance(valor, enum.Enum):  # antes que int/str: hay Enum que además son int o str
        return _limpiar(valor.value, profundidad)
    if valor is None or isinstance(valor, bool | int):
        return valor
    if isinstance(valor, float):
        return valor if math.isfinite(valor) else str(valor)
    if isinstance(valor, str):
        if _es_texto_sospechoso(valor):
            return MARCA_OMITIDO
        return valor[:LARGO_MAXIMO_TEXTO]
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, dt.datetime | dt.date | dt.time):
        return valor.isoformat()
    if isinstance(valor, uuid.UUID):
        return str(valor)
    if isinstance(valor, bytes | bytearray):
        return MARCA_OMITIDO
    if isinstance(valor, Mapping):
        if profundidad >= PROFUNDIDAD_MAXIMA:
            return "[profundo]"
        return {
            str(clave)[:LARGO_MAXIMO_TEXTO]: (
                MARCA_OMITIDO if _es_clave_prohibida(str(clave), item) else _limpiar(item, profundidad + 1)
            )
            for clave, item in valor.items()
        }
    if isinstance(valor, list | tuple | set | frozenset):
        if profundidad >= PROFUNDIDAD_MAXIMA:
            return "[profundo]"
        elementos = list(valor)
        if isinstance(valor, set | frozenset):
            elementos.sort(key=str)
        limpios = [_limpiar(item, profundidad + 1) for item in elementos[:ELEMENTOS_MAXIMOS]]
        if len(elementos) > ELEMENTOS_MAXIMOS:
            limpios.append(f"...+{len(elementos) - ELEMENTOS_MAXIMOS}")
        return limpios
    return str(valor)[:100]


def sanear_datos(datos: Any) -> dict | None:
    """Versión segura de `datos` para guardar en la bitácora (función pura: no
    modifica lo que recibe).

    - Convierte a tipos JSON (Decimal, fechas, UUID, Enum, conjuntos).
    - Las claves de secretos y de datos personales conservan la clave con el
      valor "[omitido]": se ve que el campo existió sin ver su contenido.
    - Un texto con forma de JWT, de hash bcrypt o de correo se omite aunque su
      clave sea inocente.
    - Límites: profundidad 4, textos de 200 caracteres, listas de 50 elementos
      y 4096 bytes en total (si se pasa: {"truncado": true, "claves": [...]})."""
    if datos is None:
        return None
    if not isinstance(datos, Mapping):
        datos = {"valor": datos}
    limpio = _limpiar(datos, 0)
    tamano = len(json.dumps(limpio, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if tamano > BYTES_MAXIMOS:
        return {"truncado": True, "claves": list(limpio)[:20]}
    return limpio


def diff_campos(antes: Any, despues: Mapping[str, Any], campos_visibles: Iterable[str] = ()) -> dict:
    """Qué campos cambiaron. `antes` es el objeto (o mapa) con los valores
    actuales y `despues` los valores nuevos (solo los campos que se piden
    cambiar). Devuelve {"campos": [nombres...]} y, solo para los campos
    listados en `campos_visibles` (no sensibles: activo, estado, cargo...), sus
    valores en "antes" y "despues"."""

    def valor_actual(campo: str) -> Any:
        return antes.get(campo) if isinstance(antes, Mapping) else getattr(antes, campo, None)

    visibles = set(campos_visibles)
    cambiados = [campo for campo, nuevo in despues.items() if valor_actual(campo) != nuevo]
    resultado: dict[str, Any] = {"campos": cambiados}
    mostrar = [campo for campo in cambiados if campo in visibles]
    if mostrar:
        resultado["antes"] = {campo: valor_actual(campo) for campo in mostrar}
        resultado["despues"] = {campo: despues[campo] for campo in mostrar}
    return resultado
