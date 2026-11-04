"""Población de demostración (`scripts.poblar_demo`): 8 organizaciones con sucursales en varias
ciudades, catálogo con foto y probador, y stock distinto por sucursal. Todo sobre SQLite en
memoria (la fixture `db_session`), con Cloudinary simulado y una carpeta de fotos de mentira que
trae los metadatos reales de las 24 prendas."""

import dataclasses
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.catalogo.models import (
    ActivoProbador,
    Categoria,
    MovimientoInventario,
    Producto,
    ProductoImagen,
    ProductoVariante,
    Stock,
)
from app.core.exceptions import ErrorFuncional
from app.core.tenant import empresa_de, en_empresa, fijar_empresa, fijar_plataforma
from app.plataforma import politicas
from app.plataforma.casos_uso.cu04_gestionar_empresas_planes_suscripciones import GestionarEmpresas
from app.plataforma.models import Cliente, Empleado, Empresa, Plan, Sucursal, Suscripcion, Usuario
from app.plataforma.schemas import SucursalCrear
from scripts import demo_organizaciones as demo
from scripts import poblar_demo, seed_prendas_probador
from scripts.demo_organizaciones import ORGANIZACIONES, por_codigo
from app.core.security import verificar_password
from scripts.poblar_demo import (
    RUTA_ACCESOS,
    cantidad_stock,
    clave_de_organizacion,
    escribir_accesos,
    exigir_base_segura,
    imprimir,
    imprimir_accesos,
    iniciales_de,
    seed,
)
from tests.scripts._prendas_falsas import PRENDAS, crear_carpeta, simular_cloudinary

PASSWORD = "claveSegura123"

@pytest.fixture(scope="module")
def carpeta(tmp_path_factory):
    return crear_carpeta(tmp_path_factory.mktemp("prendas"))


@pytest.fixture(autouse=True)
def sin_cloudinary(monkeypatch):
    return simular_cloudinary(monkeypatch)


def _reducida(codigo: str, prendas: tuple[int, ...]) -> demo.OrganizacionDemo:
    return dataclasses.replace(por_codigo(codigo), prendas=prendas)


@pytest.fixture()
def organizaciones():
    """Tres organizaciones con pocas prendas, para que las pruebas sean rápidas."""
    return (
        _reducida("fashionstore", (10005, 10003, 10017, 14006, 10022)),  # hombre, mujer, chamarra, camiseta, polo
        _reducida("chaski-sport", (10005, 10010, 10019, 10022)),
        _reducida("pampa-casual", (38606, 10026, 14006)),
    )


def _sembrar(db, carpeta, organizaciones, **kwargs):
    return seed(db, ejecutar=True, password=PASSWORD, origen=carpeta, organizaciones=organizaciones, **kwargs)


def _id(db, codigo: str) -> int:
    empresa = politicas.obtener_empresa_por_codigo(db, codigo)
    assert empresa is not None, f"no existe la empresa {codigo}"
    return empresa.id


def _contar(db, empresa_id: int, modelo, *condiciones) -> int:
    with en_empresa(db, empresa_id):
        return db.scalar(select(func.count()).select_from(modelo).where(*condiciones))


def _total(resumen) -> int:
    return sum(resumen.creados.values())


# ---- Los datos (sin base de datos) ----------------------------------------------------------


def test_los_datos_cumplen_las_reglas():
    assert len(ORGANIZACIONES) == 8
    assert sum(len(o.sucursales) for o in ORGANIZACIONES) == 22
    assert sum(len(o.prendas) for o in ORGANIZACIONES) == 104
    assert [o.plan for o in ORGANIZACIONES].count("profesional") == 3
    assert [o.plan for o in ORGANIZACIONES].count("estandar") == 3
    assert [o.plan for o in ORGANIZACIONES].count("basico") == 2
    ids_del_dataset = {p[0] for p in PRENDAS}
    assert len(ids_del_dataset) == 24
    from app.plataforma.politicas import normalizar_nombre_empresa

    for org in ORGANIZACIONES:
        assert org.codigo == normalizar_nombre_empresa(org.nombre), org.nombre
        assert org.nombre.isascii(), "los nombres no llevan tildes (se escriben en el login)"
        assert len(org.sucursales) <= demo.LIMITE_SUCURSALES[org.plan], org.nombre
        assert 2 <= len(org.sucursales) <= 3
        assert set(org.prendas) <= ids_del_dataset
        assert len(set(org.prendas)) == len(org.prendas)
        codigos = [s.codigo for s in org.sucursales]
        assert len(set(codigos)) == len(codigos) and all(len(c) <= 13 for c in codigos), org.nombre
        correos = [p.email for p in org.personal()]
        assert len(set(correos)) == len(correos) and all(c.endswith(f"@{org.dominio}") for c in correos)
        assert all(s.factor > 0 for s in org.sucursales)
    assert len({o.dominio for o in ORGANIZACIONES}) == 8
    assert por_codigo("fashionstore").prendas == demo.TODAS and len(demo.TODAS) == 24
    with pytest.raises(KeyError):
        por_codigo("no-existe")


