"""CU-15 — Consultar ventas

Absorbe los antiguos CU-26 (Consultar historial de compras) y CU-28
(Consultar ventas de la sucursal).

Actor: Cliente, Encargado de sucursal, Cajero.
Precondición: sesión iniciada. El cliente consulta su historial; el
personal (con el permiso ventas.gestionar_sucursal, solo de su sucursal
salvo alcance global, ver plataforma.politicas) consulta las ventas de su
sucursal.
Postcondición: el cliente visualiza su historial de compras y el
comprobante de la compra elegida; el personal conoce las ventas y los
ingresos de su sucursal.

Incluye ver el comprobante de una venta (antes un "extend" del catálogo, ya
no un CU aparte): es la misma consulta con más detalle.

También incluye consultar los turnos y cierres de caja (aporte propio, D24): `ConsultarTurnosCaja`. El cajero ve el
turno de su sucursal sin el esperado (cierre ciego); el encargado de sucursal y el administrador (permiso
`caja.supervisar`) ven los cierres, con el esperado, de su sucursal o de todas las de la empresa."""

import datetime as dt

from sqlalchemy.orm import Session

from app.comercial.models import Venta
from app.comercial.politicas import (
    cerrar_turnos_vencidos,
    construir_turno_respuesta,
    es_supervisor_de_caja,
    limites_de_dias_bolivia,
    monto_inicial_sugerido,
    obtener_comprobante,
    sucursal_de_caja,
)
from app.comercial.repository import CajaTurnoRepository, VentaRepository
from app.comercial.schemas import (
    CajaDeSucursalRespuesta,
    TurnoActualRespuesta,
    TurnoDetalleRespuesta,
    TurnoRespuesta,
)
from app.core.deps import ParametrosPaginacion
from app.plataforma import politicas as plataforma_politicas
from app.plataforma.politicas import obtener_perfil_cliente


# ---- Consultar historial de compras (antiguo CU-26) ----

class ConsultarHistorialCompras:
    def __init__(self) -> None:
        self._ventas = VentaRepository()

    def obtener_comprobante(self, db: Session, venta_id: int, usuario_id: int) -> Venta:
        return obtener_comprobante(db, venta_id, usuario_id)

    def listar_mis_compras(self, db: Session, usuario_id: int) -> list[Venta]:
        cliente = obtener_perfil_cliente(db, usuario_id)
        return self._ventas.listar_por_cliente(db, cliente.id)


# ---- Consultar ventas de la sucursal (antiguo CU-28) ----

class ConsultarVentasSucursal:
    def __init__(self) -> None:
        self._ventas = VentaRepository()

    def ejecutar(self, db: Session, sucursal_id: int, usuario_id: int) -> list[Venta]:
        plataforma_politicas.obtener_sucursal(db, sucursal_id)
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, sucursal_id)
        return self._ventas.listar_por_sucursal(db, sucursal_id)


# ---- Consultar turnos y cierres de caja (aporte propio, D24) ----

class ConsultarTurnosCaja:
    def __init__(self) -> None:
        self._turnos = CajaTurnoRepository()

    def actual(self, db: Session, usuario_id: int, sucursal_id: int | None) -> TurnoActualRespuesta:
        """El turno abierto de la sucursal de esta persona (o de la que indique, si opera todas) y, si no hay ninguno, el
        monto inicial que se sugiere para abrir el siguiente. Sin el esperado salvo para un supervisor (cierre ciego)."""
        sucursal_id = sucursal_de_caja(db, usuario_id, sucursal_id)
        cerrar_turnos_vencidos(db, sucursal_id)
        turno = self._turnos.obtener_abierto_de_sucursal(db, sucursal_id)
        if turno is None:
            return TurnoActualRespuesta(
                sucursal_id=sucursal_id, turno=None, monto_inicial_sugerido=monto_inicial_sugerido(db, sucursal_id)
            )
        respuesta = construir_turno_respuesta(db, turno, ver_esperado=es_supervisor_de_caja(db, usuario_id))
        return TurnoActualRespuesta(sucursal_id=sucursal_id, turno=respuesta, monto_inicial_sugerido=None)

    def estado_de_cajas(self, db: Session, usuario_id: int) -> list[CajaDeSucursalRespuesta]:
        """"Cajas de hoy" para el supervisor: una tarjeta por sucursal que puede ver (todas si opera todas; la suya si
        no), con su turno abierto y el esperado en vivo."""
        sucursales = [
            sucursal
            for sucursal, _horarios in plataforma_politicas.listar_sucursales_autorizadas(db, usuario_id)
            if not sucursal.es_deposito
        ]
        cerrar_turnos_vencidos(db)
        abiertos = {t.sucursal_id: t for t in self._turnos.listar_abiertos(db, [s.id for s in sucursales])}
        usuarios = plataforma_politicas.obtener_usuarios_por_ids(db, [t.abierto_por_id for t in abiertos.values()])
        nombres = {sucursal.id: sucursal.nombre for sucursal in sucursales}
        return [
            CajaDeSucursalRespuesta(
                sucursal_id=sucursal.id,
                sucursal_nombre=sucursal.nombre,
                turno=(
                    construir_turno_respuesta(
                        db, abiertos[sucursal.id], ver_esperado=True, usuarios=usuarios, sucursales=nombres
                    )
                    if sucursal.id in abiertos
                    else None
                ),
            )
            for sucursal in sucursales
        ]

    def listar(
        self,
        db: Session,
        usuario_id: int,
        sucursal_id: int | None,
        estado: str | None,
        desde: dt.date | None,
        hasta: dt.date | None,
        paginacion: ParametrosPaginacion,
    ) -> list[TurnoRespuesta]:
        """Los turnos, el más reciente primero, con su esperado. El supervisor de una sucursal solo ve los de la suya;
        quien opera todas, los de la empresa o los de la sucursal pedida. `desde` y `hasta` son días de Bolivia."""
        acotada = plataforma_politicas.acotar_sucursal(db, usuario_id, sucursal_id)
        cerrar_turnos_vencidos(db, acotada)
        desde_utc, hasta_utc = limites_de_dias_bolivia(desde, hasta)
        turnos = self._turnos.listar(
            db,
            sucursal_ids=None if acotada is None else [acotada],
            estado=estado,
            desde=desde_utc,
            hasta=hasta_utc,
            paginacion=paginacion,
        )
        ids = {i for t in turnos for i in (t.abierto_por_id, t.cerrado_por_id, t.conteo_por_id)} - {None}
        usuarios = plataforma_politicas.obtener_usuarios_por_ids(db, list(ids))
        nombres = {
            sucursal.id: sucursal.nombre
            for sucursal, _horarios in plataforma_politicas.listar_sucursales_autorizadas(db, usuario_id)
        }
        return [
            construir_turno_respuesta(db, turno, ver_esperado=True, usuarios=usuarios, sucursales=nombres)
            for turno in turnos
        ]

    def detalle(self, db: Session, usuario_id: int, turno_id: int) -> TurnoDetalleRespuesta:
        turno = self._turnos.obtener(db, turno_id)  # 404 si no existe o es de otra empresa
        plataforma_politicas.validar_acceso_sucursal(db, usuario_id, turno.sucursal_id)
        cerrar_turnos_vencidos(db, turno.sucursal_id)
        db.refresh(turno)
        return construir_turno_respuesta(db, turno, ver_esperado=True, detalle=True)
