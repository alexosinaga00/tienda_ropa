from decimal import Decimal

from sqlalchemy import func, select

from app.abastecimiento.models import OrdenCompra, ProductoProveedor, Proveedor, Recepcion
from app.catalogo.casos_uso.cu07_gestionar_catalogo_maestro import GestionarCategorias, GestionarColores
from app.catalogo.casos_uso.cu08_gestionar_productos import GestionarProductos
from app.catalogo.models import Talla
from app.catalogo.schemas import CategoriaCrear, ColorCrear, ProductoCrear
from app.inventario.models import MovimientoInventario, Stock
from app.organizacion.models import Empleado, HorarioSucursal, Sucursal
from app.seguridad.politicas import permisos_de_usuario
from app.seguridad.models import Usuario
from scripts.seed_catalogo import seed as seed_catalogo
from scripts.seed_operativo import seed as seed_operativo

PASSWORD = "claveSegura123"


def _crear_productos(db):
    seed_catalogo(db)
    cu_categorias = GestionarCategorias()
    cu_colores = GestionarColores()
    cu_productos = GestionarProductos()
    tallas = [t.id for t in db.scalars(select(Talla).where(Talla.codigo.in_(["L", "XL"])))]
    padre = cu_categorias.crear(db, CategoriaCrear(nombre="Ropa superior"))
    poleras = cu_categorias.crear(db, CategoriaCrear(nombre="Poleras", categoria_padre_id=padre.id))
    chamarras = cu_categorias.crear(db, CategoriaCrear(nombre="Chamarras", categoria_padre_id=padre.id))
    negro = cu_colores.crear(db, ColorCrear(nombre="Negro", codigo_hex="#1A1A1A"))
    for codigo, nombre, categoria, precio in [
        ("FS-1", "Polera Nike Basic (Negro)", poleras.id, "149.00"),
        ("FS-2", "Polo Puma Classic (Negro)", poleras.id, "189.00"),
        ("FS-3", "Chamarra Adidas Wind (Negro)", chamarras.id, "399.00"),
    ]:
        cu_productos.crear(
            db,
            ProductoCrear(
                codigo=codigo, nombre=nombre, categoria_id=categoria, genero="hombre",
                precio_base=Decimal(precio), tallas_ids=tallas, colores_ids=[negro.id],
            ),
            creado_por=None,
        )


def _contar(db, modelo):
    return db.scalar(select(func.count()).select_from(modelo))


def test_dry_run_no_escribe(db_session):
    _crear_productos(db_session)

    resumen = seed_operativo(db_session, ejecutar=False, password=None)

    assert resumen.creados["sucursal"] == 3
    assert resumen.creados["orden_compra"] == 9
    assert _contar(db_session, Sucursal) == 0
    assert _contar(db_session, Stock) == 0


def test_seed_operativo_crea_todo_consistente_e_idempotente(db_session):
    _crear_productos(db_session)

    seed_operativo(db_session, ejecutar=True, password=PASSWORD)

    assert _contar(db_session, Sucursal) == 3
    assert _contar(db_session, HorarioSucursal) == 14
    assert _contar(db_session, Usuario) == 6
    assert _contar(db_session, Empleado) == 5
    assert _contar(db_session, Proveedor) == 3
    assert _contar(db_session, ProductoProveedor) == 3
    assert _contar(db_session, OrdenCompra) == 9
    assert set(db_session.scalars(select(OrdenCompra.estado))) == {"recibida"}
    assert _contar(db_session, Recepcion) == 9
    # 3 productos x 2 tallas x 3 sucursales
    assert _contar(db_session, Stock) == 18

    # Kardex: el stock físico es la suma de sus movimientos.
    for stock in db_session.scalars(select(Stock)):
        suma = db_session.scalar(
            select(func.sum(MovimientoInventario.cantidad)).where(
                MovimientoInventario.variante_id == stock.variante_id,
                MovimientoInventario.sucursal_id == stock.sucursal_id,
            )
        )
        assert suma == stock.cantidad_fisica > 0
        assert stock.costo_promedio > 0
        assert stock.stock_maximo is not None

    # El admin tiene todos los permisos; el cajero queda en su sucursal.
    admin = db_session.scalar(select(Usuario).where(Usuario.email == "admin@fashionstore.bo"))
    assert len(permisos_de_usuario(db_session, admin.id)) == 19
    cajero = db_session.scalar(select(Usuario).where(Usuario.email == "cajero.centro@fashionstore.bo"))
    empleado = db_session.scalar(select(Empleado).where(Empleado.usuario_id == cajero.id))
    centro = db_session.scalar(select(Sucursal).where(Sucursal.codigo == "SC-CENTRO"))
    assert empleado.sucursal_id == centro.id

    movimientos_antes = _contar(db_session, MovimientoInventario)
    segundo = seed_operativo(db_session, ejecutar=True, password=PASSWORD)

    assert sum(segundo.creados.values()) == 0
    assert _contar(db_session, MovimientoInventario) == movimientos_antes