def test_el_plan_basico_tiene_dos_sucursales_y_hay_varias_ciudades():
    for org in ORGANIZACIONES:
        if org.plan == "basico":
            assert len(org.sucursales) == 2
    ciudades = {s.ciudad[0] for o in ORGANIZACIONES for s in o.sucursales}
    assert len(ciudades) >= 6
    # Una organización con todas sus sucursales en Santa Cruz y otra repartida en varias ciudades.
    assert {s.ciudad for s in por_codigo("canaveral-moda").sucursales} == {demo.SANTA_CRUZ}
    assert len({s.ciudad for s in por_codigo("illimani-urban").sucursales}) == 2
    for org in ORGANIZACIONES:
        for s in org.sucursales:
            assert -23 < float(s.latitud) < -9 and -70 < float(s.longitud) < -57, f"{s.codigo} fuera de Bolivia"


PRECIOS_ESPERADOS = {  # (polera, polo o camiseta, chamarra)
    "fashionstore": (149, 189, 399),
    "chaski-sport": (159, 209, 439),
    "illimani-urban": (169, 219, 459),
    "canaveral-moda": (139, 179, 379),
    "valle-alegre": (129, 169, 359),
    "tinku-wear": (129, 159, 339),
    "boutique-andina": (129, 169, 359),
    "pampa-casual": (119, 149, 319),
}


def test_los_precios_por_organizacion_son_los_aprobados():
    for org in ORGANIZACIONES:
        obtenidos = tuple(
            int(seed_prendas_probador.precio_con_factor(base, org.factor_precio))
            for base in (Decimal("149.00"), Decimal("189.00"), Decimal("399.00"))
        )
        assert obtenidos == PRECIOS_ESPERADOS[org.codigo], org.nombre


def test_planificar_asigna_genero_categoria_y_probador(carpeta):
    planes = {p.id_dataset: p for p in seed_prendas_probador.planificar(carpeta, None)}
    assert len(planes) == 24
    por_genero = [p.genero for p in planes.values()]
    assert (por_genero.count("hombre"), por_genero.count("mujer"), por_genero.count("unisex")) == (16, 7, 1)
    # La chamarra (de corte femenino en el dataset) se ofrece a todos y admite el probador.
    assert (planes[10017].genero, planes[10017].categoria, planes[10017].admite_probador) == ("unisex", "Chamarras", True)
    assert (planes[10003].genero, planes[10003].admite_probador) == ("mujer", False)
    assert planes[14006].categoria == "Camisetas deportivas" and planes[3730].categoria == "Camisetas deportivas"
    assert {i for i, p in planes.items() if p.categoria == "Polos"} == {10022, 15348, 38639}
    assert all(p.admite_probador == (p.genero != "mujer") for p in planes.values())
    assert {p.categoria for p in planes.values()} == {"Poleras", "Polos", "Camisetas deportivas", "Chamarras"}
    # Con el factor de Pampa Casual (0,80).
    pampa = {p.id_dataset: p for p in seed_prendas_probador.planificar(carpeta, {38606, 14006, 10017}, factor_precio=Decimal("0.80"))}
    assert (pampa[38606].precio, pampa[14006].precio, pampa[10017].precio) == (Decimal("119"), Decimal("149"), Decimal("319"))


