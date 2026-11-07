"""Reloj en UTC: la única forma de pedir 'hoy' o 'ahora' en el backend, y los períodos
relativos ('este mes', 'últimos 3 meses') que los reportes resuelven con él."""

import calendar
import datetime as dt
from typing import Any

from app.core.exceptions import DomainError


def hoy_utc() -> dt.date:
    """La fecha de hoy en UTC, NO la local del proceso.

    Las columnas contra las que se comparan estos períodos (`venta.fecha`,
    `probador_generacion.creado_en`) se graban con `server_default=func.now()`,
    es decir en UTC. Tomar el límite con `dt.date.today()` (fecha local del
    proceso) corre la ventana de consulta respecto de los datos siempre que
    el servidor no esté en UTC: con el reloj en UTC-4, una venta cobrada
    después de las 20:00 obtiene una `fecha` del día siguiente y queda fuera
    del período "hasta hoy".

    Vive en core/tiempo.py, y no en cada caso de uso, porque la necesitan `periodo_reportes`
    (reportes), CU-23 (reporte por voz) y CU-11 (cupo diario del probador).
    """
    return dt.datetime.now(dt.timezone.utc).date()


ZONA_BOLIVIA = dt.timezone(dt.timedelta(hours=-4), "Bolivia")  # UTC-4 fijo, sin horario de verano


def ahora_bolivia() -> dt.datetime:
    """El instante actual en hora de Bolivia (con zona): para rotular los archivos que se
    descargan (E10). La base y el resto del backend siguen en UTC."""
    return dt.datetime.now(dt.timezone.utc).astimezone(ZONA_BOLIVIA)


def dia_bolivia(ahora: dt.datetime | None = None) -> tuple[dt.date, dt.datetime, dt.datetime]:
    """El día de hoy en Bolivia y sus límites como instantes UTC naive: `(fecha, desde, hasta)`, con `desde` incluido
    y `hasta` excluido. Sirve para decir "las ventas de hoy" contra `venta.fecha` (UTC): una venta de las 23:12 en
    Bolivia ya es del día siguiente en UTC, y cortar la fecha UTC la sacaría de hoy. `ahora` solo existe para las pruebas."""
    hoy = (ahora.astimezone(ZONA_BOLIVIA) if ahora is not None else ahora_bolivia()).date()
    inicio = dt.datetime.combine(hoy, dt.time.min, tzinfo=ZONA_BOLIVIA).astimezone(dt.timezone.utc).replace(tzinfo=None)
    return hoy, inicio, inicio + dt.timedelta(days=1)


