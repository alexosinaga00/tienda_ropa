import datetime as dt
from dataclasses import dataclass

from fastapi import Query

from app.core.exceptions import DomainError


@dataclass
class ParametrosPaginacion:
    pagina: int
    tamanio: int

    @property
    def offset(self) -> int:
        return (self.pagina - 1) * self.tamanio


def parametros_paginacion(
    pagina: int = Query(default=1, ge=1),
    tamanio: int = Query(default=20, ge=1, le=100),
) -> ParametrosPaginacion:
    return ParametrosPaginacion(pagina=pagina, tamanio=tamanio)


DIAS_PERIODO_POR_DEFECTO = 30


def hoy_utc() -> dt.date:
    """La fecha de hoy en UTC, NO la local del proceso.

    Las columnas contra las que se comparan estos períodos (`venta.fecha`,
    `probador_generacion.creado_en`) se graban con `server_default=func.now()`,
    es decir en UTC. Tomar el límite con `dt.date.today()` (fecha local del
    proceso) corre la ventana de consulta respecto de los datos siempre que
    el servidor no esté en UTC: con el reloj en UTC-4, una venta cobrada
    después de las 20:00 obtiene una `fecha` del día siguiente y queda fuera
    del período "hasta hoy".

    Vive acá, y no en cada caso de uso, porque la necesitan `periodo_reportes`
    (reportes), CU-38 (reporte por voz) y CU-39 (cupo diario del probador).
    """
    return dt.datetime.now(dt.timezone.utc).date()


@dataclass
class ParametrosPeriodo:
    desde: dt.date
    hasta: dt.date


def periodo_reportes(
    desde: dt.date | None = Query(default=None),
    hasta: dt.date | None = Query(default=None),
) -> ParametrosPeriodo:
    """Para `reportes` (P6.3): sin `desde`/`hasta` toma los últimos 30
    días. `desde` > `hasta` es un rango inválido, no un caso a tolerar."""
    hasta_final = hasta if hasta is not None else hoy_utc()
    desde_final = desde if desde is not None else hasta_final - dt.timedelta(days=DIAS_PERIODO_POR_DEFECTO)
    if desde_final > hasta_final:
        raise DomainError("El rango de fechas es inválido: 'desde' no puede ser posterior a 'hasta'")
    return ParametrosPeriodo(desde=desde_final, hasta=hasta_final)