def test_cantidad_stock_es_determinista_y_variada():
    org = por_codigo("chaski-sport")
    tienda, otra, deposito = org.sucursales
    assert cantidad_stock(org.codigo, tienda, "FS-10005", "M") == cantidad_stock(org.codigo, tienda, "FS-10005", "M")
    muestra = [(p, t) for p in (f"FS-{i}" for i in range(10000, 10120)) for t in demo.TALLAS_DEMO]

    def cantidades(sucursal):
        return [cantidad_stock(org.codigo, sucursal, p, t) for p, t in muestra]

    for sucursal in org.sucursales:
        valores = cantidades(sucursal)
        assert min(valores) >= 0
        assert 0 in valores, "debe haber variantes agotadas"
        assert any(1 <= v <= 2 for v in valores), "debe haber variantes con muy poco stock"
        assert any(v >= 3 for v in valores)
    # El depósito guarda mucho más que cualquier tienda, y la sucursal grande más que la chica.
    promedio = {s.codigo: sum(cantidades(s)) / len(muestra) for s in org.sucursales}
    assert promedio[deposito.codigo] > 1.8 * promedio[tienda.codigo]
    assert promedio[tienda.codigo] > promedio[otra.codigo]
    # Cada sucursal tiene números distintos para las mismas variantes.
    assert cantidades(tienda) != cantidades(otra) != cantidades(deposito)


def test_reescribir_los_accesos_conserva_el_bloque_del_superadministrador(tmp_path):
    ruta = tmp_path / "accesos.txt"
    bloque = "SUPERADMINISTRADOR DE LA PLATAFORMA\n  Correo: super@ejemplo.bo\n  Clave : Clave.De.Prueba.1\n" + (
        "=== FIN SUPERADMINISTRADOR ==="
    )
    ruta.write_text(bloque + "\n\nACCESOS VIEJOS que se reemplazan\n", encoding="utf-8")

    escribir_accesos(list(ORGANIZACIONES), ruta)
    escribir_accesos(list(ORGANIZACIONES), ruta)  # repetir no lo duplica

    texto = ruta.read_text(encoding="utf-8")
    assert texto.startswith(bloque) and texto.count("SUPERADMINISTRADOR DE LA PLATAFORMA") == 1
    assert "ACCESOS VIEJOS" not in texto and "CS.ChaskiSport.2026" in texto
    # Sin ese bloque (o con otro archivo), el script no inventa ni agrega ninguna clave de superadministrador.
    limpio = tmp_path / "sin_bloque.txt"
    escribir_accesos(list(ORGANIZACIONES), limpio)
    assert "SUPERADMINISTRADOR DE LA PLATAFORMA" not in limpio.read_text(encoding="utf-8")


def test_reintentar_repite_los_cortes_de_red_y_no_los_demas_errores(monkeypatch):
    import cloudinary.exceptions

    esperas = []
    monkeypatch.setattr(seed_prendas_probador.time, "sleep", esperas.append)
    cortes = [cloudinary.exceptions.Error("Unexpected error - ProtocolError('Connection aborted.', ConnectionResetError(10054))")]
    llamadas = []

    def con_dos_cortes():
        llamadas.append(1)
        if len(llamadas) <= 2:
            raise cortes[0]
        return "subido"

    assert seed_prendas_probador.reintentar(con_dos_cortes) == "subido"
    assert len(llamadas) == 3 and esperas == [3.0, 6.0]  # espera creciente

    # Un corte que no se arregla se propaga tras agotar los intentos.
    llamadas.clear()
    with pytest.raises(cloudinary.exceptions.Error):
        seed_prendas_probador.reintentar(lambda: llamadas.append(1) or (_ for _ in ()).throw(cortes[0]), intentos=3)
    assert len(llamadas) == 3
    # Un error que no es de red (validación) NO se repite.
    llamadas.clear()
    with pytest.raises(ValueError):
        seed_prendas_probador.reintentar(lambda: llamadas.append(1) or (_ for _ in ()).throw(ValueError("x")))
    assert len(llamadas) == 1
    assert seed_prendas_probador._es_error_de_red(TimeoutError()) and not seed_prendas_probador._es_error_de_red(KeyError())


