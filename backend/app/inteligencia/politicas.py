"""Soporte de `inteligencia` que el catálogo no numera como casos de uso:

- Registrar el historial de navegación no es un caso de uso (no tiene un
  actor que lo "haga" con un objetivo propio: es una traza que queda como
  efecto secundario de navegar, probar o comprar). Soporta CU-32
  (recomendar productos).
- Redactar la respuesta en lenguaje natural de CU-38 (reporte por comando de
  voz). Es una plantilla en español armada con las cifras reales del
  reporte: ningún dato del negocio sale a un tercero y ninguna cifra la
  inventa un modelo.
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from app.inteligencia.repository import HistorialNavegacionRepository
from app.inteligencia.schemas import EventoCrear
from app.reportes.schemas import (
    DashboardRespuesta,
    ReporteInventarioRespuesta,
    ReporteReservasRespuesta,
    ReporteVentasRespuesta,
)
from app.seguridad.politicas import obtener_perfil_cliente

historial_repo = HistorialNavegacionRepository()


def registrar_evento(db: Session, datos: EventoCrear, usuario) -> None:
    """POST /api/v1/ia/eventos. `usuario` es `None` en navegación anónima."""
    cliente_id = obtener_perfil_cliente(db, usuario.id).id if usuario else None
    historial_repo.crear(db, cliente_id, None, datos.producto_id, datos.variante_id, datos.tipo_evento)


# ---- Respuesta en lenguaje natural de CU-38 -----------------------------------------

ResultadoReporte = ReporteVentasRespuesta | ReporteInventarioRespuesta | ReporteReservasRespuesta | DashboardRespuesta

_AVISO_NO_ENTENDIDO = "No identifiqué qué reporte pedías, así que te muestro el resumen general. "


def _bs(valor: Decimal) -> str:
    """Bs 12.400,50: miles con punto, decimales con coma."""
    formateado = f"{Decimal(valor):,.2f}"  # 12,400.50
    return "Bs " + formateado.replace(",", "\0").replace(".", ",").replace("\0", ".")


def _fecha(fecha: dt.date) -> str:
    return fecha.strftime("%d/%m/%Y")


def _porcentaje(fraccion: float) -> str:
    """La tasa de conversión viene como fracción (0.25 = 25%)."""
    texto = f"{fraccion * 100:.1f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",") + "%"


def _cantidad(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _filtros(*, sucursal: str | None = None, categoria: str | None = None, canal: str | None = None) -> str:
    """Solo los filtros que ese reporte realmente aplicó, entre paréntesis."""
    partes = []
    if sucursal:
        partes.append(f"en {sucursal}")
    if categoria:
        partes.append(f"categoría {categoria}")
    if canal:
        partes.append(f"canal {canal}")
    return f" ({', '.join(partes)})" if partes else ""


def _texto_ventas(periodo: str, resultado: ReporteVentasRespuesta) -> str:
    resumen = resultado.resumen
    if resumen.transacciones == 0:
        return f"{periodo} no hubo ventas."
    texto = (
        f"{periodo} hubo {_cantidad(resumen.transacciones, 'venta', 'ventas')} por {_bs(resumen.total_ventas)}, "
        f"con un ticket promedio de {_bs(resumen.ticket_promedio)} y un margen bruto de {_bs(resumen.margen_bruto)}."
    )
    if resultado.top_productos:
        top = resultado.top_productos[0]
        texto += f" Lo más vendido fue {top.producto} ({_cantidad(top.cantidad_vendida, 'unidad', 'unidades')})."
    return texto


def _texto_inventario(inicio: str, resultado: ReporteInventarioRespuesta) -> str:
    if not resultado.consolidado:
        return f"{inicio} no hay existencias registradas."
    unidades = sum(fila.cantidad_disponible for fila in resultado.consolidado)
    variantes = len({fila.variante_id for fila in resultado.consolidado})
    valor = sum((fila.valor_total for fila in resultado.valuacion), Decimal("0"))
    bajo_minimo = len({fila.variante_id for fila in resultado.alertas})
    texto = (
        f"{inicio} hay {_cantidad(unidades, 'unidad disponible', 'unidades disponibles')} en "
        f"{_cantidad(variantes, 'variante', 'variantes')}, con un valor de inventario de {_bs(valor)}."
    )
    if bajo_minimo:
        texto += f" {_cantidad(bajo_minimo, 'variante está', 'variantes están')} por debajo del stock mínimo."
    else:
        texto += " Ninguna variante está por debajo del stock mínimo."
    return texto


def _texto_reservas(periodo: str, resultado: ReporteReservasRespuesta) -> str:
    total = sum(fila.cantidad for fila in resultado.por_estado)
    if total == 0:
        return f"{periodo} no hubo reservas."
    desglose = ", ".join(f"{fila.cantidad} {fila.nombre.lower()}" for fila in resultado.por_estado if fila.cantidad > 0)
    return (
        f"{periodo} hubo {_cantidad(total, 'reserva', 'reservas')} ({desglose}); "
        f"la tasa de conversión a venta fue de {_porcentaje(resultado.tasa_conversion)}."
    )


def _texto_dashboard(periodo: str, resultado: DashboardRespuesta) -> str:
    bajo_minimo = resultado.variantes_bajo_minimo
    alerta = (
        f"hay {_cantidad(bajo_minimo, 'variante', 'variantes')} por debajo del stock mínimo"
        if bajo_minimo
        else "ninguna variante está por debajo del stock mínimo"
    )
    return (
        f"{periodo} las ventas sumaron {_bs(resultado.ventas_del_periodo)} en "
        f"{_cantidad(resultado.transacciones, 'transacción', 'transacciones')} "
        f"(ticket promedio {_bs(resultado.ticket_promedio)}). El inventario vale {_bs(resultado.valor_inventario_total)} "
        f"y {alerta}. La tasa de conversión de reservas es de {_porcentaje(resultado.tasa_conversion_reservas)}."
    )


def redactar_respuesta_reporte(
    *,
    tipo_reporte: str,
    entendida: bool,
    desde: dt.date,
    hasta: dt.date,
    sucursal: str | None,
    categoria: str | None,
    canal: str | None,
    resultado: ResultadoReporte,
) -> str:
    """Para CU-38: convierte el reporte ya consultado en una respuesta en
    español. `entendida=False` (Groq falló, sin API key o tipo inválido)
    antepone el aviso de que se muestra el resumen general."""
    rango = f"El {_fecha(desde)}" if desde == hasta else f"Entre el {_fecha(desde)} y el {_fecha(hasta)}"
    if tipo_reporte == "ventas":
        texto = _texto_ventas(rango + _filtros(sucursal=sucursal, categoria=categoria, canal=canal), resultado)
    elif tipo_reporte == "inventario":
        texto = _texto_inventario("Al día de hoy" + _filtros(sucursal=sucursal), resultado)
    elif tipo_reporte == "reservas":
        texto = _texto_reservas(rango + _filtros(sucursal=sucursal), resultado)
    else:
        texto = _texto_dashboard(rango + _filtros(sucursal=sucursal), resultado)
    return texto if entendida else _AVISO_NO_ENTENDIDO + texto
