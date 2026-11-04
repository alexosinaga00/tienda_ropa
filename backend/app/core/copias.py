"""Motor de copias de seguridad por empresa (E22, D24-D25).

Arma, en memoria, un ZIP con TODOS los datos de UNA empresa: un JSON por tabla (`datos/<tabla>.json`), los
catálogos globales que esos datos referencian (`referencias/<tabla>.json`) y un `manifest.json` con la
versión del esquema, los conteos y el SHA-256 de cada archivo.

Reglas que este módulo hace cumplir:
- NUNCA `pg_dump`: copiaría a todas las empresas. Cada consulta lleva su filtro por `empresa_id` de forma
  EXPLÍCITA (el filtro automático del ORM no cubre consultas Core por nombre de tabla) y la empresa llega
  solo de quien llama (el token del administrador), nunca del cliente.
- La lista de tablas es EXPLÍCITA: incluidas, referencias y excluidas. Una prueba falla si aparece en
  `Base.metadata` una tabla que no esté en exactamente una categoría, así nadie agrega una tabla sin decidir si
  se respalda.
- Sin secretos: `usuario.password_hash`, `bitacora.ip`, las columnas generadas y cualquier columna cuyo nombre
  parezca un secreto no salen nunca; tampoco las tablas de pagos de la pasarela ni la caché del probador.
- Nada en disco: el ZIP vive en un `BytesIO`. Nada de datos de la empresa en logs.
- Topes de tamaño comprimido y de tiempo, revisados bloque a bloque: al excederlos se aborta y no se entrega
  nada parcial.

DEC-2: este módulo lee las tablas POR NOMBRE iterando `Base.metadata`. Es infraestructura genérica del
`core` (no consulta de un paquete a otro) y no importa ningún paquete de negocio; depende de que los modelos ya
estén registrados (la aplicación siempre los importa).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import math
import re
import threading
import time
import uuid
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import Column, Connection, String, Table, column, inspect, select, table
from sqlalchemy.sql.elements import ColumnElement

from app.core.database import Base

FORMATO = "fashionstore-copia-1"

# ---- Clasificación explícita de las tablas -----------------------------------------------------------------------

# Datos de la empresa, filtrados por `empresa_id` (salvo `empresa`, por id, y `usuario_rol`, por su usuario).
TABLAS_INCLUIDAS: tuple[str, ...] = (
    "activo_probador", "bitacora", "carrito", "carrito_detalle", "categoria", "ciudad", "cliente", "coleccion",
    "color", "consulta_voz", "devolucion", "devolucion_detalle", "direccion_cliente", "empleado", "empresa",
    "envio", "favorito", "historial_navegacion", "horario_sucursal", "material", "movimiento_inventario",
    "notificacion", "operacion_sync", "orden_compra", "orden_compra_detalle", "pago", "producto",
    "producto_imagen", "producto_proveedor", "producto_variante", "promocion", "promocion_alcance", "proveedor",
    "recepcion", "recepcion_detalle", "recomendacion", "regla_tarifa_envio", "reserva", "reserva_detalle",
    "reserva_historial", "stock", "sucursal", "suscripcion", "tabla_medida", "talla", "temporada",
    "transferencia", "transferencia_detalle", "usuario", "usuario_rol", "venta", "venta_detalle", "zona_envio",
)  # fmt: skip

# Catálogos globales que los datos referencian por id: NO son datos de la empresa, se guardan en `referencias/`
# para poder reinterpretar las llaves foráneas. `plan` y `rol` solo con lo que la empresa usa.
TABLAS_REFERENCIA: tuple[str, ...] = (
    "estado_pago", "estado_reserva", "estado_venta", "metodo_pago", "plan", "rol", "tipo_movimiento",
)  # fmt: skip

# Referencias que se copian completas (catálogos pequeños del sistema, iguales para todas las empresas).
_REFERENCIAS_COMPLETAS = frozenset({"estado_pago", "estado_reserva", "estado_venta", "metodo_pago", "tipo_movimiento"})

# Fuera de la copia, con la razón (aparece en el manifiesto y en la pantalla).
TABLAS_EXCLUIDAS: dict[str, str] = {
    "copia_seguridad": "es el historial de las propias copias",
    "modelo_ml": "modelos de Machine Learning serializados: se vuelven a entrenar",
    "pedido_contratacion": "datos de compra previos a la empresa y hash de contraseña",
    "permiso": "catálogo del sistema que ningún dato de la empresa referencia",
    "probador_generacion": "caché regenerable del probador; guarda el hash de la foto del cliente",
    "rol_permiso": "catálogo del sistema que ningún dato de la empresa referencia",
    "transaccion_pasarela": "payloads de la pasarela de pagos: pueden traer tokens",
}

# Columnas que nunca salen, además de las generadas y de las que el patrón de abajo reconoce.
COLUMNAS_EXCLUIDAS: dict[str, tuple[str, ...]] = {
    "usuario": ("password_hash",),
    "bitacora": ("ip",),
}

# Cualquier columna cuyo nombre parezca un secreto se omite aunque nadie la haya listado (defensa en profundidad).
PATRON_COLUMNA_SENSIBLE = re.compile(r"password|secret|token|clave|api_key|credencial|hash_|_hash")

_MARCA_TIEMPO_ZIP = (1980, 1, 1, 0, 0, 0)  # fija: el ZIP de dos copias iguales no cambia por la fecha de los miembros
_TAMANO_BLOQUE = 1000


# ---- Errores -----------------------------------------------------------------------------------------------------


class CopiaError(Exception):
    """Fallo al armar la copia. `codigo` es estable (va a la fila de historial y a la respuesta); el mensaje nunca
    lleva datos de la empresa."""

    codigo = "error_interno"


class CopiaDemasiadoGrandeError(CopiaError):
    codigo = "copia_demasiado_grande"


class CopiaTiempoAgotadoError(CopiaError):
    codigo = "copia_tiempo_agotado"


class ServidorOcupadoError(CopiaError):
    codigo = "servidor_ocupado"


class ColumnaNoSoportadaError(CopiaError):
    """Una columna binaria: no hay ninguna en las tablas incluidas, y si aparece la copia se detiene."""

    codigo = "columna_no_soportada"


# ---- Qué se copia ------------------------------------------------------------------------------------------------


def tablas_sin_clasificar() -> list[str]:
    """Tablas de `Base.metadata` que no están en EXACTAMENTE una categoría (o categorías que nombran tablas que no
    existen). Una lista vacía es lo único aceptable: la prueba G1 lo exige."""
    problemas: list[str] = []
    categorias = (set(TABLAS_INCLUIDAS), set(TABLAS_REFERENCIA), set(TABLAS_EXCLUIDAS))
    for nombre in sorted(Base.metadata.tables):
        veces = sum(nombre in categoria for categoria in categorias)
        if veces != 1:
            problemas.append(f"{nombre} (en {veces} categorías)")
    for categoria in categorias:
        problemas += [f"{nombre} (no existe)" for nombre in sorted(categoria - set(Base.metadata.tables))]
    return problemas


def _es_columna_copiable(columna: Column, tabla: str) -> bool:
    if columna.name in COLUMNAS_EXCLUIDAS.get(tabla, ()):
        return False
    if columna.computed is not None:  # p. ej. stock.cantidad_disponible: se recalcula, no se inserta
        return False
    return PATRON_COLUMNA_SENSIBLE.search(columna.name.lower()) is None


def columnas_copiadas(nombre: str) -> list[Column]:
    return [c for c in Base.metadata.tables[nombre].columns if _es_columna_copiable(c, nombre)]


def columnas_omitidas(nombre: str) -> list[str]:
    return [c.name for c in Base.metadata.tables[nombre].columns if not _es_columna_copiable(c, nombre)]


def descripcion_de_tablas() -> dict[str, Any]:
    """Lo que la copia incluye y lo que no (alimenta `GET /copias-seguridad/tablas` y el manifiesto)."""
    return {
        "incluidas": list(TABLAS_INCLUIDAS),
        "referencias": list(TABLAS_REFERENCIA),
        "excluidas": [{"tabla": t, "motivo": m} for t, m in sorted(TABLAS_EXCLUIDAS.items())],
        "columnas_excluidas": {
            t: omitidas for t in (*TABLAS_INCLUIDAS, *TABLAS_REFERENCIA) if (omitidas := columnas_omitidas(t))
        },
    }


def _filtro(nombre: str, tabla: Table, empresa_id: int) -> ColumnElement[bool] | None:
    """La condición EXPLÍCITA que deja solo lo de esta empresa. `None` = el catálogo global completo."""
    meta = Base.metadata.tables
    if nombre == "empresa":
        return tabla.c.id == empresa_id
    if nombre == "usuario_rol":
        usuarios = meta["usuario"]
        return tabla.c.usuario_id.in_(select(usuarios.c.id).where(usuarios.c.empresa_id == empresa_id))
    if nombre == "plan":
        suscripciones = meta["suscripcion"]
        return tabla.c.id.in_(select(suscripciones.c.plan_id).where(suscripciones.c.empresa_id == empresa_id))
    if nombre == "rol":
        usuarios, usuario_rol = meta["usuario"], meta["usuario_rol"]
        return tabla.c.id.in_(
            select(usuario_rol.c.rol_id).where(
                usuario_rol.c.usuario_id.in_(select(usuarios.c.id).where(usuarios.c.empresa_id == empresa_id))
            )
        )
    if nombre in _REFERENCIAS_COMPLETAS:
        return None
    return tabla.c.empresa_id == empresa_id


def consulta_de(nombre: str, empresa_id: int):
    """El SELECT (solo las columnas copiables, filtrado por empresa y ordenado por clave primaria: resultado
    determinista) de una tabla."""
    tabla = Base.metadata.tables[nombre]
    consulta = select(*columnas_copiadas(nombre))
    filtro = _filtro(nombre, tabla, empresa_id)
    if filtro is not None:
        consulta = consulta.where(filtro)
    return consulta.order_by(*tabla.primary_key.columns)


# ---- Serialización -----------------------------------------------------------------------------------------------


def _valor_json(valor: Any) -> Any:
    if valor is None or isinstance(valor, (bool, int, str)):
        return valor
    if isinstance(valor, float):
        return valor if math.isfinite(valor) else None
    if isinstance(valor, Decimal):
        return format(valor, "f")  # texto exacto: un float perdería centavos
    if isinstance(valor, (dt.datetime, dt.date, dt.time)):
        return valor.isoformat()
    if isinstance(valor, uuid.UUID):
        return str(valor)
    if isinstance(valor, (dict, list)):
        return valor
    if isinstance(valor, (bytes, bytearray, memoryview)):
        raise ColumnaNoSoportadaError("una columna binaria no se puede copiar")
    return str(valor)


def _linea(nombres: list[str], fila: Any) -> bytes:
    objeto = {nombre: _valor_json(valor) for nombre, valor in zip(nombres, fila, strict=True)}
    return json.dumps(objeto, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# ---- Concurrencia ------------------------------------------------------------------------------------------------

_bloqueo = threading.Lock()
_en_curso = 0


@contextmanager
def plaza_de_copia(maximo: int) -> Iterator[None]:
    """Tope global de copias a la vez en este proceso (el backend corre con un solo worker y arma el ZIP en RAM)."""
    global _en_curso
    with _bloqueo:
        if _en_curso >= maximo:
            raise ServidorOcupadoError("hay demasiadas copias en curso")
        _en_curso += 1
    try:
        yield
    finally:
        with _bloqueo:
            _en_curso -= 1


# ---- Generador ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ContenidoCopia:
    contenido: bytes
    checksum: str  # SHA-256 hexadecimal del ZIP completo
    tablas: dict[str, int]  # filas por tabla de datos (no incluye las referencias)
    manifiesto: dict[str, Any]


def leer_version_esquema(conexion: Connection) -> str | None:
    """La revisión de Alembic de la base, o None si la base no usa Alembic (las pruebas con SQLite)."""
    if not inspect(conexion).has_table("alembic_version"):
        return None
    versiones = table("alembic_version", column("version_num", String))
    return conexion.execute(select(versiones.c.version_num)).scalar()


def generar_copia(
    conexion: Connection,
    empresa_id: int,
    *,
    empresa: dict[str, str],
    plan_codigo: str | None,
    version_esquema: str | None,
    max_bytes: int,
    max_segundos: float,
    reloj: Callable[[], float] = time.monotonic,
    ahora: dt.datetime | None = None,
) -> ContenidoCopia:
    """Arma el ZIP de la empresa `empresa_id` y lo devuelve en memoria.

    `conexion` debería ofrecer una lectura coherente (en PostgreSQL, REPEATABLE READ: todas las tablas reflejan el
    mismo instante). `empresa` lleva solo `codigo` y `nombre`. Lanza `CopiaDemasiadoGrandeError` o
    `CopiaTiempoAgotadoError` si se pasa de los topes, sin entregar nada parcial.
    """
    inicio = reloj()
    buffer = io.BytesIO()
    entradas: dict[str, dict[str, Any]] = {}
    entradas_ref: dict[str, dict[str, Any]] = {}

    def comprobar_topes() -> None:
        if reloj() - inicio > max_segundos:
            raise CopiaTiempoAgotadoError("la copia tardó más de lo permitido")
        if buffer.tell() > max_bytes:
            raise CopiaDemasiadoGrandeError("la copia supera el tamaño permitido")

    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for carpeta, nombres, destino in (
            ("datos", TABLAS_INCLUIDAS, entradas),
            ("referencias", TABLAS_REFERENCIA, entradas_ref),
        ):
            for nombre in nombres:
                destino[nombre] = _escribir_tabla(zf, carpeta, nombre, empresa_id, conexion, comprobar_topes)

        manifiesto = _manifiesto(empresa, plan_codigo, version_esquema, entradas, entradas_ref, ahora)
        _escribir_miembro(zf, "manifest.json", json.dumps(manifiesto, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8"))

    contenido = buffer.getvalue()
    if len(contenido) > max_bytes:
        raise CopiaDemasiadoGrandeError("la copia supera el tamaño permitido")
    return ContenidoCopia(
        contenido=contenido,
        checksum=hashlib.sha256(contenido).hexdigest(),
        tablas={nombre: datos["filas"] for nombre, datos in entradas.items()},
        manifiesto=manifiesto,
    )


def _nuevo_miembro(nombre: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(nombre, date_time=_MARCA_TIEMPO_ZIP)
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _escribir_miembro(zf: zipfile.ZipFile, nombre: str, contenido: bytes) -> None:
    zf.writestr(_nuevo_miembro(nombre), contenido)


def _escribir_tabla(
    zf: zipfile.ZipFile,
    carpeta: str,
    nombre: str,
    empresa_id: int,
    conexion: Connection,
    comprobar_topes: Callable[[], None],
) -> dict[str, Any]:
    """Escribe `<carpeta>/<tabla>.json` por bloques (nunca la tabla entera en memoria) y devuelve su entrada del
    manifiesto: archivo, filas, sha256 de lo escrito y columnas."""
    nombres = [c.name for c in columnas_copiadas(nombre)]
    huella = hashlib.sha256()
    filas = 0
    ruta = f"{carpeta}/{nombre}.json"

    with zf.open(_nuevo_miembro(ruta), "w") as destino:

        def escribir(trozo: bytes) -> None:
            destino.write(trozo)
            huella.update(trozo)

        escribir(b"[")
        resultado = conexion.execution_options(stream_results=True).execute(consulta_de(nombre, empresa_id))
        try:
            for bloque in resultado.partitions(_TAMANO_BLOQUE):
                comprobar_topes()
                for fila in bloque:
                    escribir((b",\n" if filas else b"\n") + _linea(nombres, fila))
                    filas += 1
        finally:
            resultado.close()
        escribir(b"\n]" if filas else b"]")
    comprobar_topes()
    return {"archivo": ruta, "filas": filas, "sha256": huella.hexdigest(), "columnas": nombres}


def _manifiesto(
    empresa: dict[str, str],
    plan_codigo: str | None,
    version_esquema: str | None,
    tablas: dict[str, dict[str, Any]],
    referencias: dict[str, dict[str, Any]],
    ahora: dt.datetime | None,
) -> dict[str, Any]:
    momento = ahora or dt.datetime.now(dt.timezone.utc)
    return {
        "formato": FORMATO,
        "version_esquema": version_esquema,
        "generada_en": momento.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "empresa": {"codigo": empresa["codigo"], "nombre": empresa["nombre"]},
        "plan": {"codigo": plan_codigo},
        "tablas": tablas,
        "referencias": referencias,
        "excluidas": {
            "tablas": sorted(TABLAS_EXCLUIDAS),
            "columnas": {t: omitidas for t in (*TABLAS_INCLUIDAS, *TABLAS_REFERENCIA) if (omitidas := columnas_omitidas(t))},
        },
    }
