"""Multitenant: la empresa de la sesión, el filtro automático y el relleno de
`empresa_id` al insertar.

Infraestructura transversal (no es un paquete de negocio). Aquí vive lo único
que sabe en qué empresa se está trabajando:

- La empresa se guarda en `Session.info` (explícita por sesión; no depende de
  hilos, de async ni de variables de contexto, y se fija igual en una tarea en
  segundo plano o en una prueba). Solo este módulo la escribe.
- `EmpresaMixin` da la columna `empresa_id` (NOT NULL, FK, índice) a las tablas
  propias de cada empresa; `EmpresaOpcionalMixin` la da con NULL permitido
  (solo `usuario`: NULL = superadministrador de la plataforma). Ambos cuelgan
  de `TieneEmpresa`, la base que usa el filtro.
- FILTRO AUTOMÁTICO (`do_orm_execute`): toda consulta ORM (select, update y
  delete) que toque una clase `TieneEmpresa` recibe el predicado
  `empresa_id = <empresa de la sesión>`. FALLA CERRADO: sin empresa en la
  sesión la consulta no se ejecuta. Un recurso de otra empresa queda
  invisible, igual que uno inexistente (los casos de uso responden 404).
- ESCRITURA (`before_flush`): rellena `empresa_id` en los objetos nuevos con
  la empresa de la sesión y se niega a crear un registro en otra empresa.

Lo que el filtro NO cubre y cómo se cubre:
- SQL en texto (`text()`): `condicion_empresa(db)` da el fragmento y el
  parámetro. Una prueba recorre `app/` y falla si aparece `text(` fuera de la
  lista conocida.
- Objetos que ya están en el mapa de identidad de la sesión: `fijar_empresa`
  hace `expunge_all()` al cambiar de empresa, y en producción hay una sesión
  por petición.

Las FK se escriben como cadena ("empresa.id"): este módulo no importa ningún
paquete de negocio (`core` ← `plataforma`). La única excepción es la
dependencia `empresa_publica`, que importa `plataforma.politicas` de forma
diferida, igual que `core/security.py`. Fuera de este módulo, ningún paquete
fija ni cambia la empresa de la sesión.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from typing import Any, TypeVar

from fastapi import Depends, Request, status
from sqlalchemy import ForeignKey, Select, event
from sqlalchemy.orm import ORMExecuteState, Mapped, Session, mapped_column, with_loader_criteria
from sqlalchemy.sql import visitors

from app.core.database import get_db
from app.core.exceptions import DomainError, NoEncontradoError

logger = logging.getLogger(__name__)

CLAVE_EMPRESA = "empresa_id"
CLAVE_PLATAFORMA = "plataforma"
OPCION_SIN_FILTRO = "sin_filtro_empresa"

# Prefijo de las rutas de la tienda pública por empresa (D02, D10): la única
# fuente de empresa que no es el usuario autenticado.
PREFIJO_PUBLICO = "/api/v1/public/"
# Rutas públicas que NO son una tienda (no llevan `{codigo}`): la contratación de planes. El código `contratacion`
# está reservado (plataforma.politicas) para que ninguna empresa pueda tomar este segmento.
PREFIJO_CONTRATACION = "/api/v1/public/contratacion/"

# Las únicas tablas de empresa que se pueden consultar SIN empresa en la
# sesión (y solo con `sin_filtro`): el usuario al autenticarse (todavía no se
# sabe su empresa), la transacción de pasarela (el webhook no trae usuario) y
# la suscripción (el superadministrador). Por nombre de tabla para no importar
# los modelos desde `core`.
TABLAS_SIN_ALCANCE = frozenset({"usuario", "transaccion_pasarela", "suscripcion"})

T = TypeVar("T")


class EmpresaNoDefinidaError(DomainError):
    """Se operó sin empresa en la sesión. Es un error de programación (un
    punto de entrada olvidó fijarla); la API lo responde 401 genérico."""

    def __init__(self, mensaje: str = "Empresa no definida") -> None:
        super().__init__(mensaje, status_code=status.HTTP_401_UNAUTHORIZED)


class ModoPlataformaError(DomainError):
    """El superadministrador (sin empresa) intentó leer o escribir datos de
    negocio. Para operar sobre una empresa debe fijarla explícitamente."""

    def __init__(self, mensaje: str = "Operación no permitida para el superadministrador") -> None:
        super().__init__(mensaje, status_code=status.HTTP_403_FORBIDDEN)


class TieneEmpresa:
    """Marca común de las clases con `empresa_id`: sobre ella se aplica el
    filtro automático. No se usa directamente."""


class EmpresaMixin(TieneEmpresa):
    """Tabla propia de una empresa: `empresa_id` NOT NULL."""

    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresa.id"), nullable=False, index=True)


class EmpresaOpcionalMixin(TieneEmpresa):
    """Como `EmpresaMixin` pero con NULL permitido (superadministrador)."""

    empresa_id: Mapped[int | None] = mapped_column(ForeignKey("empresa.id"), nullable=True, index=True)


# ---- La empresa de la sesión ----


def fijar_empresa(db: Session, empresa_id: int | None) -> None:
    """Fija la empresa de la sesión. `None` la deja sin empresa.

    Si la sesión ya trabajaba con OTRA empresa se vacía el mapa de identidad
    (`expunge_all`) para no reutilizar objetos de la empresa anterior. Salir
    del modo plataforma también lo vacía."""
    actual = db.info.get(CLAVE_EMPRESA)
    if (actual is not None and actual != empresa_id) or (empresa_id is not None and en_modo_plataforma(db)):
        db.expunge_all()
    db.info.pop(CLAVE_PLATAFORMA, None)
    if empresa_id is None:
        db.info.pop(CLAVE_EMPRESA, None)
    else:
        db.info[CLAVE_EMPRESA] = empresa_id


def fijar_plataforma(db: Session) -> None:
    """Modo superadministrador: la sesión no tiene empresa y las tablas de
    negocio quedan cerradas (`ModoPlataformaError`) salvo que el caso de uso
    fije una empresa de forma explícita con `fijar_empresa`."""
    if db.info.get(CLAVE_EMPRESA) is not None:
        db.expunge_all()
    db.info.pop(CLAVE_EMPRESA, None)
    db.info[CLAVE_PLATAFORMA] = True


def en_modo_plataforma(db: Session) -> bool:
    return bool(db.info.get(CLAVE_PLATAFORMA))


def fijar_empresa_de_usuario(db: Session, usuario: Any) -> None:
    """Fija la empresa de la sesión según el usuario ya autenticado: la suya,
    o el modo plataforma si no tiene (superadministrador). Si el cambio vació
    el mapa de identidad, el usuario se vuelve a adjuntar a la sesión."""
    if usuario.empresa_id is None:
        fijar_plataforma(db)
    else:
        fijar_empresa(db, usuario.empresa_id)
    if usuario not in db:
        db.add(usuario)


def empresa_de(db: Session) -> int | None:
    """Empresa fijada en la sesión, o `None` si no tiene."""
    return db.info.get(CLAVE_EMPRESA)


def exigir_empresa(db: Session) -> int:
    """Empresa de la sesión; lanza si no hay (`ModoPlataformaError` en modo
    plataforma, `EmpresaNoDefinidaError` en cualquier otro caso)."""
    empresa_id = empresa_de(db)
    if empresa_id is None:
        if en_modo_plataforma(db):
            raise ModoPlataformaError()
        raise EmpresaNoDefinidaError()
    return empresa_id


def sin_filtro(consulta: Select) -> Select:
    """Marca una consulta para que NO reciba el filtro de empresa. Solo vale
    para `TABLAS_SIN_ALCANCE`; sobre cualquier otra tabla de empresa el evento
    lanza error. No usar en código de negocio."""
    return consulta.execution_options(**{OPCION_SIN_FILTRO: True})


def condicion_empresa(db: Session) -> tuple[str, dict[str, Any]]:
    """Fragmento y parámetros para SQL en texto sobre tablas o vistas de
    empresa: `("empresa_id = :empresa_id", {"empresa_id": 7})`. Lanza si la
    sesión no tiene empresa. Es lo único permitido para `text()` sobre datos
    de empresa."""
    return "empresa_id = :empresa_id", {"empresa_id": exigir_empresa(db)}


def por_cada_empresa(
    db: Session, ids_empresa: Iterable[int], tarea: Callable[[Session], T]
) -> list[T | None]:
    """Ejecuta `tarea(db)` una vez por empresa, con la empresa fijada. Una
    empresa que falla no frena a las demás: se revierte, se registra y su
    resultado queda en `None`. Al final la sesión queda sin empresa."""
    resultados: list[T | None] = []
    try:
        for empresa_id in ids_empresa:
            fijar_empresa(db, empresa_id)
            try:
                resultados.append(tarea(db))
            except Exception:
                db.rollback()
                logger.exception("Falló la tarea para la empresa %s", empresa_id)
                resultados.append(None)
    finally:
        fijar_empresa(db, None)
    return resultados


@contextmanager
def en_empresa(db: Session, empresa_id: int) -> Iterator[None]:
    """Trabaja DENTRO de `empresa_id` y al salir restaura lo que la sesión tenía
    (otra empresa, el modo plataforma o nada). Para el superadministrador, que
    opera sobre una empresa ajena en una operación acotada (alta del
    administrador o de una sucursal).

    Cambiar de empresa vacía el mapa de identidad: lo pendiente se vuelca antes
    (`flush`, sin confirmar) y los objetos cargados antes quedan desligados, así
    que hay que guardar los ids que hagan falta y volver a leer lo demás."""
    db.flush()
    plataforma = en_modo_plataforma(db)
    anterior = empresa_de(db)
    fijar_empresa(db, empresa_id)
    try:
        yield
        db.flush()
    finally:
        if plataforma:
            fijar_plataforma(db)
        else:
            fijar_empresa(db, anterior)


# Funciones que preparan los datos base de una empresa nueva (tallas,
# materiales, ciudades...). Cada paquete registra la suya al importarse, así
# `plataforma` no tiene que importar a `catalogo` (inversión de dependencia).
_inicializadores: list[Callable[[Session], None]] = []


def registrar_inicializador(funcion: Callable[[Session], None]) -> Callable[[Session], None]:
    """Registra `funcion(db)`: se ejecuta con la empresa ya fijada, es
    idempotente y no confirma (la transacción es de quien registra la empresa).
    Sirve de decorador."""
    if funcion not in _inicializadores:
        _inicializadores.append(funcion)
    return funcion


def inicializar_empresa(db: Session, empresa_id: int) -> None:
    """Corre todos los inicializadores registrados dentro de `empresa_id`."""
    with en_empresa(db, empresa_id):
        for funcion in list(_inicializadores):
            funcion(db)


# ---- El filtro automático ----


def _clases_del_enunciado(estado: ORMExecuteState) -> set[type]:
    """Las clases ORM que toca el enunciado. `all_mappers` solo trae las de
    las columnas pedidas: un `select(func.count()).select_from(Modelo)` o una
    subconsulta sobre otra tabla no aparecen ahí, así que se recorre también
    el árbol de la consulta buscando entidades anotadas (FROM, JOIN, WHERE)."""
    clases = {m.class_ for m in estado.all_mappers}
    for elemento in visitors.iterate(estado.statement):
        entidad = (getattr(elemento, "_annotations", None) or {}).get("parententity")
        if entidad is not None:
            clases.add(entidad.mapper.class_)
    return clases


@event.listens_for(Session, "do_orm_execute")
def _filtrar_por_empresa(estado: ORMExecuteState) -> None:
    if not (estado.is_select or estado.is_update or estado.is_delete):
        return
    clases = [c for c in _clases_del_enunciado(estado) if issubclass(c, TieneEmpresa)]
    if not clases:
        return  # solo tablas globales o SQL que el ORM no administra

    sesion = estado.session
    if estado.execution_options.get(OPCION_SIN_FILTRO):
        ajenas = [c.__name__ for c in clases if c.__table__.name not in TABLAS_SIN_ALCANCE]
        if ajenas:
            raise EmpresaNoDefinidaError(
                f"sin_filtro no está permitido sobre: {', '.join(sorted(ajenas))}"
            )
        return

    empresa_id = empresa_de(sesion)
    if empresa_id is None:
        exigir_empresa(sesion)  # lanza el error que corresponda
    # Un criterio por mixin (y no uno sobre `TieneEmpresa`): SQLAlchemy evalúa
    # la condición contra la clase base indicada, que debe tener la columna.
    estado.statement = estado.statement.options(
        with_loader_criteria(
            EmpresaMixin, lambda cls: cls.empresa_id == empresa_id, include_aliases=True
        ),
        with_loader_criteria(
            EmpresaOpcionalMixin, lambda cls: cls.empresa_id == empresa_id, include_aliases=True
        ),
    )


# ---- La escritura ----


@event.listens_for(Session, "before_flush")
def _rellenar_empresa(session: Session, flush_context, instances) -> None:
    de_la_sesion = empresa_de(session)
    for obj in session.new:
        if isinstance(obj, EmpresaMixin):
            if obj.empresa_id is None:
                obj.empresa_id = exigir_empresa(session)
            elif de_la_sesion is not None and obj.empresa_id != de_la_sesion:
                raise EmpresaNoDefinidaError(
                    f"{type(obj).__name__} con empresa_id={obj.empresa_id} en una sesión de la empresa {de_la_sesion}"
                )
            # Sesión sin empresa y empresa_id explícito: lo hace el
            # superadministrador al dar de alta una empresa (suscripción,
            # administrador). Se respeta el valor dado.
        elif isinstance(obj, EmpresaOpcionalMixin):
            if obj.empresa_id is None:
                # Sin empresa en la sesión queda en NULL (superadministrador).
                obj.empresa_id = de_la_sesion
            elif de_la_sesion is not None and obj.empresa_id != de_la_sesion:
                raise EmpresaNoDefinidaError(
                    f"{type(obj).__name__} con empresa_id={obj.empresa_id} en una sesión de la empresa {de_la_sesion}"
                )


# ---- La empresa de una petición pública ----


def empresa_publica(codigo: str, db: Session) -> int:
    """Fija la empresa de la sesión a partir del código de la ruta
    `/public/{codigo}/...`. Código inexistente o empresa inactiva: 404 igual
    (no se distingue una de otra)."""
    from app.plataforma import politicas as plataforma_politicas

    empresa = plataforma_politicas.obtener_empresa_por_codigo(db, codigo)
    if empresa is None or not empresa.activo:
        raise NoEncontradoError("Tienda no encontrada")
    fijar_empresa(db, empresa.id)
    return empresa.id


def contexto_empresa(request: Request, db: Session = Depends(get_db)) -> None:
    """Dependencia de aplicación (una sola, en `main.py`): en las rutas
    `/api/v1/public/{codigo}/...` fija la empresa desde el código de la tienda;
    en las demás la fija desde el token de la petición, si lo trae (las rutas
    que piden usuario la vuelven a comprobar con `get_current_user`)."""
    if request.url.path.startswith(PREFIJO_CONTRATACION):
        # Contratación pública (prueba gratuita y compra con PayPal): no es la tienda de ninguna empresa y crea una nueva. Se atiende
        # SIEMPRE como anónima: un token viejo que mande el navegador no fija empresa ni exige su suscripción.
        return
    codigo = request.path_params.get("codigo")
    if codigo is not None and request.url.path.startswith(PREFIJO_PUBLICO):
        empresa_publica(codigo, db)
        # La tienda de una empresa sin suscripción activa no opera (403), salvo
        # los datos públicos de la tienda (/public/{codigo}/tienda).
        from app.core.planes import ruta_exenta_de_suscripcion, verificar_suscripcion_activa

        if not ruta_exenta_de_suscripcion(request.url.path):
            verificar_suscripcion_activa(db, request)
        return
    from app.core.security import fijar_empresa_del_token

    fijar_empresa_del_token(request, db)