def test_exigir_base_segura():
    with pytest.raises(SystemExit):
        exigir_base_segura("fashionstore_dev", True, None)
    with pytest.raises(SystemExit):
        exigir_base_segura("fashionstore_dev", True, "no")
    exigir_base_segura("fashionstore_dev", True, "si")  # confirmada
    exigir_base_segura("fashionstore_dev", False, None)  # dry-run: no escribe
    exigir_base_segura("fashionstore_test", True, None)
    exigir_base_segura(None, True, None)


# ---- El script sobre la base ---------------------------------------------------------------------


def test_dry_run_no_escribe(db_session, carpeta, organizaciones, sin_cloudinary, capsys):
    fashionstore = _id(db_session, "fashionstore")
    antes = {m.__name__: db_session.scalar(select(func.count()).select_from(m)) for m in (Empresa, Plan, Suscripcion)}

    resultados = seed(db_session, ejecutar=False, password=None, origen=carpeta, organizaciones=organizaciones)

    assert {m.__name__: db_session.scalar(select(func.count()).select_from(m)) for m in (Empresa, Plan, Suscripcion)} == antes
    assert politicas.obtener_empresa_por_codigo(db_session, "chaski-sport") is None
    assert db_session.scalar(select(Plan.id).where(Plan.codigo == "estandar")) is None
    for modelo in (Sucursal, Usuario, Producto, ProductoVariante, Stock, MovimientoInventario, ProductoImagen):
        assert _contar(db_session, fashionstore, modelo) == 0, modelo.__name__
    assert sin_cloudinary == []
    assert resultados["(plan estandar)"].creados["plan"] == 1
    chaski, pampa = resultados["chaski-sport"], resultados["pampa-casual"]
    assert chaski.creados["empresa"] == 1 and chaski.creados["sucursal"] == 3 and chaski.creados["producto"] == 4
    assert chaski.creados["variante"] == 16 and chaski.creados["foto"] == 4
    assert pampa.creados["sucursal"] == 2 and pampa.creados["producto"] == 3
    assert resultados["fashionstore"].creados["producto"] == 5
    assert empresa_de(db_session) == fashionstore  # la sesión queda como estaba
    imprimir(resultados, False)
    assert "dry-run" in capsys.readouterr().out


