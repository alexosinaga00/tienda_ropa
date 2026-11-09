"""E05, 4.2: el universo de dos empresas.

`crear_universo` deja en una empresa UNA instancia de cada recurso de negocio. Todo se
crea por la API con el administrador de la empresa (casos de uso, no INSERT); solo lo que
no tiene alta por API (imagen, activo y generación del probador, transacción de pasarela,
regla de tarifa, consulta de voz, historial, recomendación, notificación) entra por el
ORM con la empresa fijada.

Cada recurso lleva una MARCA en un texto ("MARCA-A-producto", "MARCA-B-producto"): así
una fuga se ve en el cuerpo de una respuesta. A y B se crean con la MISMA estructura y
datos solapados a propósito (mismo código de producto y SKU, mismo código de sucursal,
mismo correo de usuario, mismo nombre de categoría) y precios y cantidades distintos.

`Universo.nuevo(recurso)` crea una instancia DESECHABLE más de un recurso (para la prueba
espejo de las rutas que destruyen o cambian de estado lo que tocan).
"""

from __future__ import annotations

import datetime as dt
import itertools
import uuid
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

from app.catalogo.models import ActivoProbador, ProbadorGeneracion, ProductoImagen
from app.comercial.models import (
    CajaTurno,
    Devolucion,
    DevolucionDetalle,
    Envio,
    EstadoPago,
    MetodoPago,
    Pago,
    ReglaTarifaEnvio,
    TransaccionPasarela,
)
from app.core.security import crear_access_token, permisos_de_usuario
from app.core.tenant import fijar_empresa
from app.inteligencia.models import ConsultaVoz, HistorialNavegacion, Recomendacion
from app.plataforma.models import Bitacora, Cliente, CopiaSeguridad, Notificacion, Usuario
from app.plataforma.repository import ClienteRepository, UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from app.sincronizacion.models import OperacionSync

API = "/api/v1"
CLAVE = "claveSegura123"

# Precio de la prenda y unidades por venta: A vende poco y B mucho, para que una mezcla
# en un reporte se note (A: 4 x 25 = 100.00; B: 5 x 1400 = 7000.00).
PRECIO = {"A": "25.00", "B": "1400.00"}
UNIDADES_POR_VENTA = {"A": (1, 1, 2), "B": (1, 1, 1, 1, 1)}
TOTAL_VENDIDO = {"A": Decimal("100.00"), "B": Decimal("7000.00")}


def marca(tag: str, recurso: str) -> str:
    return f"MARCA-{tag}-{recurso}"


def _pedir(client, metodo, ruta, cuerpo, headers, esperado):
    respuesta = client.request(metodo, f"{API}{ruta}", json=cuerpo, headers=headers)
    assert respuesta.status_code in esperado, f"{metodo} {ruta}: {respuesta.status_code} {respuesta.text}"
    return respuesta.json() if respuesta.content else None


def crear(client, ruta, cuerpo, headers):
    return _pedir(client, "POST", ruta, cuerpo, headers, (200, 201))


def actualizar(client, ruta, cuerpo, headers):
    return _pedir(client, "PUT", ruta, cuerpo, headers, (200,))


def leer(client, ruta, headers):
    return _pedir(client, "GET", ruta, None, headers, (200,))


def token_de_usuario(db, usuario) -> dict:
    """Cabeceras con el access token de `usuario`, firmado como lo hace el login."""
    roles = [r.nombre for r in usuario.roles]
    token = crear_access_token(usuario.id, roles, permisos_de_usuario(db, usuario.id), empresa_id=usuario.empresa_id)
    return {"Authorization": f"Bearer {token}"}


