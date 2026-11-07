"""CU-22 — Consultar reportes e indicadores

Absorbe los antiguos CU-33 (Consultar reportes de ventas e inventario) y
CU-34 (Visualizar indicadores empresariales).

Actor: Administrador, Encargado de sucursal.
Precondición: sesión con el permiso reportes.ver.
Postcondición: se consultan los reportes de ventas, inventario y reservas
de un período y se ven en un panel los indicadores del negocio del período
elegido: ventas, transacciones, ticket promedio, margen bruto, productos
más vendidos, ventas por canal y por sucursal, valor total del inventario,
variantes bajo mínimo, reservas por estado, conversión de reservas a ventas
y uso del probador virtual.

Caso de uso COMPUESTO: agrupa los reportes (ventas, inventario, reservas) y
el dashboard de indicadores, cada uno con su propia clase. Este caso de uso
SOLO LEE: no escribe en ninguna tabla. Un encargado (sin alcance global) solo
ve su sucursal: ver plataforma.politicas.acotar_sucursal.

Descarga en Excel o PDF (E10, paso 8): `ExportarReportesVentasInventario` entrega los reportes de
ventas, inventario y reservas como archivo; solo agrega una fila de bitácora."""

import datetime as dt
import time
from decimal import Decimal

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.catalogo.casos_uso.cu06_consultar_buscar_catalogo import ConsultarCatalogo
from app.catalogo.casos_uso.cu09_gestionar_inventario import ConsultarInventarioGlobal
from app.catalogo.politicas import reporte_uso_probador
from app.comercial import politicas as comercial_politicas
from app.comercial.politicas import reporte_reservas_por_estado
from app.core.auditoria import ACCION_EXPORTAR, ENTIDAD_REPORTE, ContextoAuditoria
from app.core.deps import ParametrosPeriodo
from app.core.permisos import PERMISO_INVENTARIO_VER, PERMISO_STAFF_RESERVAS, PERMISO_STAFF_VENTAS
from app.core.planes import FUNC_GESTION_VENTAS, FUNC_RESERVAS, plan_incluye_funcionalidad
from app.core.tenant import exigir_empresa
from app.core.tiempo import ahora_bolivia, dia_bolivia
from app.inteligencia.exportacion import MAX_FILAS, TIPO_MIME, ArchivoExportado, construir_archivo
from app.inteligencia.exportacion_convencionales import documento_inventario, documento_reservas, documento_ventas
from app.inteligencia.politicas import etiqueta_periodo, tasa_conversion, ticket_promedio
from app.inteligencia.schemas import (
    AlertaStockInicio,
    DashboardRespuesta,
    FilaReservasPorEstado,
    FilaTopProducto,
    FilaUsoProbador,
    FilaVentasDetalle,
    FilaVentasPorCanal,
    FilaVentasPorSucursal,
    PrendaVendidaInicio,
    ReporteInventarioRespuesta,
    ReporteReservasRespuesta,
    ReporteVentasRespuesta,
    ResumenInicioRespuesta,
    ResumenReservasInicio,
    ResumenStockInicio,
    ResumenVentas,
    ResumenVentasInicio,
    VentaRecienteInicio,
)
from app.plataforma import politicas as plataforma_politicas

_CERO = Decimal("0")