def test_siembra_organizaciones_planes_ciudades_y_catalogo(db_session, carpeta, organizaciones, sin_cloudinary):
    resultados = _sembrar(db_session, carpeta, organizaciones)
    assert all(_total(r) > 0 for r in resultados.values())
    original = _id(db_session, "fashionstore")

    # El plan Estándar existe como dato, con lo que se aprobó.
    estandar = db_session.scalar(select(Plan).where(Plan.codigo == "estandar"))
    assert (estandar.max_sucursales, estandar.reportes_ia, estandar.analitica_ml, estandar.copias_seguridad) == (5, True, False, True)
    assert (estandar.plazo_cambio_horas_defecto, estandar.max_copias_historial, estandar.operacion_offline) == (48, 6, True)
    assert estandar.precio_mensual_bs == Decimal("290.00")

    for codigo, plan in (("fashionstore", "profesional"), ("chaski-sport", "profesional"), ("pampa-casual", "basico")):
        with en_empresa(db_session, _id(db_session, codigo)):
            assert politicas.plan_de_la_empresa(db_session).codigo == plan
            assert politicas.estado_efectivo(politicas.obtener_suscripcion_vigente(db_session)) == "activa"

    chaski, pampa, fashionstore = _id(db_session, "chaski-sport"), _id(db_session, "pampa-casual"), original
    # Sucursales: Chaski en dos ciudades con su depósito; Pampa dos tiendas en Tarija.
    assert _contar(db_session, chaski, Sucursal) == 3
    assert _contar(db_session, chaski, Sucursal, Sucursal.es_deposito.is_(True)) == 1
    assert _contar(db_session, pampa, Sucursal, Sucursal.es_deposito.is_(True)) == 0
    with en_empresa(db_session, chaski):
        filas = db_session.execute(select(Sucursal.codigo, Sucursal.latitud, Sucursal.ciudad_id)).all()
        assert len({ciudad_id for _, _, ciudad_id in filas}) == 2  # Santa Cruz y Cochabamba
        assert all(lat is not None for _, lat, _ in filas)
    # Personal: administrador, y encargado y cajero por tienda.
    assert _contar(db_session, chaski, Empleado) == 1 + 2 * 2
    assert _contar(db_session, chaski, Cliente) == demo.CLIENTES_POR_ORGANIZACION
    with en_empresa(db_session, chaski):
        correos = set(db_session.scalars(select(Usuario.email)))
    assert {"admin@chaskisport.bo", "encargado.plaza@chaskisport.bo", "cajero.norte@chaskisport.bo"} <= correos

    # Catálogo: cada organización tiene SOLO sus prendas y sus precios.
    for codigo, esperados in (("fashionstore", 5), ("chaski-sport", 4), ("pampa-casual", 3)):
        assert _contar(db_session, _id(db_session, codigo), Producto) == esperados, codigo
        assert _contar(db_session, _id(db_session, codigo), ProductoVariante) == esperados * 4, codigo
    with en_empresa(db_session, pampa):
        precios = dict(db_session.execute(select(Producto.codigo, Producto.precio_base)).all())
    assert precios == {"FS-38606": Decimal("119"), "FS-10026": Decimal("119"), "FS-14006": Decimal("149")}
    with en_empresa(db_session, chaski):
        precios = dict(db_session.execute(select(Producto.codigo, Producto.precio_base)).all())
        categorias = set(db_session.scalars(select(Categoria.nombre)))
    assert precios["FS-10005"] == Decimal("159") and precios["FS-10022"] == Decimal("209")
    assert {"Ropa superior", "Poleras", "Polos"} <= categorias
    with en_empresa(db_session, chaski):
        madre = {c.nombre: c.categoria_padre_id for c in db_session.scalars(select(Categoria))}
        ids = {c.nombre: c.id for c in db_session.scalars(select(Categoria))}
    assert madre["Polos"] == ids["Poleras"] and madre["Poleras"] == ids["Ropa superior"]

    # Género y probador: la mujer sin probador; hombre y la chamarra unisex, con overlay en las 4 tallas.
    with en_empresa(db_session, fashionstore):
        productos = {p.codigo: p for p in db_session.scalars(select(Producto))}
        assert (productos["FS-10003"].genero, productos["FS-10003"].admite_probador) == ("mujer", False)
        assert (productos["FS-10017"].genero, productos["FS-10017"].admite_probador) == ("unisex", True)
        assert (productos["FS-10005"].genero, productos["FS-10005"].admite_probador) == ("hombre", True)
        con_overlay = set(
            db_session.scalars(
                select(ProductoVariante.producto_id).join(ActivoProbador, ActivoProbador.variante_id == ProductoVariante.id)
            )
        )
        assert con_overlay == {p.id for c, p in productos.items() if c != "FS-10003"}
        assert db_session.scalar(select(func.count()).select_from(ActivoProbador)) == 4 * 4
        assert db_session.scalar(select(func.count()).select_from(ActivoProbador).where(ActivoProbador.estado == "validado")) == 16
        assert db_session.scalar(select(func.count()).select_from(ProductoImagen)) == 5
        assert db_session.scalar(select(func.count()).select_from(ProductoImagen).where(ProductoImagen.es_principal.is_(True))) == 5
    # Subidas: una foto por producto y un overlay por producto con probador (las demás tallas lo reutilizan).
    assert len(sin_cloudinary) == (5 + 4) + (4 + 3) + (3 + 2)  # fotos + overlays de las 3 organizaciones

    # La sesión queda como estaba.
    assert empresa_de(db_session) == original