class Universo:
    """Una empresa con todos sus recursos. `ids` es {"producto": 12, "variante": 31, ...}."""

    def __init__(self, tag, empresa, fabrica_sesiones, client):
        self.tag = tag
        self.empresa = empresa  # EmpresaDePrueba: id, codigo, admin_id, headers
        self.sesiones = fabrica_sesiones
        self.client = client
        self.ids: dict = {}
        self.headers: dict[str, dict] = {"admin": empresa.headers}
        self.cliente: SimpleNamespace | None = None
        self._contador = itertools.count(1)

    # -- utilidades ---------------------------------------------------------------

    @property
    def id(self) -> int:
        return self.empresa.id

    @property
    def codigo(self) -> str:
        return self.empresa.codigo

    @property
    def admin(self) -> dict:
        return self.headers["admin"]

    def m(self, recurso: str) -> str:
        return marca(self.tag, recurso)

    def n(self) -> int:
        return next(self._contador)

    @contextmanager
    def orm(self):
        """Sesión de apoyo con la empresa fijada; confirma al salir."""
        with self.sesiones() as db:
            fijar_empresa(db, self.id)
            yield db
            db.commit()

    # -- creación del universo ------------------------------------------------------

    def construir(self) -> "Universo":
        c, h, ids, m = self.client, self.admin, self.ids, self.m

        ids["ciudad"] = crear(c, "/ciudades", {"nombre": m("ciudad")}, h)["id"]
        ids["sucursal"] = crear(
            c, "/sucursales", {"ciudad_id": ids["ciudad"], "codigo": "SUC-1", "nombre": m("sucursal"), "direccion": "Calle 1"}, h
        )["id"]
        ids["sucursal_destino"] = crear(
            c, "/sucursales", {"ciudad_id": ids["ciudad"], "codigo": "SUC-2", "nombre": m("sucursal-destino"), "direccion": "Calle 2"}, h
        )["id"]
        for dia in range(1, 8):
            horario = crear(
                c,
                f"/sucursales/{ids['sucursal']}/horarios",
                {"dia_semana": dia, "hora_apertura": "08:00:00", "hora_cierre": "20:00:00"},
                h,
            )
            ids.setdefault("horario", horario["id"])

        # Usuarios: un cajero (mismo correo en A y B), otro sin ficha y el cliente.
        ids["usuario"] = crear(
            c, "/usuarios", {"nombre": "Caja", "apellido": m("usuario"), "email": "caja@tienda.bo", "password": CLAVE}, h
        )["id"]
        actualizar(c, f"/usuarios/{ids['usuario']}/roles", {"nombres_rol": ["cajero"]}, h)
        ids["usuario_extra"] = crear(
            c, "/usuarios", {"nombre": "Otro", "apellido": self.tag, "email": "otro@tienda.bo", "password": CLAVE}, h
        )["id"]
        ids["empleado"] = crear(
            c, "/empleados", {"usuario_id": ids["usuario"], "sucursal_id": ids["sucursal"], "cargo": m("empleado")}, h
        )["id"]
        # El administrador también es empleado de la sucursal: así puede vender y cobrar.
        crear(c, "/empleados", {"usuario_id": self.empresa.admin_id, "sucursal_id": ids["sucursal"]}, h)
        with self.orm() as db:
            cajero = db.scalar(select(Usuario).where(Usuario.id == ids["usuario"]))
            self.headers["cajero"] = token_de_usuario(db, cajero)
        self._crear_cliente()

        # Catálogo.
        ids["categoria_padre"] = crear(c, "/categorias", {"nombre": "Ropa", "descripcion": m("categoria-padre")}, h)["id"]
        ids["categoria"] = crear(
            c, "/categorias", {"nombre": "Camisas", "descripcion": m("categoria"), "categoria_padre_id": ids["categoria_padre"]}, h
        )["id"]
        ids["talla"] = crear(c, "/tallas", {"codigo": "M", "descripcion": m("talla"), "orden": 1}, h)["id"]
        # El color del producto es el mismo nombre en A y en B (así el SKU se solapa);
        # el color marcado queda aparte para las pruebas de fuga.
        ids["color_base"] = crear(c, "/colores", {"nombre": "Negro"}, h)["id"]
        ids["color"] = crear(c, "/colores", {"nombre": m("color")}, h)["id"]
        ids["material"] = crear(c, "/materiales", {"nombre": "Algodon", "descripcion": m("material")}, h)["id"]
        ids["temporada"] = crear(c, "/temporadas", {"nombre": m("temporada"), "anio": 2026}, h)["id"]
        ids["coleccion"] = crear(c, "/colecciones", {"nombre": m("coleccion"), "temporada_id": ids["temporada"]}, h)["id"]
        ids["producto"] = crear(
            c,
            "/productos",
            {
                "codigo": "CAM-001",
                "nombre": m("producto"),
                "descripcion": m("producto-descripcion"),
                "categoria_id": ids["categoria"],
                "material_id": ids["material"],
                "temporada_id": ids["temporada"],
                "coleccion_id": ids["coleccion"],
                "precio_base": PRECIO[self.tag],
                "admite_probador": True,
                "tallas_ids": [ids["talla"]],
                "colores_ids": [ids["color_base"]],
            },
            h,
        )["id"]
        variante = leer(c, f"/productos/{ids['producto']}/variantes", h)[0]
        ids["variante"], ids["sku"] = variante["id"], variante["sku"]
        ids["medida"] = crear(c, f"/productos/{ids['producto']}/medidas", {"talla_id": ids["talla"], "pecho_min_cm": "90"}, h)["id"]
        with self.orm() as db:
            imagen = ProductoImagen(producto_id=ids["producto"], url=m("imagen"), orden=0, es_principal=True)
            db.add(imagen)
            db.flush()
            ids["imagen"] = imagen.id
            activo = ActivoProbador(variante_id=ids["variante"], tipo="overlay_2d", url=m("activo-probador"), estado="validado")
            db.add(activo)
            db.flush()
            ids["activo_probador"] = activo.id
            generacion = ProbadorGeneracion(
                cliente_id=self.cliente.id,
                variante_id=ids["variante"],
                hash_foto="f" * 64,
                url_resultado=m("generacion"),
                estado="completado",
            )
            db.add(generacion)
            db.flush()
            ids["generacion"] = generacion.id

        # Inventario.
        crear(c, "/inventario/ajustes", {"variante_id": ids["variante"], "sucursal_id": ids["sucursal"], "cantidad": 100, "observacion": m("ajuste")}, h)
        ids["stock"] = next(s["id"] for s in leer(c, f"/inventario/stock?variante_id={ids['variante']}", h) if s["sucursal_id"] == ids["sucursal"])
        ids["movimiento"] = crear(
            c,
            "/inventario/movimientos",
            {
                "variante_id": ids["variante"],
                "sucursal_id": ids["sucursal"],
                "tipo_movimiento_codigo": "ajuste_positivo",
                "cantidad": 5,
                "observacion": m("movimiento"),
            },
            h,
        )["id"]
        ids["transferencia"] = self._transferencia(enviar=True)

        # Abastecimiento.
        ids["proveedor"] = crear(c, "/proveedores", {"nombre": m("proveedor"), "nit": "1020304"}, h)["id"]
        crear(c, f"/proveedores/{ids['proveedor']}/productos", {"producto_id": ids["producto"]}, h)
        ids["orden_compra"] = self._orden_compra()
        ids["recepcion"] = self._recepcion()

        # Comercial.
        ids["zona_envio"] = crear(c, "/zonas-envio", {"ciudad_id": ids["ciudad"], "nombre": m("zona-envio"), "tarifa_base": "10.00"}, h)["id"]
        with self.orm() as db:
            regla = ReglaTarifaEnvio(zona_envio_id=ids["zona_envio"], peso_desde_kg=0, peso_hasta_kg=5, recargo=1)
            db.add(regla)
            db.flush()
            ids["regla_tarifa"] = regla.id
        ids["direccion"] = crear(
            c, "/clientes/direcciones", {"zona_envio_id": ids["zona_envio"], "alias": m("direccion"), "direccion": "Av. 1"}, self.cliente.headers
        )["id"]
        ids["promocion"] = self._promocion()
        crear(c, "/favoritos", {"variante_id": ids["variante"]}, self.cliente.headers)
        crear(c, "/carrito", {"variante_id": ids["variante"], "cantidad": 1}, self.cliente.headers)
        ids["reserva"] = self._reserva()

        # Ventas pagadas (totales distintos entre A y B), una devolución y un envío.
        ventas = []
        for unidades in UNIDADES_POR_VENTA[self.tag]:
            venta = crear(
                c,
                "/ventas/presencial",
                {"sucursal_id": ids["sucursal"], "cliente_id": self.cliente.id, "detalle": [{"variante_id": ids["variante"], "cantidad": unidades}]},
                h,
            )
            pago = crear(c, "/pagos/caja", {"venta_id": venta["id"], "metodo_pago": "efectivo", "monto_recibido": "99999"}, h)["pago"]
            ventas.append((venta, pago))
        (venta, pago), ultima = ventas[0], ventas[-1]
        ids["venta"], ids["venta_detalle"], ids["pago"] = venta["id"], venta["detalle"][0]["id"], pago["id"]
        ids["devolucion"] = crear(
            c,
            "/devoluciones",
            {"venta_id": ultima[0]["id"], "motivo": m("devolucion"), "detalle": [{"venta_detalle_id": ultima[0]["detalle"][0]["id"], "cantidad": 1}]},
            h,
        )["id"]
        ids["venta_con_devolucion"] = ultima[0]["id"]
        # La devolución de arriba es sin cambio de prenda y la venta se pagó en efectivo: dejó su reembolso (ya hecho).
        ids["reembolso"] = leer(c, f"/ventas/{ultima[0]['id']}/reembolsos", h)[0]["id"]
        # Un turno de caja YA CERRADO (la observación del cierre lleva la marca): así las pruebas "espejo" de cerrar y de
        # completar el conteo reciben un 409 sin cambiar nada, y la sucursal queda libre para abrir otro turno.
        with self.orm() as db:
            turno = CajaTurno(
                sucursal_id=ids["sucursal"], abierto_por_id=self.empresa.admin_id, estado="cerrada",
                apertura_en=dt.datetime(2026, 10, 1, 8, 0, 0), monto_inicial=Decimal("10.00"),
                cierre_en=dt.datetime(2026, 10, 1, 12, 0, 0), cerrado_por_id=self.empresa.admin_id,
                efectivo_contado=Decimal("10.00"), ventas_efectivo=Decimal("0.00"), reembolsos_efectivo=Decimal("0.00"),
                monto_esperado=Decimal("10.00"), diferencia=Decimal("0.00"), cantidad_ventas=0,
                ventas_otros_metodos=Decimal("0.00"), pendientes_declarados=0, observacion_cierre=m("cierre-caja"),
            )
            db.add(turno)
            db.flush()
            ids["caja_turno"] = turno.id
        ids["solicitud_cambio"] = self._solicitud_pendiente()
        self._pendiente_con_pasarela()
        self._envio(ventas[1][0]["id"] if len(ventas) > 1 else venta["id"])

        # Inteligencia y notificaciones.
        with self.orm() as db:
            voz = ConsultaVoz(cliente_id=self.cliente.id, texto_transcrito=m("consulta-voz"), filtros_json={"marca": m("voz")}, cantidad_resultados=1)
            historial = HistorialNavegacion(cliente_id=self.cliente.id, producto_id=ids["producto"], variante_id=ids["variante"], tipo_evento="vista")
            recomendacion = Recomendacion(cliente_id=self.cliente.id, variante_id=ids["variante"], puntaje=Decimal("0.9"), motivo=m("recomendacion"))
            notificacion = Notificacion(usuario_id=self.empresa.admin_id, titulo=m("notificacion"), mensaje=m("notificacion-mensaje"), tipo="aviso")
            # La bitácora (E06) ya recibe filas de las acciones de arriba; esta lleva la marca
            # para que una fuga se vea en el cuerpo de una respuesta.
            bitacora = Bitacora(
                empresa_id=self.id, usuario_id=self.empresa.admin_id, entidad="universo", entidad_id=0,
                accion="crear", datos={"marca": m("bitacora")}, ip="127.0.0.1",
            )
            # Una operación offline ya resuelta (E07): su mensaje lleva la marca.
            operacion_id = uuid.uuid4()
            operacion_sync = OperacionSync(
                sucursal_id=ids["sucursal"], usuario_id=self.empresa.admin_id, operacion_id=operacion_id,
                tipo="venta_contado", estado="rechazada", motivo="regla_de_negocio",
                payload={"nota": "sin datos"}, resultado={"mensaje": m("operacion-sync")},
                fecha_operacion=dt.datetime(2026, 10, 1, 12, 0, 0), procesada_en=dt.datetime(2026, 10, 1, 12, 0, 1),
            )
            # Una copia de seguridad ya completada (E22): solo metadatos; la marca va en la versión del esquema,
            # que es el único texto libre de la fila y sale en el detalle y en el historial.
            copia = CopiaSeguridad(
                usuario_id=self.empresa.admin_id, estado="completada", tamano_bytes=2048,
                tablas_incluidas={"sucursal": 2, "producto": 1}, version_esquema=m("copia"), checksum="c" * 64,
                terminado_en=dt.datetime(2026, 10, 1, 12, 0, 1),
            )
            db.add_all([voz, historial, recomendacion, notificacion, bitacora, operacion_sync, copia])
            db.flush()
            ids.update(
                consulta_voz=voz.id, historial=historial.id, recomendacion=recomendacion.id,
                notificacion=notificacion.id, bitacora=bitacora.id, operacion_sync=str(operacion_id),
                copia_seguridad=copia.id,
            )
        return self

    # -- piezas ---------------------------------------------------------------------

    def _crear_cliente(self):
        """Un usuario con rol cliente y su perfil, dentro de la empresa."""
        with self.orm() as db:
            repo = UsuarioRepository()
            usuario = repo.crear(
                db, UsuarioCrear(nombre="Cli", apellido=self.tag, email="cliente@tienda.bo", password=CLAVE)
            )
            repo.asignar_roles(db, usuario, ["cliente"])
            perfil = ClienteRepository().crear_o_actualizar_perfil(db, usuario.id, None)
            db.flush()
            self.cliente = SimpleNamespace(id=perfil.id, usuario_id=usuario.id, headers=token_de_usuario(db, usuario))
        self.ids["cliente"] = self.cliente.id
        self.headers["cliente"] = self.cliente.headers

    def _solicitud_pendiente(self) -> int:
        """Una solicitud de cambio PENDIENTE del cliente sobre la venta del universo (Etapa 2 de CU-17). Se inserta
        directo: no mueve stock ni cuenta como devuelta, y la talla nueva es la misma (la regla de negocio la rechaza
        al aprobar con 400: para la prueba espejo basta con que la ruta ENCUENTRE el recurso)."""
        ids = self.ids
        with self.orm() as db:
            devolucion = Devolucion(
                codigo=f"SOL-U{self.tag}{self.n()}",
                venta_id=ids["venta"],
                motivo=self.m("solicitud"),
                estado="pendiente",
                usuario_id=self.cliente.usuario_id,
            )
            db.add(devolucion)
            db.flush()
            db.add(
                DevolucionDetalle(
                    devolucion_id=devolucion.id,
                    venta_detalle_id=ids["venta_detalle"],
                    cantidad=1,
                    variante_nueva_id=ids["variante"],
                )
            )
            db.flush()
            return devolucion.id

    def _transferencia(self, enviar: bool) -> int:
        ids = self.ids
        cuerpo = {
            "codigo": f"TRF-{self.n():03d}",
            "sucursal_origen_id": ids["sucursal"],
            "sucursal_destino_id": ids["sucursal_destino"],
            "detalle": [{"variante_id": ids["variante"], "cantidad": 2}],
        }
        transferencia = crear(self.client, "/transferencias", cuerpo, self.admin)["id"]
        if enviar:
            crear(self.client, f"/transferencias/{transferencia}/enviar", None, self.admin)
        return transferencia

    def _orden_compra(self) -> int:
        ids = self.ids
        cuerpo = {
            "codigo": f"OC-{self.n():03d}",
            "proveedor_id": ids["proveedor"],
            "sucursal_id": ids["sucursal"],
            "detalle": [{"variante_id": ids["variante"], "cantidad": 5, "costo_unitario": "40.00"}],
        }
        return crear(self.client, "/ordenes-compra", cuerpo, self.admin)["id"]

    def _recepcion(self) -> int:
        ids = self.ids
        cuerpo = {
            "codigo": f"REC-{self.n():03d}",
            "proveedor_id": ids["proveedor"],
            "sucursal_id": ids["sucursal"],
            "observacion": self.m("recepcion"),
            "detalle": [{"variante_id": ids["variante"], "cantidad": 4, "costo_unitario": "40.00"}],
        }
        return crear(self.client, "/recepciones", cuerpo, self.admin)["id"]

    def _promocion(self) -> int:
        hoy = dt.date.today()
        cuerpo = {
            "nombre": self.m("promocion"),
            "tipo": "porcentaje",
            "valor": "10",
            "fecha_inicio": hoy.isoformat(),
            "fecha_fin": (hoy + dt.timedelta(days=30)).isoformat(),
            "alcances": [{"producto_id": self.ids["producto"]}],
        }
        return crear(self.client, "/promociones", cuerpo, self.admin)["id"]

    def _reserva(self) -> int:
        manana = dt.date.today() + dt.timedelta(days=1)
        cuerpo = {
            "sucursal_id": self.ids["sucursal"],
            "fecha_visita": manana.isoformat(),
            "hora_visita_desde": "10:00:00",
            "hora_visita_hasta": "11:00:00",
            "observacion": self.m("reserva"),
            "detalle": [{"variante_id": self.ids["variante"], "cantidad": 1}],
        }
        return crear(self.client, "/reservas", cuerpo, self.cliente.headers)["id"]

    def _pendiente_con_pasarela(self):
        """Una venta pendiente de pago con un pago de Libélula y su transacción: el
        webhook y la pantalla QR resuelven la empresa por `id_transaccion`."""
        ids = self.ids
        venta = crear(
            self.client,
            "/ventas/presencial",
            {"sucursal_id": ids["sucursal"], "cliente_id": self.cliente.id, "detalle": [{"variante_id": ids["variante"], "cantidad": 1}]},
            self.admin,
        )
        ids["venta_pendiente"] = venta["id"]
        with self.orm() as db:
            metodo = db.scalar(select(MetodoPago).where(MetodoPago.codigo == "libelula"))
            estado = db.scalar(select(EstadoPago).where(EstadoPago.codigo == "iniciado"))
            pago = Pago(venta_id=venta["id"], metodo_pago_id=metodo.id, estado_id=estado.id, monto=Decimal(venta["total"]))
            db.add(pago)
            db.flush()
            transaccion = TransaccionPasarela(
                pago_id=pago.id,
                pasarela="libelula",
                id_transaccion=f"TXN-{self.tag}-0001",
                payload_envio={"marca": self.m("transaccion")},
                estado="pendiente",
            )
            db.add(transaccion)
            db.flush()
            ids.update(pago_pasarela=pago.id, transaccion=transaccion.id, id_transaccion=transaccion.id_transaccion)

    def _envio(self, venta_id: int):
        ids = self.ids
        with self.orm() as db:
            envio = Envio(
                venta_id=venta_id,
                direccion_id=ids["direccion"],
                zona_envio_id=ids["zona_envio"],
                costo=Decimal("10.00"),
                estado="programado",
                repartidor=self.m("repartidor"),
            )
            db.add(envio)
            db.flush()
            ids["envio"] = envio.id
            ids["venta_con_envio"] = venta_id

    # -- instancias desechables -------------------------------------------------------

    def nuevo(self, recurso: str, **cambios) -> int:
        """Crea una instancia NUEVA de `recurso` (para la prueba espejo de las rutas que
        borran o cambian de estado lo que tocan) y devuelve su id."""
        c, h, ids, n = self.client, self.admin, self.ids, self.n()
        fabricas = {
            "ciudad": lambda: crear(c, "/ciudades", {"nombre": f"Ciudad {n}"}, h)["id"],
            "sucursal": lambda: crear(
                c, "/sucursales", {"ciudad_id": ids["ciudad"], "codigo": f"S-{n}", "nombre": f"Sucursal {n}", "direccion": "Calle"}, h
            )["id"],
            "horario": lambda: crear(
                c, f"/sucursales/{cambios.get('sucursal_id', ids['sucursal_destino'])}/horarios",
                {"dia_semana": 1, "hora_apertura": "06:00:00", "hora_cierre": "07:00:00"}, h,
            )["id"],
            "categoria": lambda: crear(c, "/categorias", {"nombre": f"Categoria {n}"}, h)["id"],
            "talla": lambda: crear(c, "/tallas", {"codigo": f"T{n}", "orden": n}, h)["id"],
            "color": lambda: crear(c, "/colores", {"nombre": f"Color {n}"}, h)["id"],
            "material": lambda: crear(c, "/materiales", {"nombre": f"Material {n}"}, h)["id"],
            "temporada": lambda: crear(c, "/temporadas", {"nombre": f"Temporada {n}", "anio": 2025}, h)["id"],
            "coleccion": lambda: crear(c, "/colecciones", {"nombre": f"Coleccion {n}"}, h)["id"],
            "producto": lambda: self._producto_nuevo(n),
            "variante": lambda: self._variante_nueva(n),
            "medida": lambda: crear(
                c, f"/productos/{ids['producto']}/medidas", {"talla_id": self._talla_nueva(n), "pecho_min_cm": "80"}, h
            )["id"],
            "imagen": lambda: self._insertar(ProductoImagen(producto_id=ids["producto"], url=f"img-{n}", orden=n, es_principal=False)),
            "proveedor": lambda: crear(c, "/proveedores", {"nombre": f"Proveedor {n}"}, h)["id"],
            "orden_compra": self._orden_compra,
            "transferencia": lambda: self._transferencia(enviar=False),
            "transferencia_enviada": lambda: self._transferencia(enviar=True),
            "promocion": self._promocion,
            "zona_envio": lambda: crear(c, "/zonas-envio", {"ciudad_id": ids["ciudad"], "nombre": f"Zona {n}", "tarifa_base": "5.00"}, h)["id"],
            "usuario": lambda: crear(
                c, "/usuarios", {"nombre": "Nuevo", "apellido": str(n), "email": f"nuevo{n}@tienda.bo", "password": CLAVE}, h
            )["id"],
            "empleado": lambda: crear(c, "/empleados", {"usuario_id": self.nuevo("usuario"), "sucursal_id": ids["sucursal"]}, h)["id"],
            "direccion": lambda: crear(
                c, "/clientes/direcciones", {"zona_envio_id": ids["zona_envio"], "direccion": f"Calle {n}"}, self.cliente.headers
            )["id"],
            "reserva": lambda: self._reserva_nueva(n),
            "venta_pendiente": lambda: self._venta_pendiente()["id"],
            "pago": lambda: self._pago_nuevo(),
            "solicitud_cambio": self._solicitud_pendiente,
            "notificacion": lambda: self._insertar(Notificacion(usuario_id=self.empresa.admin_id, titulo=f"aviso {n}", tipo="aviso")),
            "activo_probador": lambda: self._insertar(
                ActivoProbador(variante_id=self._variante_nueva(n), tipo="overlay_2d", url=f"activo-{n}", estado="pendiente")
            ),
            "copia_seguridad": lambda: self._insertar(
                CopiaSeguridad(
                    usuario_id=self.empresa.admin_id, estado="completada", tamano_bytes=1024,
                    tablas_incluidas={"sucursal": 1}, version_esquema=f"copia-{n}", checksum="d" * 64,
                    terminado_en=dt.datetime(2026, 10, 1, 12, 0, 1),
                )
            ),
        }
        return fabricas[recurso]()

    def _insertar(self, fila) -> int:
        with self.orm() as db:
            db.add(fila)
            db.flush()
            return fila.id

    def _talla_nueva(self, n: int) -> int:
        return crear(self.client, "/tallas", {"codigo": f"X{n}", "orden": 50 + n}, self.admin)["id"]

    def _producto_nuevo(self, n: int) -> int:
        ids = self.ids
        return crear(
            self.client,
            "/productos",
            {
                "codigo": f"PRD-{n:03d}",
                "nombre": f"Producto {n}",
                "categoria_id": ids["categoria"],
                "precio_base": PRECIO[self.tag],
                "tallas_ids": [ids["talla"]],
                "colores_ids": [crear(self.client, "/colores", {"nombre": f"Color p{n}"}, self.admin)["id"]],
            },
            self.admin,
        )["id"]

    def _variante_nueva(self, n: int) -> int:
        producto = self._producto_nuevo(n)
        return leer(self.client, f"/productos/{producto}/variantes", self.admin)[0]["id"]

    def _reserva_nueva(self, n: int) -> int:
        # Un día distinto por reserva evita chocar con la franja ya reservada.
        dia = dt.date.today() + dt.timedelta(days=2 + n)
        cuerpo = {
            "sucursal_id": self.ids["sucursal"],
            "fecha_visita": dia.isoformat(),
            "hora_visita_desde": "10:00:00",
            "hora_visita_hasta": "11:00:00",
            "detalle": [{"variante_id": self.ids["variante"], "cantidad": 1}],
        }
        return crear(self.client, "/reservas", cuerpo, self.cliente.headers)["id"]

    def _venta_pendiente(self) -> dict:
        return crear(
            self.client,
            "/ventas/presencial",
            {
                "sucursal_id": self.ids["sucursal"],
                "cliente_id": self.cliente.id,
                "detalle": [{"variante_id": self.ids["variante"], "cantidad": 1}],
            },
            self.admin,
        )

    def _pago_nuevo(self) -> int:
        venta = self._venta_pendiente()
        return crear(self.client, "/pagos/caja", {"venta_id": venta["id"], "metodo_pago": "efectivo", "monto_recibido": "99999"}, self.admin)["pago"]["id"]


def crear_universo(client, sesiones, empresa, tag: str) -> Universo:
    """Construye el universo de `empresa` (EmpresaDePrueba) con la etiqueta "A" o "B"."""
    return Universo(tag, empresa, sesiones, client).construir()