def ahora_utc_naive() -> dt.datetime:
    """El instante actual en UTC como datetime naive (sin tzinfo).

    Para comparar contra las columnas TIMESTAMP WITHOUT TIME ZONE con
    `server_default=func.now()` (`venta.fecha`, `evento.creado_en`...): la
    base las guarda en UTC y SQLAlchemy las devuelve naive, así que restar o
    comparar contra `dt.datetime.now()` (hora local del proceso) desfasa el
    resultado el offset del servidor si no corre en UTC."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


# ---- Períodos relativos (reportes generativos, E09) ----------------------------------------
# Puras y con `hoy` inyectable: la IA solo dice "este_mes" o "ultimos_meses 3"; las fechas
# las calcula el backend. Todo período termina a más tardar hoy: nunca hay fechas futuras.

_MAX_DIAS_RANGO = 366
_ANIO_MINIMO, _ANIO_MAXIMO = 2000, 2100
# Un 29 de febrero sin año se busca hasta 8 años atrás: el bisiesto más lejano posible
# (2096 a 2104, porque 2100 no lo es).
_ANIOS_BUSQUEDA = 9


def inicio_de_semana(fecha: dt.date) -> dt.date:
    """El lunes de la semana (lunes a domingo) a la que pertenece `fecha`."""
    return fecha - dt.timedelta(days=fecha.weekday())


def restar_meses(fecha: dt.date, n: int) -> dt.date:
    """`fecha` menos `n` meses: el mismo día, o el último del mes si ese día no existe
    (31 de marzo - 1 mes = 28 o 29 de febrero). Con `n` negativo suma meses."""
    indice = fecha.year * 12 + (fecha.month - 1) - n
    anio, mes_cero = divmod(indice, 12)
    mes = mes_cero + 1
    return dt.date(anio, mes, min(fecha.day, calendar.monthrange(anio, mes)[1]))


def _numero(n: Any, minimo: int, maximo: int, unidad: str) -> int:
    if n is None:
        raise DomainError(f"Indica cuántos {unidad} quieres ver (entre {minimo} y {maximo}).")
    if isinstance(n, bool) or not isinstance(n, int) or not minimo <= n <= maximo:
        raise DomainError(f"La cantidad de {unidad} debe ser un número entre {minimo} y {maximo}.")
    return n


def _mes_valido(mes: Any) -> int:
    if mes is None:
        raise DomainError("Indica el mes (un número del 1 al 12).")
    if isinstance(mes, bool) or not isinstance(mes, int) or not 1 <= mes <= 12:
        raise DomainError("El mes debe ser un número del 1 al 12.")
    return mes


def _anio_valido(anio: Any) -> int:
    if isinstance(anio, bool) or not isinstance(anio, int) or not _ANIO_MINIMO <= anio <= _ANIO_MAXIMO:
        raise DomainError(f"El año debe estar entre {_ANIO_MINIMO} y {_ANIO_MAXIMO}.")
    return anio


def _partes_de_fecha(valor: Any, etiqueta: str) -> tuple[Any, Any, Any]:
    """(dia, mes, anio) de una fecha parcial: un `date`, una tupla (dia, mes[, anio]), un
    dict o cualquier objeto con atributos dia, mes y anio (p. ej. el esquema FechaParcial)."""
    if isinstance(valor, dt.date):
        return valor.day, valor.month, valor.year
    if isinstance(valor, (tuple, list)) and len(valor) in (2, 3):
        return valor[0], valor[1], valor[2] if len(valor) == 3 else None
    if isinstance(valor, dict):
        return valor.get("dia"), valor.get("mes"), valor.get("anio")
    if hasattr(valor, "dia") and hasattr(valor, "mes"):
        return valor.dia, valor.mes, getattr(valor, "anio", None)
    raise DomainError(f"Indica la fecha '{etiqueta}' con día y mes (el año es opcional).")


def _resolver_fecha_parcial(valor: Any, hoy: dt.date, etiqueta: str) -> dt.date:
    """Con año, esa fecha exacta; sin año, la más reciente que ya ocurrió (hoy incluido).
    Lanza DomainError si no existe en el calendario o si es futura."""
    if valor is None:
        raise DomainError(f"Falta la fecha '{etiqueta}' del rango.")
    dia, mes, anio = _partes_de_fecha(valor, etiqueta)
    mes = _mes_valido(mes)
    if isinstance(dia, bool) or not isinstance(dia, int) or not 1 <= dia <= 31:
        raise DomainError(f"El día de la fecha '{etiqueta}' debe ser un número del 1 al 31.")
    if anio is not None:
        anio = _anio_valido(anio)
        try:
            fecha = dt.date(anio, mes, dia)
        except ValueError:
            raise DomainError(f"La fecha {dia:02d}/{mes:02d}/{anio} no existe en el calendario.") from None
        if fecha > hoy:
            raise DomainError(
                f"La fecha {fecha:%d/%m/%Y} es futura: solo puedo reportar hasta hoy ({hoy:%d/%m/%Y})."
            )
        return fecha
    for anio_candidato in range(hoy.year, hoy.year - _ANIOS_BUSQUEDA, -1):
        try:
            candidata = dt.date(anio_candidato, mes, dia)
        except ValueError:
            continue
        if candidata <= hoy:
            return candidata
    raise DomainError(f"La fecha {dia:02d}/{mes:02d} no existe en el calendario.")


def resolver_periodo_relativo(
    tipo: str,
    *,
    n: int | None = None,
    mes: int | None = None,
    anio: int | None = None,
    desde: Any = None,
    hasta: Any = None,
    hoy: dt.date | None = None,
) -> tuple[dt.date, dt.date]:
    """(desde, hasta) inclusivos de un período relativo a `hoy` (por defecto `hoy_utc()`).
    `hasta` nunca es posterior a `hoy`. Tipos:

      hoy · ayer · esta_semana (lunes a hoy) · semana_pasada (lunes a domingo anteriores)
      este_mes · mes_pasado · este_anio · anio_pasado
      ultimos_dias n (1..366): n días terminando hoy
      ultimas_semanas n (1..104): desde el lunes de hace n-1 semanas hasta hoy
      ultimos_meses n (1..24): desde el día 1 del mes de hace n-1 meses hasta hoy ('últimos 3
        meses' = 2 meses completos más lo que va del actual)
      mes_calendario mes[, anio]: ese mes; sin año, el más reciente que ya empezó (septiembre
        en octubre de 2026 es septiembre de 2026; diciembre en septiembre de 2026 es 2025);
        un mes en curso se recorta a hoy
      rango_fechas desde, hasta: cada fecha es (dia, mes[, anio]), un `date`, un dict o un
        objeto con dia/mes/anio; sin año se toma la más reciente que no sea futura. Máximo
        366 días.

    Lanza DomainError (mensaje en español, listo para mostrar) con tipo desconocido, números
    fuera de rango, mes fuera de 1..12, fechas inexistentes o futuras, `desde` posterior a
    `hasta` y rangos de más de 366 días."""
    hoy = hoy or hoy_utc()
    if tipo == "hoy":
        return hoy, hoy
    if tipo == "ayer":
        ayer = hoy - dt.timedelta(days=1)
        return ayer, ayer
    if tipo == "esta_semana":
        return inicio_de_semana(hoy), hoy
    if tipo == "semana_pasada":
        lunes = inicio_de_semana(hoy)
        return lunes - dt.timedelta(days=7), lunes - dt.timedelta(days=1)
    if tipo == "este_mes":
        return hoy.replace(day=1), hoy
    if tipo == "mes_pasado":
        fin = hoy.replace(day=1) - dt.timedelta(days=1)
        return fin.replace(day=1), fin
    if tipo == "este_anio":
        return dt.date(hoy.year, 1, 1), hoy
    if tipo == "anio_pasado":
        return dt.date(hoy.year - 1, 1, 1), dt.date(hoy.year - 1, 12, 31)
    if tipo == "ultimos_dias":
        dias = _numero(n, 1, 366, "días")
        return hoy - dt.timedelta(days=dias - 1), hoy
    if tipo == "ultimas_semanas":
        semanas = _numero(n, 1, 104, "semanas")
        return inicio_de_semana(hoy) - dt.timedelta(weeks=semanas - 1), hoy
    if tipo == "ultimos_meses":
        meses = _numero(n, 1, 24, "meses")
        return restar_meses(hoy, meses - 1).replace(day=1), hoy
    if tipo == "mes_calendario":
        mes = _mes_valido(mes)
        if anio is None:
            anio = hoy.year if mes <= hoy.month else hoy.year - 1
        else:
            anio = _anio_valido(anio)
        inicio = dt.date(anio, mes, 1)
        if inicio > hoy:
            raise DomainError(
                f"El mes {mes:02d}/{anio} todavía no empieza: solo puedo reportar hasta hoy ({hoy:%d/%m/%Y})."
            )
        fin = dt.date(anio, mes, calendar.monthrange(anio, mes)[1])
        return inicio, min(fin, hoy)
    if tipo == "rango_fechas":
        inicio = _resolver_fecha_parcial(desde, hoy, "desde")
        fin = _resolver_fecha_parcial(hasta, hoy, "hasta")
        if inicio > fin:
            raise DomainError(
                f"El rango es inválido: la fecha inicial ({inicio:%d/%m/%Y}) es posterior a la final ({fin:%d/%m/%Y})."
            )
        if (fin - inicio).days + 1 > _MAX_DIAS_RANGO:
            raise DomainError(
                f"El rango es demasiado largo: el máximo es de {_MAX_DIAS_RANGO} días. Acórtalo o pide los últimos meses."
            )
        return inicio, fin
    raise DomainError(f"No reconozco el período '{tipo}'.")