def test_el_stock_es_distinto_por_sucursal_y_cuadra_con_lo_previsto(db_session, carpeta, organizaciones):
    _sembrar(db_session, carpeta, organizaciones)
    for org in organizaciones:
        empresa_id = _id(db_session, org.codigo)
        planes = poblar_demo.planes_de_prendas(org, carpeta)
        with en_empresa(db_session, empresa_id):
            sucursales = {s.codigo: s.id for s in db_session.scalars(select(Sucursal))}
            filas = db_session.execute(select(Stock.sucursal_id, Stock.cantidad_fisica, Stock.stock_minimo, Stock.stock_maximo)).all()
            kardex = db_session.scalar(select(func.count()).select_from(MovimientoInventario))
        assert all(fisica >= 0 for _, fisica, _, _ in filas)
        esperadas_filas = esperadas_unidades = 0
        totales = {}
        for s in org.sucursales:
            unidades = poblar_demo.unidades_previstas(org, planes, (s,))
            con_stock = sum(
                cantidad_stock(org.codigo, s, p.codigo, t) > 0 for p in planes for t in demo.TALLAS_DEMO
            )
            esperadas_filas += con_stock
            esperadas_unidades += unidades
            totales[s.codigo] = sum(f for sid, f, _, _ in filas if sid == sucursales[s.codigo])
            assert totales[s.codigo] == unidades, f"{org.codigo}/{s.codigo}"
        assert len(filas) == esperadas_filas and kardex == esperadas_filas
        assert sum(totales.values()) == esperadas_unidades
        assert len(set(totales.values())) == len(totales), "las sucursales no tienen el mismo total"
        # Mínimo y máximo de cada fila, según tienda o depósito.
        por_id = {sucursales[s.codigo]: s for s in org.sucursales}
        assert all((minimo, maximo) == (por_id[sid].stock_minimo, por_id[sid].stock_maximo) for sid, _, minimo, maximo in filas)


def test_segunda_corrida_no_cambia_nada(db_session, carpeta, organizaciones, sin_cloudinary):
    _sembrar(db_session, carpeta, organizaciones)
    subidas = len(sin_cloudinary)
    empresas = [_id(db_session, o.codigo) for o in organizaciones]
    modelos = (Sucursal, Usuario, Empleado, Cliente, Producto, ProductoVariante, ProductoImagen, ActivoProbador, Stock, MovimientoInventario, Suscripcion)

    def foto():
        return {(e, m.__name__): _contar(db_session, e, m) for e in empresas for m in modelos}

    antes = foto()
    segunda = _sembrar(db_session, carpeta, organizaciones)

    assert {codigo: _total(resumen) for codigo, resumen in segunda.items()} == dict.fromkeys(segunda, 0)
    assert foto() == antes
    assert len(sin_cloudinary) == subidas  # no vuelve a subir nada
    assert db_session.scalar(select(func.count()).select_from(Plan).where(Plan.codigo == "estandar")) == 1


def test_ajustar_planes_deja_copias_y_plazo_crecientes_y_no_pisa_sin_la_opcion(db_session, carpeta, organizaciones):
    def valores():
        db_session.expire_all()
        planes = {p.codigo: p for p in db_session.scalars(select(Plan))}
        return {
            c: (planes[c].copias_seguridad, planes[c].max_copias_historial, planes[c].plazo_cambio_horas_defecto)
            for c in ("basico", "estandar", "profesional")
        }

    # Sin la opción solo nace el Estándar; Básico y Profesional quedan como los dejó la migración.
    _sembrar(db_session, carpeta, organizaciones[2:])
    assert valores() == {"basico": (False, 0, 24), "estandar": (True, 6, 48), "profesional": (True, 5, 24)}

    # Un ajuste manual del superadministrador sobrevive a repetir el script sin la opción.
    estandar = db_session.scalar(select(Plan).where(Plan.codigo == "estandar"))
    estandar.max_copias_historial = 4
    db_session.commit()
    _sembrar(db_session, carpeta, organizaciones[2:])
    assert valores()["estandar"] == (True, 4, 48)

    # Con la opción se aplica lo acordado (los tres planes cambian), y repetirla no cambia nada más.
    resultado = _sembrar(db_session, carpeta, organizaciones[2:], ajustar_planes=True)
    assert resultado["(plan estandar)"].creados["plan_ajustado"] == 3
    assert valores() == {"basico": (True, 3, 24), "estandar": (True, 6, 48), "profesional": (True, 10, 72)}
    otra = _sembrar(db_session, carpeta, organizaciones[2:], ajustar_planes=True)
    assert otra["(plan estandar)"].creados["plan_ajustado"] == 0
    c = valores()  # las copias y el plazo crecen con el plan
    assert c["basico"][1] < c["estandar"][1] < c["profesional"][1] and c["basico"][2] < c["estandar"][2] < c["profesional"][2]


