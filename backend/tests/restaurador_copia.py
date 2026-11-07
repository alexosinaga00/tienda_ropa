"""Restaurador SOLO DE PRUEBAS de las copias de seguridad (E22).

NO es código de producción y no hay endpoint de restauración: la restauración como función del sistema no
entra en esta etapa. Sirve para demostrar que una copia es COMPLETA y RECUPERABLE: carga el ZIP de una empresa
en otra empresa VACÍA (creada con `crear_empresa`: solo `empresa` y su `suscripcion`) y deja las herramientas
para comparar el origen con el resultado.

Reglas del restaurador (`restaurar_copia`):
- `empresa_id` es SIEMPRE el del destino; el del archivo se ignora.
- Ids nuevos (autoincrementales) con una tabla de equivalencias id_viejo -> id_nuevo por tabla. Los catálogos
  globales (`estado_*`, `metodo_pago`, `tipo_movimiento`) se resuelven por CÓDIGO y `rol` por NOMBRE con los
  archivos de `referencias/`.
- Orden de carga por dependencias FK (`Base.metadata.sorted_tables` restringido a las incluidas). `categoria`
  (autorreferencia) se carga en dos pasadas.
- Las columnas generadas (`stock.cantidad_disponible`) no se insertan: la base las recalcula.
- `empresa` y `suscripcion` del destino NO se tocan (no se restauran).
- Los usuarios quedan sin contraseña utilizable (`!sin-clave`: no es un hash bcrypt válido).
- Antes de cargar se verifica el SHA-256 de cada miembro, los conteos y las columnas del manifiesto; si algo no
  coincide se rechaza sin tocar la base. El destino debe estar VACÍO: si no lo está, se rechaza (nunca mezcla).
- Todo se carga en un SAVEPOINT y se confirma al final: si algo falla queda el destino como estaba.

Referencias blandas (sin llave foránea) que se remapean por tipo, DESPUÉS de cargar todo:
- `movimiento_inventario.referencia_id` según `referencia_tipo` (venta, venta_anulada, devolucion, recepcion,
  transferencia, sync_forzada). Un `referencia_tipo` libre (el que mande el cliente por `POST
  /inventario/movimientos`) o 'ajuste' NO se remapea.
- `notificacion.referencia_id` según `tipo` (reserva, reserva_preparada, envio, sincronizacion).
- `bitacora.entidad_id` según `entidad` (usuario, sesion, sucursal, empleado, venta, devolucion,
  movimiento_inventario, operacion_sync, empresa). NO se remapea el de rol, plan, suscripcion, bitacora, lote_sync,
  reporte*, cierre_caja, modelo_ml ni copia_seguridad.
- Ids dentro de JSON (`bitacora.datos`, `operacion_sync.payload` y `.resultado`): solo las claves de
  `CLAVES_JSON` (variante_id, venta_id, ...), a cualquier profundidad. `consulta_voz.filtros_json` NO se toca.

El checksum canónico (`checksums_canonicos`) quita la clave primaria, las llaves foráneas, `empresa_id` y las
columnas de referencia blanda de `COLUMNAS_BLANDAS` (sus ids cambian con el remapeo); esas se comprueban aparte,
con claves naturales, en `verificar_referencias_blandas`, y las llaves foráneas con `verificar_isomorfismo`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import uuid
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    Table,
    Time,
    TypeDecorator,
    Uuid,
    func,
    insert,
    null,
    select,
    update,
)
from sqlalchemy import JSON as TipoJSON
from sqlalchemy.orm import Session

from app.core import copias
from app.core.database import Base

HASH_INUTILIZABLE = "!sin-clave"
TABLAS_NO_RESTAURADAS = ("empresa", "suscripcion")

# Claves de JSON cuyo valor es un id de otra tabla (heurística del restaurador de pruebas).
CLAVES_JSON = {
    "variante_id": "producto_variante",
    "producto_id": "producto",
    "cliente_id": "cliente",
    "venta_id": "venta",
    "reserva_id": "reserva",
    "pago_id": "pago",
    "sucursal_id": "sucursal",
    "movimiento_id": "movimiento_inventario",
    "devolucion_id": "devolucion",
    "recepcion_id": "recepcion",
    "transferencia_id": "transferencia",
    "usuario_id": "usuario",
    "empleado_id": "empleado",
}
REF_MOVIMIENTO = {
    "venta": "venta",
    "venta_anulada": "venta",
    "devolucion": "devolucion",
    "recepcion": "recepcion",
    "transferencia": "transferencia",
    "sync_forzada": "operacion_sync",
}
REF_NOTIFICACION = {
    "reserva": "reserva",
    "reserva_preparada": "reserva",
    "envio": "venta",
    "sincronizacion": "operacion_sync",
    "pedido_diferido": "venta",  # el aviso de un pedido cobrado apunta a su venta
}
REF_BITACORA = {
    "usuario": "usuario",
    "sesion": "usuario",
    "sucursal": "sucursal",
    "empleado": "empleado",
    "venta": "venta",
    "devolucion": "devolucion",
    "movimiento_inventario": "movimiento_inventario",
    "operacion_sync": "operacion_sync",
    "empresa": "empresa",
}
# Columnas con referencias blandas: se excluyen del checksum canónico (ver el docstring del módulo).
COLUMNAS_BLANDAS: dict[str, tuple[str, ...]] = {
    "movimiento_inventario": ("referencia_id",),
    "notificacion": ("referencia_id",),
    "bitacora": ("entidad_id", "datos"),
    "operacion_sync": ("payload", "resultado"),
}
# Catálogos globales: clave natural con la que se resuelven en el destino.
CLAVE_NATURAL_REFERENCIA = {
    "estado_pago": "codigo",
    "estado_reserva": "codigo",
    "estado_venta": "codigo",
    "metodo_pago": "codigo",
    "tipo_movimiento": "codigo",
    "rol": "nombre",
}
# Clave natural de cada tabla, para comprobar las referencias blandas sin depender de los ids.
CLAVE_NATURAL = {
    "venta": "codigo",
    "devolucion": "codigo",
    "recepcion": "codigo",
    "transferencia": "codigo",
    "reserva": "codigo",
    "sucursal": "codigo",
    "usuario": "email",
    "operacion_sync": "operacion_id",
    "empleado": "usuario_id",  # se traduce por el correo del usuario (ver `_clave_natural`)
    "movimiento_inventario": "observacion",
}


class CopiaInvalidaError(Exception):
    """El ZIP no es una copia íntegra (miembros, SHA-256, conteos, columnas, tipos). No se tocó la base."""


class DestinoNoVacioError(Exception):
    """La empresa destino ya tiene datos: el restaurador nunca mezcla."""


@dataclass
class Paquete:
    manifiesto: dict[str, Any]
    datos: dict[str, list[dict[str, Any]]]
    referencias: dict[str, list[dict[str, Any]]]


@dataclass
class ResultadoRestauracion:
    filas: dict[str, int]  # filas cargadas por tabla (no incluye empresa ni suscripcion)
    equivalencias: dict[str, dict[Any, Any]]  # tabla -> {id_viejo: id_nuevo} (también catálogos y rol)
    blandas_sin_resolver: list[str] = field(default_factory=list)  # referencias blandas cuyo destino no vino en la copia
    blandas_remapeadas: dict[str, int] = field(default_factory=dict)  # columna -> cuántas se remapearon


# =================================================================================================
# Lectura y validación del ZIP (no toca la base)
# =================================================================================================


def leer_paquete(zip_bytes: bytes) -> Paquete:
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as error:
        raise CopiaInvalidaError(f"no es un ZIP: {error}") from None
    with zf:
        if zf.testzip() is not None:
            raise CopiaInvalidaError("el ZIP tiene un miembro dañado")
        nombres = set(zf.namelist())
        if "manifest.json" not in nombres:
            raise CopiaInvalidaError("falta manifest.json")
        manifiesto = json.loads(zf.read("manifest.json"))
        if manifiesto.get("formato") != copias.FORMATO:
            raise CopiaInvalidaError(f"formato desconocido: {manifiesto.get('formato')!r}")
        if set(manifiesto["tablas"]) != set(copias.TABLAS_INCLUIDAS):
            raise CopiaInvalidaError("las tablas del manifiesto no son las incluidas")
        if set(manifiesto["referencias"]) != set(copias.TABLAS_REFERENCIA):
            raise CopiaInvalidaError("las referencias del manifiesto no son las esperadas")

        esperados = {"manifest.json"}
        cargado: dict[str, dict[str, list[dict[str, Any]]]] = {"tablas": {}, "referencias": {}}
        for grupo in ("tablas", "referencias"):
            for tabla, entrada in manifiesto[grupo].items():
                archivo = entrada["archivo"]
                esperados.add(archivo)
                if archivo not in nombres:
                    raise CopiaInvalidaError(f"falta {archivo}")
                contenido = zf.read(archivo)
                if hashlib.sha256(contenido).hexdigest() != entrada["sha256"]:
                    raise CopiaInvalidaError(f"SHA-256 distinto en {archivo}")
                filas = json.loads(contenido)
                if len(filas) != entrada["filas"]:
                    raise CopiaInvalidaError(f"{archivo}: el manifiesto dice {entrada['filas']} filas y hay {len(filas)}")
                for fila in filas:
                    if sorted(fila) != sorted(entrada["columnas"]):
                        raise CopiaInvalidaError(f"{archivo}: una fila no tiene las columnas del manifiesto")
                cargado[grupo][tabla] = filas
        if nombres != esperados:
            raise CopiaInvalidaError(f"miembros inesperados: {sorted(nombres - esperados)}")
    return Paquete(manifiesto=manifiesto, datos=cargado["tablas"], referencias=cargado["referencias"])


# =================================================================================================
# Conversión de tipos
# =================================================================================================


def _tipo_base(columna: Column) -> Any:
    tipo = columna.type
    while isinstance(tipo, TypeDecorator):
        tipo = tipo.impl
        if isinstance(tipo, type):
            tipo = tipo()
    return tipo


def convertir_valor(columna: Column, valor: Any, contexto: str) -> Any:
    """Convierte lo que trae el JSON al tipo Python de la columna, validándolo."""
    if valor is None:
        return None
    tipo = _tipo_base(columna)

    def malo() -> CopiaInvalidaError:
        return CopiaInvalidaError(f"{contexto}: valor {valor!r} no sirve para {type(tipo).__name__}")

    if isinstance(tipo, Boolean):
        if not isinstance(valor, bool):
            raise malo()
        return valor
    if isinstance(tipo, Integer):
        if isinstance(valor, bool) or not isinstance(valor, int):
            raise malo()
        return valor
    if isinstance(tipo, Float):
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            raise malo()
        return float(valor)
    if isinstance(tipo, Numeric):
        if not isinstance(valor, str):  # la copia guarda los Decimal como texto exacto
            raise malo()
        try:
            return Decimal(valor)
        except InvalidOperation:
            raise malo() from None
    if isinstance(tipo, DateTime):
        try:
            momento = dt.datetime.fromisoformat(valor)
        except (TypeError, ValueError):
            raise malo() from None
        if tipo.timezone and momento.tzinfo is None:
            return momento.replace(tzinfo=dt.timezone.utc)
        if not tipo.timezone and momento.tzinfo is not None:
            return momento.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return momento
    if isinstance(tipo, Date):
        try:
            return dt.date.fromisoformat(valor)
        except (TypeError, ValueError):
            raise malo() from None
    if isinstance(tipo, Time):
        try:
            return dt.time.fromisoformat(valor)
        except (TypeError, ValueError):
            raise malo() from None
    if isinstance(tipo, Uuid):
        try:
            return uuid.UUID(valor)
        except (TypeError, ValueError, AttributeError):
            raise malo() from None
    if isinstance(tipo, TipoJSON):
        return valor
    if isinstance(tipo, String):
        if not isinstance(valor, str):
            raise malo()
        return valor
    raise CopiaInvalidaError(f"{contexto}: tipo de columna no soportado {type(tipo).__name__}")


# =================================================================================================
# Restauración
# =================================================================================================


def _tablas_en_orden() -> list[Table]:
    return [t for t in Base.metadata.sorted_tables if t.name in copias.TABLAS_INCLUIDAS]


def _fk_de(columna: Column):
    return next(iter(columna.foreign_keys)) if columna.foreign_keys else None


def _es_id_generado(tabla: Table) -> bool:
    llaves = list(tabla.primary_key.columns)
    return len(llaves) == 1 and not llaves[0].foreign_keys


def _exigir_destino_vacio(conexion, empresa_destino_id: int) -> None:
    empresa = Base.metadata.tables["empresa"]
    if conexion.execute(select(empresa.c.id).where(empresa.c.id == empresa_destino_id)).first() is None:
        raise DestinoNoVacioError(f"la empresa destino {empresa_destino_id} no existe")
    con_datos: list[str] = []
    for nombre in copias.TABLAS_INCLUIDAS:
        if nombre in TABLAS_NO_RESTAURADAS:
            continue
        tabla = Base.metadata.tables[nombre]
        if nombre == "usuario_rol":
            usuario = Base.metadata.tables["usuario"]
            consulta = select(func.count()).select_from(tabla).where(
                tabla.c.usuario_id.in_(select(usuario.c.id).where(usuario.c.empresa_id == empresa_destino_id))
            )
        else:
            consulta = select(func.count()).select_from(tabla).where(tabla.c.empresa_id == empresa_destino_id)
        if conexion.execute(consulta).scalar_one():
            con_datos.append(nombre)
    if con_datos:
        raise DestinoNoVacioError(f"la empresa destino ya tiene datos en: {', '.join(con_datos)}")


def _mapa_de_referencias(conexion, paquete: Paquete) -> dict[str, dict[Any, Any]]:
    """id del archivo -> id del destino, buscando por código (catálogos) o por nombre (rol)."""
    mapa: dict[str, dict[Any, Any]] = {}
    for nombre, clave in CLAVE_NATURAL_REFERENCIA.items():
        tabla = Base.metadata.tables[nombre]
        destino = {fila[0]: fila[1] for fila in conexion.execute(select(tabla.c[clave], tabla.c.id))}
        mapa[nombre] = {}
        for fila in paquete.referencias[nombre]:
            if fila[clave] not in destino:
                raise CopiaInvalidaError(f"la referencia {nombre}.{clave}={fila[clave]!r} no existe en el destino")
            mapa[nombre][fila["id"]] = destino[fila[clave]]
    return mapa


def _remapear_json(valor: Any, equivalencias: dict[str, dict[Any, Any]], sin_resolver: list[str], donde: str) -> Any:
    if isinstance(valor, dict):
        salida = {}
        for clave, interior in valor.items():
            tabla = CLAVES_JSON.get(clave)
            if tabla is not None and isinstance(interior, int) and not isinstance(interior, bool):
                nuevo = equivalencias.get(tabla, {}).get(interior)
                if nuevo is None:
                    sin_resolver.append(f"{donde}.{clave}={interior}")
                salida[clave] = interior if nuevo is None else nuevo
            else:
                salida[clave] = _remapear_json(interior, equivalencias, sin_resolver, donde)
        return salida
    if isinstance(valor, list):
        return [_remapear_json(elemento, equivalencias, sin_resolver, donde) for elemento in valor]
    return valor


def restaurar_copia(zip_bytes: bytes, db: Session, empresa_destino_id: int) -> ResultadoRestauracion:
    paquete = leer_paquete(zip_bytes)  # 1. íntegro o nada (no toca la base)
    conexion = db.connection()
    _exigir_destino_vacio(conexion, empresa_destino_id)  # 2. nunca mezcla (solo lee)
    equivalencias: dict[str, dict[Any, Any]] = _mapa_de_referencias(conexion, paquete)
    filas_listas = _convertir_todo(paquete)  # 3. tipos validados antes de escribir nada

    resultado = ResultadoRestauracion(filas={}, equivalencias=equivalencias)
    try:
        with db.begin_nested():  # 4. una sola unidad: o todo o nada
            blandas = _cargar(conexion, filas_listas, empresa_destino_id, equivalencias, resultado)
            _remapear_blandas(conexion, blandas, equivalencias, resultado, empresa_destino_id)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return resultado


def _convertir_todo(paquete: Paquete) -> dict[str, list[dict[str, Any]]]:
    convertidas: dict[str, list[dict[str, Any]]] = {}
    for tabla in _tablas_en_orden():
        if tabla.name in TABLAS_NO_RESTAURADAS:
            continue
        columnas = copias.columnas_copiadas(tabla.name)
        lista = []
        for numero, fila in enumerate(paquete.datos[tabla.name]):
            lista.append(
                {c.name: convertir_valor(c, fila[c.name], f"{tabla.name}[{numero}].{c.name}") for c in columnas}
            )
        convertidas[tabla.name] = lista
    return convertidas


def _cargar(conexion, filas_listas, destino: int, equivalencias, resultado) -> dict[str, list[tuple[Any, dict]]]:
    blandas: dict[str, list[tuple[Any, dict]]] = {t: [] for t in COLUMNAS_BLANDAS}
    for tabla in _tablas_en_orden():
        nombre = tabla.name
        if nombre in TABLAS_NO_RESTAURADAS:
            continue
        columnas = copias.columnas_copiadas(nombre)
        generado = _es_id_generado(tabla)
        llave = next(iter(tabla.primary_key.columns))
        autorreferencias = [c for c in columnas if (fk := _fk_de(c)) is not None and fk.column.table is tabla]
        equivalencias.setdefault(nombre, {})
        pendientes_autorref: list[tuple[Any, str, Any]] = []

        for fila in filas_listas[nombre]:
            valores: dict[str, Any] = {}
            for columna in columnas:
                valor = fila[columna.name]
                fk = _fk_de(columna)
                if columna.name == "empresa_id":
                    valor = destino
                elif generado and columna is llave:
                    continue  # id nuevo: lo da la base
                elif columna in autorreferencias:
                    if valor is not None:
                        pendientes_autorref.append((fila[llave.name], columna.name, valor))
                    valor = None
                elif fk is not None and valor is not None:
                    padre = fk.column.table.name
                    if padre == "empresa":
                        valor = destino
                    elif valor in equivalencias.get(padre, {}):
                        valor = equivalencias[padre][valor]
                    else:
                        raise CopiaInvalidaError(f"{nombre}.{columna.name}: el id {valor} no existe en {padre}")
                if valor is None and isinstance(_tipo_base(columna), TipoJSON):
                    valor = null()
                valores[columna.name] = valor
            if nombre == "usuario":
                valores["password_hash"] = HASH_INUTILIZABLE

            if generado:
                nuevo = conexion.execute(insert(tabla).values(**valores).returning(llave)).scalar_one()
                equivalencias[nombre][fila[llave.name]] = nuevo
            else:
                conexion.execute(insert(tabla).values(**valores))
                nuevo = None
            resultado.filas[nombre] = resultado.filas.get(nombre, 0) + 1
            if nombre in blandas:
                blandas[nombre].append((nuevo, fila))

        for viejo, columna, padre_viejo in pendientes_autorref:  # segunda pasada: la autorreferencia
            if padre_viejo not in equivalencias[nombre]:
                raise CopiaInvalidaError(f"{nombre}.{columna}: el padre {padre_viejo} no vino en la copia")
            conexion.execute(
                update(tabla)
                .where(llave == equivalencias[nombre][viejo])
                .values({columna: equivalencias[nombre][padre_viejo]})
            )
        resultado.filas.setdefault(nombre, 0)
    return blandas


def _remapear_blandas(conexion, blandas, equivalencias, resultado, destino: int) -> None:
    equivalencias.setdefault("empresa", {})

    def contar(clave: str) -> None:
        resultado.blandas_remapeadas[clave] = resultado.blandas_remapeadas.get(clave, 0) + 1

    def resolver(tabla: str, objetivo: str | None, viejo: Any, donde: str) -> Any:
        if objetivo is None or viejo is None:
            return viejo
        nuevo = destino if objetivo == "empresa" else equivalencias.get(objetivo, {}).get(viejo)
        if nuevo is None:
            resultado.blandas_sin_resolver.append(f"{donde}={viejo} ({objetivo})")
            return viejo
        contar(donde)
        return nuevo

    for nombre, lista in blandas.items():
        tabla = Base.metadata.tables[nombre]
        for nuevo_id, fila in lista:
            cambios: dict[str, Any] = {}
            if nombre == "movimiento_inventario":
                valor = resolver(nombre, REF_MOVIMIENTO.get(fila["referencia_tipo"]), fila["referencia_id"], "movimiento_inventario.referencia_id")
                cambios["referencia_id"] = valor
            elif nombre == "notificacion":
                valor = resolver(nombre, REF_NOTIFICACION.get(fila["tipo"]), fila["referencia_id"], "notificacion.referencia_id")
                cambios["referencia_id"] = valor
            elif nombre == "bitacora":
                cambios["entidad_id"] = resolver(
                    nombre, REF_BITACORA.get(fila["entidad"]), fila["entidad_id"], "bitacora.entidad_id"
                )
                if fila["datos"] is not None:
                    cambios["datos"] = _remapear_json(fila["datos"], equivalencias, resultado.blandas_sin_resolver, "bitacora.datos")
            elif nombre == "operacion_sync":
                for columna in ("payload", "resultado"):
                    if fila[columna] is not None:
                        cambios[columna] = _remapear_json(
                            fila[columna], equivalencias, resultado.blandas_sin_resolver, f"operacion_sync.{columna}"
                        )
            originales = {c: fila[c] for c in cambios}
            cambios = {c: v for c, v in cambios.items() if v != originales[c]}
            if cambios:
                conexion.execute(update(tabla).where(tabla.c.id == nuevo_id).values(**cambios))


# =================================================================================================
# Comparaciones (sobre dos ZIP: el de la empresa origen y el de la empresa restaurada)
# =================================================================================================


def columnas_canonicas(tabla: str, columnas: list[str]) -> list[str]:
    """Columnas del checksum canónico: sin clave primaria, llaves foráneas, `empresa_id` ni referencias blandas."""
    t = Base.metadata.tables[tabla]
    fuera = {c.name for c in t.columns if c.primary_key or c.foreign_keys}
    fuera |= {"empresa_id"} | set(COLUMNAS_BLANDAS.get(tabla, ()))
    return [c for c in columnas if c not in fuera]


def _canonico(filas: list[dict[str, Any]], columnas: list[str]) -> tuple[int, str]:
    lineas = sorted(json.dumps({c: f[c] for c in columnas}, sort_keys=True, ensure_ascii=False) for f in filas)
    return len(lineas), hashlib.sha256("\n".join(lineas).encode("utf-8")).hexdigest()


def checksums_canonicos(zip_bytes: bytes) -> dict[str, tuple[int, str]]:
    """{tabla: (filas, sha256)} de todas las tablas restaurables (sin `empresa` ni `suscripcion`)."""
    paquete = leer_paquete(zip_bytes)
    resultado = {}
    for tabla, filas in paquete.datos.items():
        if tabla in TABLAS_NO_RESTAURADAS:
            continue
        columnas = columnas_canonicas(tabla, paquete.manifiesto["tablas"][tabla]["columnas"])
        resultado[tabla] = _canonico(filas, columnas)
    return resultado


def verificar_isomorfismo(zip_origen: bytes, zip_destino: bytes, resultado: ResultadoRestauracion, destino_id: int) -> list[str]:
    """Cada fila del origen, con su clave primaria y sus llaves foráneas traducidas por las equivalencias,
    debe existir idéntica en el destino (y no sobrar ninguna). Devuelve las diferencias (vacío = igual).
    Las columnas de referencia blanda se saltan (las cubre `verificar_referencias_blandas`)."""
    origen, destino = leer_paquete(zip_origen), leer_paquete(zip_destino)
    problemas: list[str] = []
    for nombre, filas in origen.datos.items():
        if nombre in TABLAS_NO_RESTAURADAS:
            continue
        tabla = Base.metadata.tables[nombre]
        columnas = [c for c in origen.manifiesto["tablas"][nombre]["columnas"] if c not in COLUMNAS_BLANDAS.get(nombre, ())]

        def traducir(fila: dict[str, Any]) -> str:
            salida = {}
            for c in columnas:
                valor = fila[c]
                columna = tabla.c[c]
                fk = _fk_de(columna)
                if c == "empresa_id":
                    valor = destino_id
                elif fk is not None and valor is not None:
                    padre = fk.column.table.name
                    valor = destino_id if padre == "empresa" else resultado.equivalencias[padre][valor]
                elif columna.primary_key and _es_id_generado(tabla):
                    valor = resultado.equivalencias[nombre][valor]
                salida[c] = valor
            return json.dumps(salida, sort_keys=True, ensure_ascii=False)

        esperado = sorted(traducir(f) for f in filas)
        real = sorted(
            json.dumps({c: f[c] for c in columnas}, sort_keys=True, ensure_ascii=False) for f in destino.datos[nombre]
        )
        if esperado != real:
            faltan = [x for x in esperado if x not in real]
            sobran = [x for x in real if x not in esperado]
            problemas.append(f"{nombre}: faltan {len(faltan)} y sobran {len(sobran)} filas respecto al origen traducido")
    return problemas


def _clave_natural(paquete: Paquete, tabla: str, id_: Any) -> Any:
    if id_ is None:
        return None
    por_id = {f["id"]: f for f in paquete.datos[tabla]}
    fila = por_id.get(id_)
    if fila is None:
        return ("<sin fila>", tabla)
    if tabla == "empleado":
        usuario = {f["id"]: f for f in paquete.datos["usuario"]}[fila["usuario_id"]]
        return usuario["email"]
    if tabla == "movimiento_inventario":
        return (fila["referencia_tipo"], fila["observacion"], fila["cantidad"], fila["creado_en"])
    return fila[CLAVE_NATURAL[tabla]]


def verificar_referencias_blandas(zip_origen: bytes, zip_destino: bytes, resultado: ResultadoRestauracion) -> dict[str, int]:
    """Comprueba con CLAVES NATURALES (código de venta, correo, ...) que cada referencia blanda de la empresa
    restaurada apunta a la misma cosa que la del origen, sin usar los ids. Devuelve cuántas se verificaron por
    columna; lanza AssertionError con la primera que no coincide."""
    origen, destino = leer_paquete(zip_origen), leer_paquete(zip_destino)
    verificadas: dict[str, int] = {}

    def comprobar(tabla: str, columna: str, objetivo_de, campo_id: str) -> None:
        equivalencia = resultado.equivalencias[tabla]
        destino_por_id = {f["id"]: f for f in destino.datos[tabla]}
        for fila in origen.datos[tabla]:
            objetivo = objetivo_de(fila)
            if objetivo is None or fila[campo_id] is None:
                continue
            fila_destino = destino_por_id[equivalencia[fila["id"]]]
            esperado = _clave_natural(origen, objetivo, fila[campo_id])
            real = _clave_natural(destino, objetivo, fila_destino[campo_id])
            assert esperado == real, f"{tabla}.{columna} de {fila['id']}: {esperado!r} != {real!r}"
            verificadas[f"{tabla}.{columna}:{objetivo}"] = verificadas.get(f"{tabla}.{columna}:{objetivo}", 0) + 1

    comprobar("movimiento_inventario", "referencia_id", lambda f: REF_MOVIMIENTO.get(f["referencia_tipo"]), "referencia_id")
    comprobar("notificacion", "referencia_id", lambda f: REF_NOTIFICACION.get(f["tipo"]), "referencia_id")
    comprobar(
        "bitacora", "entidad_id",
        lambda f: (o if (o := REF_BITACORA.get(f["entidad"])) not in (None, "empresa") else None), "entidad_id",
    )  # fmt: skip
    return verificadas


# =================================================================================================
# Consultas de apoyo sobre la base (R2, R4, R5)
# =================================================================================================


def conteos_por_tabla(conexion, empresa_id: int) -> dict[str, int]:
    """Filas de la empresa en cada tabla incluida restaurable (`usuario_rol` por su usuario)."""
    conteos = {}
    for nombre in copias.TABLAS_INCLUIDAS:
        if nombre in TABLAS_NO_RESTAURADAS:
            continue
        tabla = Base.metadata.tables[nombre]
        if nombre == "usuario_rol":
            usuario = Base.metadata.tables["usuario"]
            filtro = tabla.c.usuario_id.in_(select(usuario.c.id).where(usuario.c.empresa_id == empresa_id))
        else:
            filtro = tabla.c.empresa_id == empresa_id
        conteos[nombre] = conexion.execute(select(func.count()).select_from(tabla).where(filtro)).scalar_one()
    return conteos


def sumas_de_control(conexion, empresa_id: int) -> dict[str, Any]:
    """Cifras que no dependen de los ids: deben ser iguales en la empresa origen y en la restaurada."""
    t = Base.metadata.tables

    def suma(tabla: str, columna: str):
        valor = conexion.execute(
            select(func.coalesce(func.sum(t[tabla].c[columna]), 0)).where(t[tabla].c.empresa_id == empresa_id)
        ).scalar_one()
        return Decimal(str(valor))

    venta, detalle = t["venta"], t["venta_detalle"]
    por_venta = {
        codigo: cantidad
        for codigo, cantidad in conexion.execute(
            select(venta.c.codigo, func.count(detalle.c.id))
            .select_from(venta.outerjoin(detalle, detalle.c.venta_id == venta.c.id))
            .where(venta.c.empresa_id == empresa_id)
            .group_by(venta.c.codigo)
        )
    }
    return {
        "stock.cantidad_fisica": suma("stock", "cantidad_fisica"),
        "stock.cantidad_reservada": suma("stock", "cantidad_reservada"),
        "stock.cantidad_disponible": suma("stock", "cantidad_disponible"),  # columna generada: la recalcula la base
        "venta.total": suma("venta", "total"),
        "pago.monto": suma("pago", "monto"),
        "venta_detalle.subtotal": suma("venta_detalle", "subtotal"),
        "movimiento_inventario.cantidad": suma("movimiento_inventario", "cantidad"),
        "detalles_por_venta": por_venta,
    }


def inconsistencias_de_empresa(conexion, empresa_id: int) -> list[str]:
    """La consulta de consistencia de E05 (ninguna FK entre tablas de empresa apunta a otra empresa) filtrada
    por las filas HIJAS de `empresa_id`."""
    from tests.aislamiento.test_zz_consistencia_final import relaciones_entre_tablas_de_empresa

    problemas = []
    for hijo, columna, padre, columna_padre in relaciones_entre_tablas_de_empresa():
        h, p = hijo.alias("h"), padre.alias("p")
        cantidad = conexion.execute(
            select(func.count())
            .select_from(h.join(p, p.c[columna_padre] == h.c[columna]))
            .where(h.c.empresa_id == empresa_id, h.c.empresa_id != p.c.empresa_id)
        ).scalar_one()
        if cantidad:
            problemas.append(f"{hijo.name}.{columna} -> {padre.name}: {cantidad} fila(s)")
    return problemas


def reempaquetar(zip_bytes: bytes, cambios: dict[str, Any], *, recalcular_manifiesto: bool = True) -> bytes:
    """ZIP nuevo con cambios en miembros: `cambios[miembro]` es una función filas -> filas (para los JSON de
    tablas) o bytes (reemplazo literal). Con `recalcular_manifiesto` el manifiesto queda coherente con lo
    cambiado (SHA-256 y filas); sin él, el manifiesto conserva lo original (una copia alterada a escondidas)."""
    entrada = zipfile.ZipFile(io.BytesIO(zip_bytes))
    manifiesto = json.loads(entrada.read("manifest.json"))
    miembros = {nombre: entrada.read(nombre) for nombre in entrada.namelist()}
    for miembro, cambio in cambios.items():
        if callable(cambio):
            nuevas = cambio(json.loads(miembros[miembro]))
            miembros[miembro] = json.dumps(nuevas, sort_keys=True, ensure_ascii=False).encode("utf-8")
        else:
            miembros[miembro] = cambio
        if recalcular_manifiesto:
            for grupo in ("tablas", "referencias"):
                for entrada_tabla in manifiesto[grupo].values():
                    if entrada_tabla["archivo"] == miembro:
                        entrada_tabla["sha256"] = hashlib.sha256(miembros[miembro]).hexdigest()
                        entrada_tabla["filas"] = len(json.loads(miembros[miembro]))
    if "manifest.json" not in cambios:
        miembros["manifest.json"] = json.dumps(manifiesto, sort_keys=True, ensure_ascii=False).encode("utf-8")
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for nombre, contenido in miembros.items():
            zf.writestr(nombre, contenido)
    return salida.getvalue()


# =================================================================================================
# Datos que el universo de E05 no cubre
# =================================================================================================


def agregar_datos_extra(universo) -> dict[str, Any]:
    """Completa el `Universo` de E05 con lo que ejercita el restaurador: una categoría HIJA creada antes que su
    padre (id menor que el del padre: obliga a la segunda pasada de `categoria`), más productos, reservas,
    empleados y direcciones, y filas con referencias blandas de cada tipo. Devuelve los ids creados."""
    from app.catalogo.models import Categoria, MovimientoInventario, TipoMovimiento
    from app.comercial.models import PedidoDiferido
    from app.core.auditoria import ENTIDAD_VENTA
    from app.plataforma.models import Bitacora, Notificacion
    from app.sincronizacion.models import OperacionSync

    ids = universo.ids
    extra: dict[str, Any] = {}
    universo.nuevo("producto")
    universo.nuevo("reserva")
    universo.nuevo("empleado")
    universo.nuevo("direccion")
    universo.nuevo("proveedor")
    universo.nuevo("promocion")
    with universo.orm() as db:
        hijo = Categoria(nombre="Zeta hijo", descripcion="hijo antes que su padre")
        db.add(hijo)
        db.flush()
        padre = Categoria(nombre="Zeta padre", descripcion="padre despues del hijo")
        db.add(padre)
        db.flush()
        hijo.categoria_padre_id = padre.id  # el hijo tiene un id MENOR que el de su padre
        extra["categoria_hijo"], extra["categoria_padre"] = hijo.id, padre.id

        tipo = db.scalar(select(TipoMovimiento).where(TipoMovimiento.codigo == "ajuste_positivo"))
        libre = MovimientoInventario(
            variante_id=ids["variante"], sucursal_id=ids["sucursal"], tipo_movimiento_id=tipo.id, cantidad=1,
            saldo_post=1, referencia_tipo="externo_libre", referencia_id=987654, observacion=universo.m("mov-libre"),
        )  # fmt: skip
        db.add(libre)
        notificacion = Notificacion(
            usuario_id=universo.empresa.admin_id, titulo=universo.m("noti-reserva"), tipo="reserva",
            referencia_id=ids["reserva"],
        )  # fmt: skip
        bitacora = Bitacora(
            empresa_id=universo.id, usuario_id=universo.empresa.admin_id, entidad=ENTIDAD_VENTA,
            entidad_id=ids["venta"], accion="anular_pago", datos={"pago_id": ids["pago"], "estado_anterior": "pagada"},
        )  # fmt: skip
        sync = OperacionSync(
            sucursal_id=ids["sucursal"], usuario_id=universo.empresa.admin_id, operacion_id=uuid.uuid4(),
            tipo="venta_contado", estado="confirmada", motivo=None,
            payload={"cliente_id": ids["cliente"], "lineas": [{"variante_id": ids["variante"], "cantidad": 1}]},
            resultado={"venta_id": ids["venta"], "avisos": ["precio_distinto"], "ajustes": [{"variante_id": ids["variante"], "movimiento_id": ids["movimiento"]}]},
            fecha_operacion=dt.datetime(2026, 10, 2, 9, 30, 0), procesada_en=dt.datetime(2026, 10, 2, 9, 30, 5),
        )  # fmt: skip
        pedido = PedidoDiferido(
            operacion_id=uuid.uuid4(), usuario_id=universo.empresa.admin_id, sucursal_id=ids["sucursal"],
            estado="cobrado", venta_id=ids["venta"], total=Decimal("100.00"), total_usd=Decimal("14.37"),
            mensaje=universo.m("pedido-diferido"),
        )  # fmt: skip
        db.add_all([notificacion, bitacora, sync, pedido])
        db.flush()
        extra["movimiento_libre"] = libre.id
    return extra


def huerfanas_de_empresa(conexion, empresa_id: int) -> list[str]:
    """Filas de la empresa cuya llave foránea (no nula) no encuentra su fila padre. En PostgreSQL las restricciones
    ya lo impiden; en SQLite (sin `PRAGMA foreign_keys`) esta consulta es la comprobación."""
    problemas = []
    for tabla in Base.metadata.sorted_tables:
        if tabla.name not in copias.TABLAS_INCLUIDAS or tabla.name in TABLAS_NO_RESTAURADAS:
            continue
        if tabla.name == "usuario_rol":
            usuario = Base.metadata.tables["usuario"]
            filtro = tabla.c.usuario_id.in_(select(usuario.c.id).where(usuario.c.empresa_id == empresa_id))
        else:
            filtro = tabla.c.empresa_id == empresa_id
        for fk in tabla.foreign_keys:
            padre = fk.column.table.alias("padre")
            hijas = conexion.execute(
                select(func.count())
                .select_from(tabla.outerjoin(padre, padre.c[fk.column.name] == tabla.c[fk.parent.name]))
                .where(filtro, tabla.c[fk.parent.name].is_not(None), padre.c[fk.column.name].is_(None))
            ).scalar_one()
            if hijas:
                problemas.append(f"{tabla.name}.{fk.parent.name} -> {fk.column.table.name}: {hijas} fila(s) huérfana(s)")
    return problemas
