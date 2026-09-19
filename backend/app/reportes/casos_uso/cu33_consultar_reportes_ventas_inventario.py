"""CU-33 — Consultar reportes de ventas e inventario

Actor: Administrador.
Precondición: sesión con el permiso reportes.ver.
Postcondición: se consultan los reportes de ventas, inventario y reservas
de un período.

Caso de uso COMPUESTO: agrupa los tres reportes (antes tres CU separados
en el plan de 79; el catálogo de 43 los funde en uno). Este paquete SOLO
LEE: no escribe en ninguna tabla. Un encargado (sin alcance global) solo
ve su sucursal: ver organizacion.politicas.acotar_sucursal.
"""

from sqlalchemy.orm import Session

from app.core.deps import ParametrosPeriodo
from app.inventario.casos_uso.cu14_consultar_inventario_global import ConsultarInventarioGlobal
from app.organizacion import politicas as organizacion_politicas
from app.reportes.politicas import tasa_conversion, ticket_promedio
from app.reportes.schemas import (
    FilaReservasPorEstado,
    FilaTopProducto,
    FilaVentasDetalle,
    FilaVentasPorCanal,
    FilaVentasPorSucursal,
    ReporteInventarioRespuesta,
    ReporteReservasRespuesta,
    ReporteVentasRespuesta,
    ResumenVentas,
)
from app.reservas.politicas import reporte_reservas_por_estado
from app.ventas import politicas as ventas_politicas


class ConsultarReportesVentasInventario:
    def __init__(self) -> None:
        self._inventario = ConsultarInventarioGlobal()

    def ventas(
        self,
        db: Session,
        usuario_id: int,
        periodo: ParametrosPeriodo,
        sucursal_id: int | None = None,
        categoria_id: int | None = None,
        canal: str | None = None,
    ) -> ReporteVentasRespuesta:
        sucursal_id = organizacion_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        resumen_dict = ventas_politicas.reporte_ventas_resumen(db, periodo, sucursal_id, categoria_id, canal)
        resumen = ResumenVentas(
            transacciones=resumen_dict["transacciones"],
            total_ventas=resumen_dict["total_ventas"],
            margen_bruto=resumen_dict["margen_bruto"],
            ticket_promedio=ticket_promedio(resumen_dict["total_ventas"], resumen_dict["transacciones"]),
        )
        return ReporteVentasRespuesta(
            resumen=resumen,
            top_productos=[
                FilaTopProducto(**fila)
                for fila in ventas_politicas.reporte_ventas_top_productos(db, periodo, sucursal_id, categoria_id, canal)
            ],
            por_canal=[
                FilaVentasPorCanal(**fila)
                for fila in ventas_politicas.reporte_ventas_por_canal(db, periodo, sucursal_id, categoria_id)
            ],
            por_sucursal=[
                FilaVentasPorSucursal(**fila)
                for fila in ventas_politicas.reporte_ventas_por_sucursal(db, periodo, categoria_id, canal, sucursal_id)
            ],
            detalle=[
                FilaVentasDetalle(**fila)
                for fila in ventas_politicas.reporte_ventas_detalle(db, periodo, sucursal_id, categoria_id, canal)
            ],
        )

    def inventario(self, db: Session, usuario_id: int, sucursal_id: int | None = None) -> ReporteInventarioRespuesta:
        return ReporteInventarioRespuesta(
            consolidado=self._inventario.listar_consolidado(db, usuario_id, sucursal_id),
            alertas=self._inventario.listar_alertas(db, usuario_id, sucursal_id),
            valuacion=self._inventario.listar_valuacion(db, usuario_id, sucursal_id),
        )

    def reservas(
        self, db: Session, usuario_id: int, periodo: ParametrosPeriodo, sucursal_id: int | None = None
    ) -> ReporteReservasRespuesta:
        sucursal_id = organizacion_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        por_estado = reporte_reservas_por_estado(db, periodo, sucursal_id)
        ventas_con_reserva = ventas_politicas.contar_ventas_con_reserva(db, periodo, sucursal_id)
        return ReporteReservasRespuesta(
            por_estado=[FilaReservasPorEstado(**fila) for fila in por_estado],
            tasa_conversion=tasa_conversion(por_estado, ventas_con_reserva),
        )
