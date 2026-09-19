"""CU-23 — Gestionar carrito

Actor: Cliente.
Precondición: el cliente tiene sesión iniciada; la variante a agregar
existe.
Postcondición: el carrito del cliente queda guardado con sus líneas y el
total calculado.

Caso de uso COMPUESTO: incluye aplicar las promociones vigentes al total
(antes era un CU aparte "aplicar promoción al carrito"; el catálogo de 43
lo funde acá, en la descripción de CU-23).
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.core.exceptions import ConflictoError, NoEncontradoError
from app.inventario.casos_uso.cu13_consultar_disponibilidad_sucursal import ConsultarDisponibilidadSucursal
from app.seguridad.politicas import obtener_perfil_cliente
from app.ventas.models import Carrito, CarritoDetalle
from app.ventas.politicas import calcular_linea, redondear
from app.ventas.repository import CarritoRepository
from app.ventas.schemas import (
    CarritoDetalleActualizar,
    CarritoDetalleCrear,
    CarritoDetalleRespuesta,
    CarritoResumenLinea,
    CarritoResumenRespuesta,
    CarritoRespuesta,
)


class GestionarCarrito:
    def __init__(self) -> None:
        self._carritos = CarritoRepository()
        self._disponibilidad = ConsultarDisponibilidadSucursal()

    def _respuesta(self, db: Session, carrito: Carrito) -> CarritoRespuesta:
        """Una línea cuya variante se dio de baja después de agregarla se
        sigue devolviendo (disponible=False) para que el cliente la vea y la
        quite, pero no suma al subtotal. Antes obtener_variante lanzaba 404
        y el cliente se quedaba sin poder ver ni vaciar su carrito."""
        detalle_resp = []
        subtotal = Decimal("0")
        for linea in carrito.detalle:
            variante = catalogo_politicas.buscar_variante(db, linea.variante_id)
            disponible = variante is not None and variante.activo
            precio_unitario = catalogo_politicas.obtener_precio_efectivo(variante) if variante else Decimal("0")
            subtotal_linea = redondear(precio_unitario * linea.cantidad)
            detalle_resp.append(
                CarritoDetalleRespuesta(
                    id=linea.id,
                    variante_id=linea.variante_id,
                    cantidad=linea.cantidad,
                    precio_unitario=precio_unitario,
                    subtotal=subtotal_linea,
                    disponible=disponible,
                )
            )
            if disponible:
                subtotal += subtotal_linea

        return CarritoRespuesta(
            id=carrito.id,
            cliente_id=carrito.cliente_id,
            sucursal_id=carrito.sucursal_id,
            actualizado_en=carrito.actualizado_en,
            detalle=detalle_resp,
            subtotal=redondear(subtotal),
        )

    def _validar_stock(self, db: Session, variante_id: int, cantidad: int) -> None:
        """El carrito todavía no elige sucursal: se valida contra el
        disponible total de la variante. La sucursal concreta se vuelve a
        validar al registrar la venta (ventas.politicas.registrar_venta)."""
        disponible = sum(s.cantidad_disponible for s in self._disponibilidad.ejecutar(db, variante_id))
        if cantidad > disponible:
            if disponible <= 0:
                raise ConflictoError("Esta prenda está agotada")
            raise ConflictoError(f"Solo quedan {disponible} unidades disponibles")

    def obtener_mi_carrito(self, db: Session, usuario_id: int) -> CarritoRespuesta:
        cliente = obtener_perfil_cliente(db, usuario_id)
        carrito = self._carritos.obtener_o_crear(db, cliente.id)
        db.commit()  # persiste el carrito si obtener_o_crear tuvo que crearlo
        return self._respuesta(db, carrito)

    def agregar(self, db: Session, usuario_id: int, datos: CarritoDetalleCrear) -> CarritoRespuesta:
        cliente = obtener_perfil_cliente(db, usuario_id)
        catalogo_politicas.obtener_variante(db, datos.variante_id)  # 404 si no existe
        carrito = self._carritos.obtener_o_crear(db, cliente.id)

        linea = self._carritos.obtener_linea(db, carrito.id, datos.variante_id)
        self._validar_stock(db, datos.variante_id, datos.cantidad + (linea.cantidad if linea else 0))
        if linea is None:
            db.add(CarritoDetalle(carrito_id=carrito.id, variante_id=datos.variante_id, cantidad=datos.cantidad))
        else:
            linea.cantidad += datos.cantidad

        db.commit()
        db.refresh(carrito)
        return self._respuesta(db, carrito)

    def actualizar_linea(
        self, db: Session, usuario_id: int, variante_id: int, datos: CarritoDetalleActualizar
    ) -> CarritoRespuesta:
        cliente = obtener_perfil_cliente(db, usuario_id)
        carrito = self._carritos.obtener_o_crear(db, cliente.id)
        linea = self._carritos.obtener_linea(db, carrito.id, variante_id)
        if linea is None:
            raise NoEncontradoError("Esa variante no está en el carrito")

        if datos.cantidad > linea.cantidad:  # bajar la cantidad nunca se bloquea
            variante = catalogo_politicas.buscar_variante(db, variante_id)
            if variante is None or not variante.activo:
                raise ConflictoError("Esta prenda ya no está disponible")
            self._validar_stock(db, variante_id, datos.cantidad)
        linea.cantidad = datos.cantidad
        db.commit()
        db.refresh(carrito)
        return self._respuesta(db, carrito)

    def quitar(self, db: Session, usuario_id: int, variante_id: int) -> CarritoRespuesta:
        cliente = obtener_perfil_cliente(db, usuario_id)
        carrito = self._carritos.obtener_o_crear(db, cliente.id)
        linea = self._carritos.obtener_linea(db, carrito.id, variante_id)
        if linea is None:
            raise NoEncontradoError("Esa variante no está en el carrito")

        db.delete(linea)
        db.commit()
        db.refresh(carrito)
        return self._respuesta(db, carrito)

    def previsualizar(self, db: Session, usuario_id: int) -> CarritoResumenRespuesta:
        """POST /carrito/aplicar-promocion: no hay código de cupón que
        canjear (`promocion` no tiene esa columna) -- esto recalcula el
        carrito con las promociones vigentes ya aplicadas solas, según
        `promocion_alcance`."""
        cliente = obtener_perfil_cliente(db, usuario_id)
        carrito = self._carritos.obtener_o_crear(db, cliente.id)
        db.commit()
        hoy = dt.date.today()

        lineas: list[CarritoResumenLinea] = []
        subtotal = Decimal("0")
        descuento = Decimal("0")
        for linea in carrito.detalle:
            variante = catalogo_politicas.buscar_variante(db, linea.variante_id)
            if variante is None or not variante.activo:
                continue  # dada de baja: no se puede comprar, no entra en el total
            precio_unitario, descuento_unitario, subtotal_linea = calcular_linea(db, variante, linea.cantidad, hoy)
            lineas.append(
                CarritoResumenLinea(
                    variante_id=linea.variante_id,
                    cantidad=linea.cantidad,
                    precio_unitario=precio_unitario,
                    descuento_unitario=descuento_unitario,
                    subtotal=subtotal_linea,
                )
            )
            subtotal += precio_unitario * linea.cantidad
            descuento += descuento_unitario * linea.cantidad

        subtotal = redondear(subtotal)
        descuento = redondear(descuento)
        return CarritoResumenRespuesta(lineas=lineas, subtotal=subtotal, descuento=descuento, total=subtotal - descuento)