# ---- Reportes de ventas, inventario y reservas (antiguo CU-33) ----


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
        sucursal_id = plataforma_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        resumen_dict = comercial_politicas.reporte_ventas_resumen(db, periodo, sucursal_id, categoria_id, canal)
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
                for fila in comercial_politicas.reporte_ventas_top_productos(db, periodo, sucursal_id, categoria_id, canal)
            ],
            por_canal=[
                FilaVentasPorCanal(**fila)
                for fila in comercial_politicas.reporte_ventas_por_canal(db, periodo, sucursal_id, categoria_id)
            ],
            por_sucursal=[
                FilaVentasPorSucursal(**fila)
                for fila in comercial_politicas.reporte_ventas_por_sucursal(db, periodo, categoria_id, canal, sucursal_id)
            ],
            detalle=[
                FilaVentasDetalle(**fila)
                for fila in comercial_politicas.reporte_ventas_detalle(db, periodo, sucursal_id, categoria_id, canal)
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
        sucursal_id = plataforma_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        por_estado = reporte_reservas_por_estado(db, periodo, sucursal_id)
        ventas_con_reserva = comercial_politicas.contar_ventas_con_reserva(db, periodo, sucursal_id)
        return ReporteReservasRespuesta(
            por_estado=[FilaReservasPorEstado(**fila) for fila in por_estado],
            tasa_conversion=tasa_conversion(por_estado, ventas_con_reserva),
        )


# ---- Descarga de los reportes en Excel o PDF (E10, paso 8) ----


class ExportarReportesVentasInventario:
    """Los mismos reportes de ventas, inventario y reservas, entregados como .xlsx o .pdf. Llama a
    `ConsultarReportesVentasInventario` (las mismas consultas y el mismo alcance de sucursal) y arma
    el documento con `exportacion_convencionales`. No escribe nada salvo la fila de bitácora."""

    def __init__(self) -> None:
        self._reportes = ConsultarReportesVentasInventario()

    def ventas(
        self,
        db: Session,
        usuario_id: int,
        periodo: ParametrosPeriodo,
        sucursal_id: int | None,
        categoria_id: int | None,
        canal: str | None,
        formato: str,
        incluir_grafico: bool,
        contexto: ContextoAuditoria | None = None,
    ) -> ArchivoExportado:
        inicio = time.perf_counter()
        sucursal_id = plataforma_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        filtros = [
            f"Periodo: {etiqueta_periodo(periodo.desde, periodo.hasta)}",
            self._linea_sucursal(db, sucursal_id),
            f"Categoría: {self._nombre_categoria(db, categoria_id)}",
            f"Canal: {canal or 'todos'}",
        ]
        reporte = self._reportes.ventas(db, usuario_id, periodo, sucursal_id, categoria_id, canal)
        documento = documento_ventas(reporte, *self._rotulo(db), filtros, MAX_FILAS[formato])
        return self._entregar(
            db,
            "ventas",
            documento,
            formato,
            incluir_grafico,
            contexto,
            inicio,
            {
                "periodo": {"desde": periodo.desde.isoformat(), "hasta": periodo.hasta.isoformat()},
                "sucursal_id": sucursal_id,
                "categoria_id": categoria_id,
                "canal": canal,
            },
        )

    def inventario(
        self,
        db: Session,
        usuario_id: int,
        sucursal_id: int | None,
        formato: str,
        incluir_grafico: bool,
        contexto: ContextoAuditoria | None = None,
    ) -> ArchivoExportado:
        inicio = time.perf_counter()
        sucursal_id = plataforma_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        filtros = [self._linea_sucursal(db, sucursal_id), "Existencias a la fecha de generación"]
        reporte = self._reportes.inventario(db, usuario_id, sucursal_id)
        documento = documento_inventario(reporte, *self._rotulo(db), filtros, MAX_FILAS[formato])
        return self._entregar(
            db, "inventario", documento, formato, incluir_grafico, contexto, inicio, {"sucursal_id": sucursal_id}
        )

    def reservas(
        self,
        db: Session,
        usuario_id: int,
        periodo: ParametrosPeriodo,
        sucursal_id: int | None,
        formato: str,
        incluir_grafico: bool,
        contexto: ContextoAuditoria | None = None,
    ) -> ArchivoExportado:
        inicio = time.perf_counter()
        sucursal_id = plataforma_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        filtros = [f"Periodo: {etiqueta_periodo(periodo.desde, periodo.hasta)}", self._linea_sucursal(db, sucursal_id)]
        reporte = self._reportes.reservas(db, usuario_id, periodo, sucursal_id)
        documento = documento_reservas(reporte, *self._rotulo(db), filtros)
        return self._entregar(
            db,
            "reservas",
            documento,
            formato,
            incluir_grafico,
            contexto,
            inicio,
            {
                "periodo": {"desde": periodo.desde.isoformat(), "hasta": periodo.hasta.isoformat()},
                "sucursal_id": sucursal_id,
            },
        )

    # -- apoyo --

    @staticmethod
    def _linea_sucursal(db: Session, sucursal_id: int | None) -> str:
        """Una sucursal de otra empresa o inexistente es 404, igual que en el resto de la API."""
        if sucursal_id is None:
            return "Sucursal: todas"
        return f"Sucursal: {plataforma_politicas.obtener_sucursal(db, sucursal_id).nombre}"

    @staticmethod
    def _nombre_categoria(db: Session, categoria_id: int | None) -> str:
        return "todas" if categoria_id is None else catalogo_politicas.obtener_categoria(db, categoria_id).nombre

    @staticmethod
    def _rotulo(db: Session) -> tuple[str, dt.datetime]:
        """(nombre de la empresa de la sesión, ahora en hora de Bolivia): el encabezado del archivo."""
        return plataforma_politicas.obtener_empresa_de_la_sesion(db).nombre, ahora_bolivia()

    @staticmethod
    def _entregar(
        db: Session,
        tipo: str,
        documento,
        formato: str,
        incluir_grafico: bool,
        contexto: ContextoAuditoria | None,
        inicio: float,
        datos: dict,
    ) -> ArchivoExportado:
        contenido = construir_archivo(documento, formato, incluir_grafico)
        # El nombre solo lleva datos propios: el tipo de reporte, el código de la empresa y la hora.
        codigo = plataforma_politicas.obtener_empresa_de_la_sesion(db).codigo
        nombre = f"reporte-{tipo}-{codigo}-{documento.generado_en:%Y%m%d-%H%M}.{formato}"
        if contexto is not None:
            datos = {
                **datos,
                "tipo_reporte": tipo,
                "formato": formato,
                "bytes": len(contenido),
                "duracion_ms": int((time.perf_counter() - inicio) * 1000),
            }
            plataforma_politicas.registrar_bitacora_de(db, contexto, ENTIDAD_REPORTE, None, ACCION_EXPORTAR, datos)
            db.commit()
        return ArchivoExportado(contenido, TIPO_MIME[formato], nombre)


# ---- Resumen de la pantalla de inicio del personal ----

PRENDAS_MAS_VENDIDAS = 4
ALERTAS_MOSTRADAS = 4
VENTAS_RECIENTES = 5


class ConsultarResumenInicio:
    """El resumen de HOY (día de Bolivia) que ve el personal al entrar: ventas, stock bajo y reservas, en UNA llamada y
    con las cuentas hechas en la base (sin traer el historial de cada sucursal).

    No pide `reportes.ver`: lo ve todo el personal, y cada sección aparece solo si el usuario tiene el permiso de esa
    parte (ventas, inventario, reservas) y el plan de la empresa la incluye; las demás van en null. Quien no tiene
    alcance global ve su sucursal; el administrador, todas (`sucursal_id` null). Sin permiso para ninguna sección no
    consulta nada. Solo lee."""

    def __init__(self) -> None:
        self._inventario = ConsultarInventarioGlobal()
        self._catalogo = ConsultarCatalogo()

    def ejecutar(self, db: Session, usuario_id: int) -> ResumenInicioRespuesta:
        exigir_empresa(db)  # el superadministrador (modo plataforma) no alcanza datos de negocio: 403, no un resumen vacío
        permisos = set(plataforma_politicas.permisos_de_usuario(db, usuario_id))
        con_ventas = PERMISO_STAFF_VENTAS in permisos and plan_incluye_funcionalidad(db, FUNC_GESTION_VENTAS)
        con_stock = PERMISO_INVENTARIO_VER in permisos
        con_reservas = PERMISO_STAFF_RESERVAS in permisos and plan_incluye_funcionalidad(db, FUNC_RESERVAS)
        hoy, desde, hasta = dia_bolivia()
        if not (con_ventas or con_stock or con_reservas):
            return ResumenInicioRespuesta(fecha=hoy, sucursal_id=None, sucursal_nombre="")

        # 403 "No tenés una sucursal asignada" si no tiene alcance global ni sucursal propia.
        sucursal_id = plataforma_politicas.acotar_sucursal(db, usuario_id, None)
        nombre = (
            "Todas las sucursales"
            if sucursal_id is None
            else plataforma_politicas.obtener_sucursal(db, sucursal_id).nombre
        )
        return ResumenInicioRespuesta(
            fecha=hoy,
            sucursal_id=sucursal_id,
            sucursal_nombre=nombre,
            ventas=self._ventas(db, desde, hasta, sucursal_id) if con_ventas else None,
            stock=self._stock(db, usuario_id, sucursal_id) if con_stock else None,
            reservas=self._reservas(db, hoy, sucursal_id) if con_reservas else None,
        )

    def _ventas(self, db: Session, desde: dt.datetime, hasta: dt.datetime, sucursal_id: int | None) -> ResumenVentasInicio:
        datos = comercial_politicas.resumen_ventas_del_dia(
            db, desde, hasta, sucursal_id, mas_vendidas=PRENDAS_MAS_VENDIDAS, recientes=VENTAS_RECIENTES
        )
        nombres = self._nombres_de_variantes(db, [variante_id for variante_id, _ in datos["mas_vendidas"]])
        return ResumenVentasInicio(
            tickets=datos["tickets"],
            total_ventas=datos["total"],
            por_cobrar_cantidad=datos["por_cobrar_cantidad"],
            por_cobrar_total=datos["por_cobrar_total"],
            mas_vendidas=[
                PrendaVendidaInicio(variante_id=v, nombre=nombres.get(v, f"Variante {v}"), cantidad=cantidad)
                for v, cantidad in datos["mas_vendidas"]
            ],
            recientes=[VentaRecienteInicio(**fila) for fila in datos["recientes"]],
        )

    def _nombres_de_variantes(self, db: Session, variante_ids: list[int]) -> dict[int, str]:
        if not variante_ids:
            return {}
        items = self._catalogo.resolver_imagen_lookup(db, variante_ids, None)
        return {i.variante_id: i.producto_nombre for i in items if i.variante_id is not None}

    def _stock(self, db: Session, usuario_id: int, sucursal_id: int | None) -> ResumenStockInicio:
        filas = self._inventario.listar_alertas(db, usuario_id, sucursal_id)
        primeras = filas[:ALERTAS_MOSTRADAS]
        fotos = {
            i.producto_id: i.imagen_principal
            for i in (
                self._catalogo.resolver_imagen_lookup(db, None, sorted({f["producto_id"] for f in primeras}))
                if primeras
                else []
            )
        }
        return ResumenStockInicio(
            total_alertas=len(filas),
            alertas=[
                AlertaStockInicio(
                    producto_id=f["producto_id"],
                    variante_id=f["variante_id"],
                    producto=f["producto"],
                    stock_minimo=f["stock_minimo"],
                    cantidad_disponible=f["cantidad_disponible"],
                    imagen=fotos.get(f["producto_id"]),
                )
                for f in primeras
            ],
        )

    def _reservas(self, db: Session, hoy: dt.date, sucursal_id: int | None) -> ResumenReservasInicio:
        por_estado = reporte_reservas_por_estado(db, ParametrosPeriodo(desde=hoy, hasta=hoy), sucursal_id)
        return ResumenReservasInicio(
            total=sum(fila["cantidad"] for fila in por_estado),
            por_estado=[FilaReservasPorEstado(**fila) for fila in por_estado],
        )


# ---- Dashboard de indicadores empresariales (antiguo CU-34: Visualizar indicadores empresariales) ----


class VisualizarDashboardIndicadores:
    def __init__(self) -> None:
        self._inventario = ConsultarInventarioGlobal()

    def ejecutar(
        self, db: Session, usuario_id: int, periodo: ParametrosPeriodo, sucursal_id: int | None = None
    ) -> DashboardRespuesta:
        # Un encargado ve solo su sucursal (también en "ventas por sucursal").
        sucursal_id = plataforma_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        resumen_dict = comercial_politicas.reporte_ventas_resumen(db, periodo, sucursal_id)
        top_productos = comercial_politicas.reporte_ventas_top_productos(db, periodo, sucursal_id, limite=5)
        por_canal = comercial_politicas.reporte_ventas_por_canal(db, periodo, sucursal_id)
        por_sucursal = comercial_politicas.reporte_ventas_por_sucursal(db, periodo, sucursal_id=sucursal_id)

        alertas = self._inventario.listar_alertas(db, usuario_id, sucursal_id)
        valuacion = self._inventario.listar_valuacion(db, usuario_id, sucursal_id)
        valor_inventario_total = sum((fila["valor_total"] for fila in valuacion), _CERO)

        por_estado = reporte_reservas_por_estado(db, periodo, sucursal_id)
        ventas_con_reserva = comercial_politicas.contar_ventas_con_reserva(db, periodo, sucursal_id)

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