def test_el_plan_basico_rechaza_una_tercera_sucursal(db_session, carpeta, organizaciones):
    _sembrar(db_session, carpeta, organizaciones)
    pampa = _id(db_session, "pampa-casual")
    assert _contar(db_session, pampa, Sucursal, Sucursal.activo.is_(True)) == 2
    with en_empresa(db_session, pampa):
        ciudad_id = db_session.scalar(select(Sucursal.ciudad_id))
    original = empresa_de(db_session)
    fijar_plataforma(db_session)
    try:
        with pytest.raises(ErrorFuncional) as error:
            GestionarEmpresas().agregar_sucursal(
                db_session, pampa, SucursalCrear(ciudad_id=ciudad_id, codigo="TJ-TERCERA", nombre="Tercera", direccion="Calle 1")
            )
    finally:
        fijar_empresa(db_session, original)
    assert error.value.status_code == 409 and error.value.codigo == "limite_plan_excedido"


def test_boutique_andina_suma_las_poleras_con_foto_a_sus_productos(db_session, carpeta):
    boutique = dataclasses.replace(por_codigo("boutique-andina"), prendas=(28639, 10007))
    resultados = _sembrar(db_session, carpeta, (boutique,))

    empresa_id = _id(db_session, "boutique-andina")
    assert _contar(db_session, empresa_id, Sucursal) == 2  # las de seed_empresas_prueba, sin duplicar
    assert _contar(db_session, empresa_id, Producto) == 6 + 2  # sus 6 sin foto y las 2 nuevas
    assert _contar(db_session, empresa_id, ProductoImagen) == 2
    with en_empresa(db_session, empresa_id):
        assert db_session.scalar(select(Producto.precio_base).where(Producto.codigo == "FS-28639")) == Decimal("129")
        # Las prendas nuevas tienen stock en las dos sucursales.
        nuevas = select(ProductoVariante.id).join(Producto).where(Producto.codigo.in_(["FS-28639", "FS-10007"]))
        sucursales_con_stock = set(db_session.scalars(select(Stock.sucursal_id).where(Stock.variante_id.in_(nuevas))))
        assert len(sucursales_con_stock) == 2
    assert _total(resultados["boutique-andina"]) > 0


def test_sin_fotos_no_usa_cloudinary(db_session, carpeta, organizaciones, sin_cloudinary):
    _sembrar(db_session, carpeta, organizaciones[1:2], con_fotos=False)
    chaski = _id(db_session, "chaski-sport")
    assert sin_cloudinary == []
    assert _contar(db_session, chaski, Producto) == 4
    assert _contar(db_session, chaski, ProductoImagen) == 0 and _contar(db_session, chaski, ActivoProbador) == 0
    assert _contar(db_session, chaski, Stock) > 0  # el stock sí se carga


def test_solo_una_organizacion_y_codigo_desconocido(db_session, carpeta, organizaciones):
    _sembrar(db_session, carpeta, organizaciones, solo={"pampa-casual"})
    assert politicas.obtener_empresa_por_codigo(db_session, "pampa-casual") is not None
    assert politicas.obtener_empresa_por_codigo(db_session, "chaski-sport") is None
    assert db_session.scalar(select(Plan.id).where(Plan.codigo == "estandar")) is not None  # el plan va siempre
    with pytest.raises(SystemExit):
        _sembrar(db_session, carpeta, organizaciones, solo={"no-existe"})


def test_una_organizacion_no_ve_los_datos_de_otra(db_session, carpeta, organizaciones):
    _sembrar(db_session, carpeta, organizaciones)
    chaski, pampa = _id(db_session, "chaski-sport"), _id(db_session, "pampa-casual")
    with en_empresa(db_session, chaski):
        codigos_chaski = set(db_session.scalars(select(Producto.codigo)))
        correos_chaski = set(db_session.scalars(select(Usuario.email)))
    with en_empresa(db_session, pampa):
        codigos_pampa = set(db_session.scalars(select(Producto.codigo)))
        correos_pampa = set(db_session.scalars(select(Usuario.email)))
    assert "FS-10005" in codigos_chaski and "FS-10005" not in codigos_pampa  # mismo código, otra empresa
    assert {"FS-10026", "FS-38606"} <= codigos_pampa and not ({"FS-10026", "FS-38606"} & codigos_chaski)
    assert not any(c.endswith("@pampacasual.bo") for c in correos_chaski)
    assert not any(c.endswith("@chaskisport.bo") for c in correos_pampa)


