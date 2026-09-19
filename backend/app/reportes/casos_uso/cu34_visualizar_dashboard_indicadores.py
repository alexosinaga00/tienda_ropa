"""CU-34 — Visualizar indicadores empresariales

Actor: Administrador, Encargado de sucursal.
Precondición: sesión con el permiso reportes.ver.
Postcondición: se ven en un panel los indicadores del negocio del período
elegido: ventas, transacciones, ticket promedio, margen bruto, productos
más vendidos, ventas por canal y por sucursal, valor total del
inventario, variantes bajo mínimo, reservas por estado, conversión de
reservas a ventas y uso del probador virtual.
"""

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.deps import ParametrosPeriodo
from app.inventario.casos_uso.cu14_consultar_inventario_global import ConsultarInventarioGlobal
from app.organizacion import politicas as organizacion_politicas
from app.probador.politicas import reporte_uso_probador
from app.reportes.politicas import tasa_conversion, ticket_promedio
from app.reportes.schemas import (
    DashboardRespuesta,
    FilaReservasPorEstado,
    FilaTopProducto,
    FilaUsoProbador,
    FilaVentasPorCanal,
    FilaVentasPorSucursal,
)
from app.reservas.politicas import reporte_reservas_por_estado
from app.ventas import politicas as ventas_politicas

_CERO = Decimal("0")


class VisualizarDashboardIndicadores:
    def __init__(self) -> None:
        self._inventario = ConsultarInventarioGlobal()

    def ejecutar(
        self, db: Session, usuario_id: int, periodo: ParametrosPeriodo, sucursal_id: int | None = None
    ) -> DashboardRespuesta:
        # Un encargado ve solo su sucursal (también en "ventas por sucursal").
        sucursal_id = organizacion_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        resumen_dict = ventas_politicas.reporte_ventas_resumen(db, periodo, sucursal_id)
        top_productos = ventas_politicas.reporte_ventas_top_productos(db, periodo, sucursal_id, limite=5)
        por_canal = ventas_politicas.reporte_ventas_por_canal(db, periodo, sucursal_id)
        por_sucursal = ventas_politicas.reporte_ventas_por_sucursal(db, periodo, sucursal_id=sucursal_id)

        alertas = self._inventario.listar_alertas(db, usuario_id, sucursal_id)
        valuacion = self._inventario.listar_valuacion(db, usuario_id, sucursal_id)
        valor_inventario_total = sum((fila["valor_total"] for fila in valuacion), _CERO)

        por_estado = reporte_reservas_por_estado(db, periodo, sucursal_id)
        ventas_con_reserva = ventas_politicas.contar_ventas_con_reserva(db, periodo, sucursal_id)

        uso_probador = reporte_uso_probador(db, periodo)

        return DashboardRespuesta(
            desde=periodo.desde,
            hasta=periodo.hasta,
            ventas_del_periodo=resumen_dict["total_ventas"],
            transacciones=resumen_dict["transacciones"],
            ticket_promedio=ticket_promedio(resumen_dict["total_ventas"], resumen_dict["transacciones"]),
            margen_bruto=resumen_dict["margen_bruto"],
            top_productos=[FilaTopProducto(**fila) for fila in top_productos],
            ventas_por_canal=[FilaVentasPorCanal(**fila) for fila in por_canal],
            ventas_por_sucursal=[FilaVentasPorSucursal(**fila) for fila in por_sucursal],
            valor_inventario_total=valor_inventario_total,
            variantes_bajo_minimo=len(alertas),
            reservas_por_estado=[FilaReservasPorEstado(**fila) for fila in por_estado],
            tasa_conversion_reservas=tasa_conversion(por_estado, ventas_con_reserva),
            uso_probador=[FilaUsoProbador(**fila) for fila in uso_probador],
        )