def test_los_limites_de_stock_y_los_limites_del_plan_se_validan_antes_de_escribir(db_session, carpeta):
    exceso = dataclasses.replace(por_codigo("pampa-casual"), sucursales=por_codigo("chaski-sport").sucursales)
    with pytest.raises(SystemExit):
        _sembrar(db_session, carpeta, (exceso,))
    assert politicas.obtener_empresa_por_codigo(db_session, "pampa-casual") is None  # no escribió nada


def test_las_claves_derivadas_del_nombre_son_validas_y_distintas():
    claves = {org.codigo: clave_de_organizacion(org) for org in ORGANIZACIONES}
    assert claves["chaski-sport"] == "CS.ChaskiSport.2026"
    assert claves["canaveral-moda"] == "CM.CanaveralModa.2026"
    assert claves["fashionstore"] == "FS.FashionStore.2026"
    assert len(set(claves.values())) == 8
    assert all(8 <= len(c.encode()) <= 72 for c in claves.values())
    iniciales = [iniciales_de(o) for o in ORGANIZACIONES]
    assert iniciales == ["FS", "CS", "IU", "CM", "VA", "TW", "BA", "PC"] and len(set(iniciales)) == 8


def test_el_archivo_de_accesos_trae_claves_y_correos_sin_el_superadministrador(tmp_path):
    ruta = escribir_accesos(list(ORGANIZACIONES), tmp_path / "accesos.txt")
    texto = ruta.read_text(encoding="utf-8")
    for org in ORGANIZACIONES:
        assert org.nombre in texto and clave_de_organizacion(org) in texto and f"/t/{org.codigo}" in texto
        assert all(persona.email in texto for persona in org.personal())
        assert org.email_cliente(1) in texto
    assert "superadmin@" not in texto and "FashionStore.2026" not in texto.replace("FS.FashionStore.2026", "")
    # El archivo por defecto cae en una carpeta que git ignora.
    assert RUTA_ACCESOS.parent.name == "backups"


def test_clave_por_organizacion_cada_una_entra_solo_con_la_suya(db_session, carpeta, organizaciones, capsys):
    seed(
        db_session, ejecutar=True, password=None, origen=carpeta, organizaciones=organizaciones,
        clave_por_organizacion=True,
    )  # fmt: skip
    hashes = {}
    for codigo, correo in (
        ("chaski-sport", "admin@chaskisport.bo"),
        ("pampa-casual", "cajero.centro@pampacasual.bo"),
        ("fashionstore", "cliente01@demo.fashionstore.bo"),
    ):
        with en_empresa(db_session, _id(db_session, codigo)):
            hashes[codigo] = db_session.scalar(select(Usuario.password_hash).where(Usuario.email == correo))
    assert verificar_password("CS.ChaskiSport.2026", hashes["chaski-sport"])
    assert verificar_password("PC.PampaCasual.2026", hashes["pampa-casual"])
    assert verificar_password("FS.FashionStore.2026", hashes["fashionstore"])  # incluso los clientes
    assert not verificar_password("PC.PampaCasual.2026", hashes["chaski-sport"])
    assert not verificar_password("CS.ChaskiSport.2026", hashes["pampa-casual"])

    imprimir_accesos(list(organizaciones), True)
    assert "CS.ChaskiSport.2026" in capsys.readouterr().out  # en este modo la clave sí se muestra


def test_la_contrasena_inicial_no_se_imprime(db_session, carpeta, organizaciones, capsys):
    secreta = "Zx9-clave-secreta-unica"
    resultados = seed(db_session, ejecutar=True, password=secreta, origen=carpeta, organizaciones=organizaciones)
    imprimir(resultados, True)
    imprimir_accesos(list(organizaciones))
    seed(db_session, ejecutar=False, password=secreta, origen=carpeta, organizaciones=organizaciones)
    salida = capsys.readouterr()
    assert secreta not in salida.out and secreta not in salida.err
    assert "admin@chaskisport.bo" in salida.out  # sí se listan los correos de acceso

    # Una contraseña inválida se rechaza sin repetirla en el mensaje.
    with pytest.raises(SystemExit) as error:
        seed(db_session, ejecutar=True, password="cl4ve", origen=carpeta, organizaciones=organizaciones)
    assert "cl4ve" not in str(error.value)
