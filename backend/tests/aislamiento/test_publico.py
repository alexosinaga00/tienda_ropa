"""E05, 4.6 (primera mitad): la tienda pública, el catálogo con datos solapados y la pasarela.

- Cada ruta PUBLICA (/public/{codigo}/...): la tienda A devuelve solo datos de A y la B solo de B; un código
  inexistente o una empresa inactiva dan el mismo 404; con la suscripción suspendida, 403
  `suscripcion_no_activa` (salvo /tienda y /tiendas, exentas); un token de la otra empresa se trata como
  anónimo; las rutas viejas equivalentes, sin token, dan 401.
- Catálogo con el MISMO SKU y código en A y B: las búsquedas devuelven solo filas de la empresa de la ruta o del token.
- GET /public/tiendas: solo empresas activas con suscripción activa y solo 4 campos.
- PASARELA: el webhook y la pantalla QR resuelven la empresa por `id_transaccion`; no se llama a ningún servicio externo.

Las empresas descartables (`desc-e05-N`) son propias de este archivo; el universo compartido (A y B) no se altera
salvo con altas nuevas (usuarios cliente, ventas pendientes con su transacción).
"""

import hashlib
import hmac
import itertools
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.catalogo.models import Producto, ProductoVariante
from app.comercial.models import EstadoPago, MetodoPago, Pago, TransaccionPasarela
from app.core.config import get_settings
from app.plataforma.models import Sucursal

from .ayudas_tokens import (
    API,
    crear_descartable,
    empresa_descartable,
    poner_activa_empresa,
    poner_estado_suscripcion,
    retirar_descartable,
    rutas_de,
    nombre_corto,
)
from .oraculo import ID_INEXISTENTE, normalizar, parametros_de
from .plantillas import PARAMETROS
from .rutas_esperadas import RUTAS

PUBLICAS = rutas_de({"PUBLICA"})
CON_CODIGO = [c for c in PUBLICAS if "{codigo}" in c[1]]
SIN_REGISTRO = [c for c in CON_CODIGO if not c[1].endswith("/registro")]
PREFIJO = f"{API}/public/{{codigo}}"
_correos = itertools.count(1)

# Respuestas sin texto libre al que ponerle marca (cifras, horas, ids, confirmaciones): se revisan por ids.
SIN_MARCA = {"/sucursales/{sucursal_id}/horarios", "/inventario/disponibilidad", "/ia/eventos", "/registro", "/tienda"}
ESTADO_OK = {"/ia/eventos": 201, "/registro": 201}


@pytest.fixture(autouse=True)
def _sin_groq(monkeypatch):
    """/ia/voz pide a Groq los filtros; en las pruebas nunca se sale a la red: el intérprete devuelve None y
    la búsqueda cae a texto plano."""

    class _SinGroq:
        def parsear(self, texto, valores=None):
            return None

    monkeypatch.setattr("app.inteligencia.casos_uso.cu21_buscar_prendas_por_voz.obtener_parser_voz", lambda: _SinGroq())


class _Inexistentes:
    """Ids que no existen en ninguna empresa (para la petición de control)."""

    codigo = "tienda-a"

    class _Ids:
        def __getitem__(self, _):
            return ID_INEXISTENTE

    ids = _Ids()


def sufijo_de(clave: tuple[str, str]) -> str:
    return clave[1].removeprefix(PREFIJO)


def peticion(clave, ids_de, codigo: str | None, *, viejo: bool = False) -> tuple[str, str, dict]:
    """(método, url, argumentos de `client.request`) de la ruta pública `clave`. Los ids salen de `ids_de`
    (un Universo o `_Inexistentes`); `codigo` es la tienda de la ruta. `viejo`: la ruta equivalente sin tienda."""
    metodo, ruta = clave
    sufijo = sufijo_de(clave)
    url = API + sufijo if viejo else ruta.replace("{codigo}", codigo)
    for nombre in parametros_de(url):
        url = url.replace("{" + nombre + "}", str(ids_de.ids[PARAMETROS[nombre]]))
    ids = ids_de.ids
    extra = {
        "/catalogo/buscar": {"params": {"q": "-producto"}},
        "/inventario/disponibilidad": {"params": {"variante_id": ids["variante"]}},
        "/envios/cotizar": {"json": {"direccion_id": ids["direccion"], "cantidad_prendas": 1}},
        "/ia/eventos": {"json": {"tipo_evento": "vista", "producto_id": ids["producto"]}},
        "/ia/voz": {"json": {"texto": "-producto"}},
        "/registro": {
            "json": {"nombre": "Pub", "apellido": "Lico", "email": f"publico{next(_correos)}@tienda.bo", "password": "claveSegura123"}
        },
    }.get(sufijo, {})
    return metodo, url, extra


def ids_de(mundo, modelo, empresa_id: int) -> set[int]:
    tabla = modelo.__table__
    with mundo.engine.connect() as conexion:
        return {fila[0] for fila in conexion.execute(select(tabla.c.id).where(tabla.c.empresa_id == empresa_id))}


def _lado(mundo, lado):
    return (mundo.a, mundo.b) if lado == "A" else (mundo.b, mundo.a)


def _nombre(clave):
    return nombre_corto(clave).replace("/public/{codigo}", "")


# --- 1. cada ruta pública sirve solo a su tienda -----------------------------------------------------------------


def test_hay_30_rutas_publicas():
    # 27 con código de tienda más /public/tiendas, /public/planes, POST /public/contratacion/prueba y las 4 rutas de
    # /public/contratacion/pedidos... (sin código; las 5 de contratación EXENTAS: crean empresas o llaman a PayPal,
    # ver sus notas en rutas_esperadas).
    assert len(PUBLICAS) == 34 and len(CON_CODIGO) == 27


@pytest.mark.parametrize("lado", ["A", "B"])
@pytest.mark.parametrize("clave", CON_CODIGO, ids=[_nombre(c) for c in CON_CODIGO])
def test_la_tienda_devuelve_solo_datos_de_su_empresa(mundo, clave, lado):
    propia, ajena = _lado(mundo, lado)
    metodo, url, extra = peticion(clave, propia, propia.codigo)
    respuesta = mundo.client.request(metodo, url, **extra)
    sufijo = sufijo_de(clave)
    assert respuesta.status_code == ESTADO_OK.get(sufijo, 200), f"{metodo} {url}: {respuesta.status_code} {respuesta.text[:300]}"
    assert ajena.m("") not in respuesta.text, f"marca de la otra empresa en {url}"
    assert ajena.codigo not in respuesta.text.replace(propia.codigo, "")
    if sufijo not in SIN_MARCA:
        assert propia.m("") in respuesta.text, f"{url}: no trae datos de la propia tienda (¿prueba mal armada?)"
    if sufijo == "/sucursales/{sucursal_id}/horarios":
        assert {h["sucursal_id"] for h in respuesta.json()} == {propia.ids["sucursal"]}
    if sufijo == "/inventario/disponibilidad":
        propias = ids_de(mundo, Sucursal, propia.id)
        filas = respuesta.json()
        assert filas and {f["sucursal_id"] for f in filas} <= propias
        assert {f["variante_id"] for f in filas} == {propia.ids["variante"]}


@pytest.mark.parametrize("clave", SIN_REGISTRO, ids=[_nombre(c) for c in SIN_REGISTRO])
def test_un_codigo_inexistente_da_404_tienda_no_encontrada(mundo, clave):
    metodo, url, extra = peticion(clave, mundo.a, "no-existe-e05")
    respuesta = mundo.client.request(metodo, url, **extra)
    assert respuesta.status_code == 404 and respuesta.json() == {"detail": "Tienda no encontrada"}, respuesta.text[:200]


def test_el_registro_en_un_codigo_inexistente_da_404(mundo):
    metodo, url, extra = peticion(("POST", f"{PREFIJO}/registro"), mundo.a, "no-existe-e05")
    respuesta = mundo.client.request(metodo, url, **extra)
    assert respuesta.status_code == 404 and respuesta.json() == {"detail": "Tienda no encontrada"}


@pytest.fixture(scope="module")
def tienda_inactiva(_mundo):
    empresa = crear_descartable(_mundo)
    poner_activa_empresa(_mundo, empresa.id, False)
    yield empresa
    retirar_descartable(_mundo, empresa)


@pytest.fixture(scope="module")
def tienda_suspendida(_mundo):
    empresa = crear_descartable(_mundo)
    poner_estado_suscripcion(_mundo, empresa.id, "suspendida")
    yield empresa
    retirar_descartable(_mundo, empresa)


@pytest.mark.parametrize("clave", CON_CODIGO, ids=[_nombre(c) for c in CON_CODIGO])
def test_una_empresa_inactiva_responde_igual_que_una_inexistente(mundo, tienda_inactiva, clave):
    metodo, url, extra = peticion(clave, mundo.a, tienda_inactiva.codigo)
    inactiva = mundo.client.request(metodo, url, **extra)
    metodo, url, extra = peticion(clave, mundo.a, "no-existe-e05")
    inexistente = mundo.client.request(metodo, url, **extra)
    assert inactiva.status_code == 404 and inactiva.json() == inexistente.json() == {"detail": "Tienda no encontrada"}


EXENTAS_DE_SUSCRIPCION = ["/tienda"]
CON_SUSCRIPCION = [c for c in CON_CODIGO if sufijo_de(c) not in EXENTAS_DE_SUSCRIPCION]


@pytest.mark.parametrize("clave", CON_SUSCRIPCION, ids=[_nombre(c) for c in CON_SUSCRIPCION])
def test_con_la_suscripcion_suspendida_la_tienda_da_403(mundo, tienda_suspendida, clave):
    metodo, url, extra = peticion(clave, mundo.a, tienda_suspendida.codigo)
    respuesta = mundo.client.request(metodo, url, **extra)
    cuerpo = respuesta.json()
    assert respuesta.status_code == 403, f"{metodo} {url}: {respuesta.status_code} {respuesta.text[:200]}"
    assert cuerpo["detail"] == "suscripcion_no_activa" and cuerpo["codigo"] == "suscripcion_no_activa"


def test_los_datos_de_la_tienda_siguen_publicos_con_la_suscripcion_suspendida(mundo, tienda_suspendida):
    respuesta = mundo.client.get(f"{API}/public/{tienda_suspendida.codigo}/tienda")
    assert respuesta.status_code == 200
    assert respuesta.json()["disponible"] is False and respuesta.json()["codigo"] == tienda_suspendida.codigo


@pytest.mark.parametrize("lado", ["A", "B"])
def test_los_datos_de_la_tienda_son_solo_cuatro_campos_mas_disponible(mundo, lado):
    propia, ajena = _lado(mundo, lado)
    cuerpo = mundo.client.get(f"{API}/public/{propia.codigo}/tienda").json()
    assert set(cuerpo) == {"codigo", "nombre", "logo_url", "color_acento", "disponible"}
    assert cuerpo["codigo"] == propia.codigo and cuerpo["disponible"] is True


# --- un token de la otra empresa se trata como anónimo ----------------------------------------------------------------

SIN_TIENDA_NI_REGISTRO = [c for c in SIN_REGISTRO if sufijo_de(c) != "/tienda"]


@pytest.mark.parametrize("lado", ["A", "B"])
@pytest.mark.parametrize("clave", SIN_TIENDA_NI_REGISTRO, ids=[_nombre(c) for c in SIN_TIENDA_NI_REGISTRO])
def test_un_token_de_la_otra_empresa_se_trata_como_anonimo(mundo, clave, lado):
    propia, ajena = _lado(mundo, lado)
    metodo, url, extra = peticion(clave, propia, propia.codigo)
    anonimo = mundo.client.request(metodo, url, **extra)
    for quien in ("admin", "cliente"):
        con_token = mundo.client.request(metodo, url, headers=ajena.headers[quien], **extra)
        assert con_token.status_code == anonimo.status_code, f"{quien} de la otra empresa: {con_token.status_code} {con_token.text[:200]}"
        assert con_token.text == anonimo.text, f"{quien} de la otra empresa cambió la respuesta de {url}"
        assert ajena.m("") not in con_token.text


@pytest.mark.parametrize("lado", ["A", "B"])
def test_un_token_de_la_otra_empresa_no_impide_registrarse(mundo, lado):
    propia, ajena = _lado(mundo, lado)
    metodo, url, extra = peticion(("POST", f"{PREFIJO}/registro"), propia, propia.codigo)
    respuesta = mundo.client.request(metodo, url, headers=ajena.admin, **extra)
    assert respuesta.status_code == 201, respuesta.text[:200]


# --- las rutas viejas equivalentes, sin token ----------------------------------------------------------------------------

VIEJAS = [c for c in SIN_REGISTRO if sufijo_de(c) != "/tienda"]


@pytest.mark.parametrize("clave", VIEJAS, ids=[_nombre(c) for c in VIEJAS])
def test_la_ruta_vieja_equivalente_sin_token_da_401(mundo, clave):
    metodo, url, extra = peticion(clave, mundo.a, None, viejo=True)
    assert (metodo, API + sufijo_de(clave)) in RUTAS, "la ruta vieja equivalente ya no existe (¿cambió el registro?)"
    respuesta = mundo.client.request(metodo, url, **extra)
    assert respuesta.status_code == 401, f"{metodo} {url}: {respuesta.status_code} {respuesta.text[:200]}"


# --- ids de la otra empresa en una tienda: 404 como si no existieran ---------------------------------------------------------

CON_IDS = [
    c for c in SIN_REGISTRO if parametros_de(c[1].replace("{codigo}", "")) or sufijo_de(c) in ("/envios/cotizar", "/ia/eventos", "/inventario/disponibilidad")
]


@pytest.mark.parametrize("lado", ["A", "B"])
@pytest.mark.parametrize("clave", CON_IDS, ids=[_nombre(c) for c in CON_IDS])
def test_un_id_de_la_otra_empresa_en_la_tienda_da_404_como_uno_inexistente(mundo, clave, lado):
    propia, ajena = _lado(mundo, lado)
    metodo, url, extra = peticion(clave, ajena, propia.codigo)
    ajeno = mundo.client.request(metodo, url, **extra)
    metodo, url_control, extra_control = peticion(clave, _Inexistentes, propia.codigo)
    control = mundo.client.request(metodo, url_control, **extra_control)
    assert ajeno.status_code == 404, f"{metodo} {url}: {ajeno.status_code} {ajeno.text[:200]}"
    assert control.status_code == 404
    usados = [ID_INEXISTENTE, *ajena.ids.values()]
    assert normalizar(ajeno.text, [i for i in usados if isinstance(i, int)]) == normalizar(control.text, [ID_INEXISTENTE])
    assert ajena.m("") not in ajeno.text


# --- 2. catálogo con el mismo SKU y código en las dos empresas -------------------------------------------------------------


def test_el_universo_repite_sku_y_codigo_en_las_dos_empresas(mundo):
    assert mundo.a.ids["sku"] == mundo.b.ids["sku"]
    assert mundo.a.ids["variante"] != mundo.b.ids["variante"]


@pytest.mark.parametrize("lado", ["A", "B"])
@pytest.mark.parametrize("busqueda", ["sku", "codigo", "nombre"])
def test_buscar_variantes_con_el_mismo_sku_trae_solo_filas_de_la_empresa_del_token(mundo, busqueda, lado):
    propia, ajena = _lado(mundo, lado)
    q = {"sku": propia.ids["sku"], "codigo": "CAM-001", "nombre": propia.m("producto")}[busqueda]
    respuesta = mundo.client.get(f"{API}/catalogo/variantes/buscar", params={"q": q}, headers=propia.admin)
    assert respuesta.status_code == 200, respuesta.text[:200]
    filas = respuesta.json()
    assert propia.ids["variante"] in {f["variante_id"] for f in filas}
    assert {f["variante_id"] for f in filas} <= ids_de(mundo, ProductoVariante, propia.id)
    assert {f["producto_id"] for f in filas} <= ids_de(mundo, Producto, propia.id)
    assert ajena.m("") not in respuesta.text and ajena.ids["variante"] not in {f["variante_id"] for f in filas}


@pytest.mark.parametrize("lado", ["A", "B"])
@pytest.mark.parametrize("q", ["-producto", "CAM-001"], ids=["texto_comun", "codigo_repetido"])
def test_buscar_en_el_catalogo_trae_solo_productos_de_la_empresa_del_token(mundo, q, lado):
    propia, ajena = _lado(mundo, lado)
    respuesta = mundo.client.get(f"{API}/catalogo/buscar", params={"q": q}, headers=propia.admin)
    assert respuesta.status_code == 200, respuesta.text[:200]
    assert {p["id"] for p in respuesta.json()} <= ids_de(mundo, Producto, propia.id)
    assert ajena.m("") not in respuesta.text
    if q == "-producto":  # el texto libre busca en el nombre: las dos empresas lo tienen, cada una ve el suyo
        assert propia.ids["producto"] in {p["id"] for p in respuesta.json()}


@pytest.mark.parametrize("lado", ["A", "B"])
def test_la_busqueda_publica_con_texto_comun_trae_solo_la_tienda(mundo, lado):
    propia, ajena = _lado(mundo, lado)
    respuesta = mundo.client.get(f"{API}/public/{propia.codigo}/catalogo/buscar", params={"q": "-producto"})
    assert respuesta.status_code == 200
    assert {p["id"] for p in respuesta.json()} <= ids_de(mundo, Producto, propia.id)
    assert propia.ids["producto"] in {p["id"] for p in respuesta.json()}
    assert ajena.m("") not in respuesta.text


@pytest.mark.parametrize("lado", ["A", "B"])
def test_disponibilidad_trae_solo_sucursales_de_la_empresa_y_la_variante_ajena_es_404(mundo, lado):
    propia, ajena = _lado(mundo, lado)
    propio = mundo.client.get(
        f"{API}/inventario/disponibilidad", params={"variante_id": propia.ids["variante"]}, headers=propia.admin
    )
    assert propio.status_code == 200
    assert propio.json() and {f["sucursal_id"] for f in propio.json()} <= ids_de(mundo, Sucursal, propia.id)
    ajeno = mundo.client.get(
        f"{API}/inventario/disponibilidad", params={"variante_id": ajena.ids["variante"]}, headers=propia.admin
    )
    inexistente = mundo.client.get(
        f"{API}/inventario/disponibilidad", params={"variante_id": ID_INEXISTENTE}, headers=propia.admin
    )
    assert ajeno.status_code == inexistente.status_code == 404
    assert ajeno.json() == inexistente.json()


# --- 3. GET /public/tiendas -------------------------------------------------------------------------------------------------


def _tiendas(mundo, **params) -> list[dict]:
    respuesta = mundo.client.get(f"{API}/public/tiendas", params=params)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def test_las_tiendas_son_solo_cuatro_campos_sin_ids_ni_datos_del_administrador(mundo):
    tiendas = _tiendas(mundo, tamanio=50)
    assert {"tienda-a", "tienda-b"} <= {t["codigo"] for t in tiendas}
    for tienda in tiendas:
        assert set(tienda) == {"codigo", "nombre", "logo_url", "color_acento"}
    texto = json.dumps(tiendas)
    assert "admin@" not in texto and "MARCA-" not in texto
    # No se puede buscar por datos del administrador ni de los recursos de la tienda.
    assert _tiendas(mundo, q="admin@tienda.bo") == []
    assert _tiendas(mundo, q="MARCA-") == []


def test_una_tienda_suspendida_cancelada_o_inactiva_desaparece_de_la_lista(mundo):
    with empresa_descartable(mundo) as empresa:
        codigo = empresa.codigo
        assert [t["codigo"] for t in _tiendas(mundo, q=codigo)] == [codigo]
        for estado in ("suspendida", "cancelada"):
            poner_estado_suscripcion(mundo, empresa.id, estado)
            assert _tiendas(mundo, q=codigo) == [], estado
            if estado == "suspendida":
                poner_estado_suscripcion(mundo, empresa.id, "activa")
                assert [t["codigo"] for t in _tiendas(mundo, q=codigo)] == [codigo]
        # Cancelada es final: la tienda no vuelve aunque la empresa siga activa.
        poner_estado_suscripcion(mundo, empresa.id, "cancelada")
        assert _tiendas(mundo, q=codigo) == []
    # Las de A y B no se enteran de nada de esto.
    assert {"tienda-a", "tienda-b"} <= {t["codigo"] for t in _tiendas(mundo, tamanio=50)}


def test_una_empresa_inactiva_desaparece_de_la_lista(mundo):
    with empresa_descartable(mundo) as empresa:
        assert [t["codigo"] for t in _tiendas(mundo, q=empresa.codigo)] == [empresa.codigo]
        poner_activa_empresa(mundo, empresa.id, False)
        assert _tiendas(mundo, q=empresa.codigo) == []
    assert {"tienda-a", "tienda-b"} <= {t["codigo"] for t in _tiendas(mundo, tamanio=50)}


# --- 4. PASARELA: la empresa sale de la transacción --------------------------------------------------------------------------------

AJUSTES = get_settings()


def _firma(secreto: str, cuerpo: bytes) -> str:
    return hmac.new(secreto.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()


def _webhook(mundo, pasarela: str, id_transaccion: str, *, estado: str = "aprobado", secreto: str | None = None, firma: str | None = None):
    """Webhook firmado como lo haría la pasarela. `firma` fuerza una firma dada (p. ej. una inválida)."""
    cuerpo = json.dumps({"id_transaccion": id_transaccion, "estado": estado}).encode("utf-8")
    secretos = {"libelula": AJUSTES.libelula_webhook_secret, "paypal": AJUSTES.paypal_webhook_secret}
    cabeceras = {"Content-Type": "application/json", "x-signature": firma or _firma(secreto or secretos[pasarela], cuerpo)}
    return mundo.client.post(f"{API}/pagos/webhook/{pasarela}", content=cuerpo, headers=cabeceras)


def nueva_transaccion(universo, pasarela: str) -> dict:
    """Una venta pendiente de pago, con su pago 'iniciado' y su transacción de `pasarela` (como si el cliente
    hubiera elegido pagar así). Es nueva: no toca la transacción del universo ni las ventas que usan otras pruebas."""
    n = universo.n()
    venta = universo._venta_pendiente()
    with universo.orm() as db:
        metodo = db.scalar(select(MetodoPago).where(MetodoPago.codigo == pasarela))
        estado = db.scalar(select(EstadoPago).where(EstadoPago.codigo == "iniciado"))
        pago = Pago(venta_id=venta["id"], metodo_pago_id=metodo.id, estado_id=estado.id, monto=Decimal(venta["total"]))
        db.add(pago)
        db.flush()
        identificador = f"{'QR' if pasarela == 'qr_online' else 'TXN'}-{universo.tag}-E05-{n:04d}"
        db.add(
            TransaccionPasarela(
                pago_id=pago.id,
                pasarela=pasarela,
                id_transaccion=identificador,
                payload_envio={"marca": universo.m("transaccion-e05")},
                estado="pendiente",
            )
        )
        db.flush()
        pago_id = pago.id  # antes de confirmar: al salir del bloque la sesión expira los objetos
    return {"venta_id": venta["id"], "pago_id": pago_id, "id_transaccion": identificador, "total": venta["total"]}


def _estado_venta(mundo, universo, venta_id: int) -> str:
    respuesta = mundo.client.get(f"{API}/ventas/{venta_id}/comprobante", headers=universo.admin)
    assert respuesta.status_code == 200, respuesta.text[:200]
    return respuesta.json()["estado"]


def _intactas(mundo, antes: dict, empresas) -> None:
    for empresa in empresas:
        cambios = mundo.cambios(antes[empresa.id], mundo.instantanea(empresa.id))
        assert cambios == [], f"la empresa {empresa.tag} cambió: {cambios}"


@pytest.mark.parametrize("lado", ["A", "B"])
def test_el_webhook_de_una_empresa_aprueba_su_pago_y_no_cambia_a_la_otra(mundo, lado):
    propia, ajena = _lado(mundo, lado)
    transaccion = nueva_transaccion(propia, "libelula")
    assert _estado_venta(mundo, propia, transaccion["venta_id"]) == "pendiente_pago"
    antes_propia, antes_ajena = mundo.instantanea(propia.id), mundo.instantanea(ajena.id)

    # Sin token ni empresa en la petición: solo la transacción dice de quién es.
    respuesta = _webhook(mundo, "libelula", transaccion["id_transaccion"])

    assert respuesta.status_code == 200, respuesta.text[:300]
    assert respuesta.json()["estado"] == "aprobado"
    assert _estado_venta(mundo, propia, transaccion["venta_id"]) == "pagada"
    assert mundo.cambios(antes_propia, mundo.instantanea(propia.id)), "el webhook no cambió nada en su empresa (¿prueba mal armada?)"
    _intactas(mundo, {ajena.id: antes_ajena}, [ajena])


@pytest.mark.parametrize("lado", ["A", "B"])
def test_confirmar_la_pantalla_qr_resuelve_la_empresa_por_la_transaccion(mundo, lado):
    propia, ajena = _lado(mundo, lado)
    transaccion = nueva_transaccion(propia, "qr_online")
    antes_ajena = mundo.instantanea(ajena.id)

    respuesta = mundo.client.post(f"{API}/pagos/qr/{transaccion['id_transaccion']}/confirmar")

    assert respuesta.status_code == 200, respuesta.text[:300]
    assert respuesta.json()["estado"] == "aprobado"
    assert _estado_venta(mundo, propia, transaccion["venta_id"]) == "pagada"
    _intactas(mundo, {ajena.id: antes_ajena}, [ajena])


@pytest.mark.parametrize("lado", ["A", "B"])
def test_la_pantalla_qr_muestra_solo_su_transaccion(mundo, lado):
    propia, ajena = _lado(mundo, lado)
    suya, de_la_otra = nueva_transaccion(propia, "qr_online"), nueva_transaccion(ajena, "qr_online")
    antes = {propia.id: mundo.instantanea(propia.id), ajena.id: mundo.instantanea(ajena.id)}

    pantalla = mundo.client.get(f"{API}/pagos/qr/{suya['id_transaccion']}")
    # Con el token de la OTRA empresa se ve lo mismo: la empresa sale del id de la transacción, no de la sesión.
    con_token_ajeno = mundo.client.get(f"{API}/pagos/qr/{suya['id_transaccion']}", headers=ajena.admin)

    assert pantalla.status_code == 200 and con_token_ajeno.text == pantalla.text
    assert suya["id_transaccion"] in pantalla.text and f"Bs {suya['total']}" in pantalla.text
    assert de_la_otra["id_transaccion"] not in pantalla.text and f"Bs {de_la_otra['total']}" not in pantalla.text
    _intactas(mundo, antes, [propia, ajena])  # mirar la pantalla no cambia nada


@pytest.mark.parametrize("lado", ["A", "B"])
def test_una_transaccion_de_una_empresa_no_se_confirma_con_el_id_en_otra_pasarela(mundo, lado):
    """Firma válida, pero la transacción de B no existe bajo esa pasarela (o bajo la pantalla QR): 404, y nada cambia."""
    propia, ajena = _lado(mundo, lado)
    transaccion = nueva_transaccion(ajena, "libelula")
    antes = {propia.id: mundo.instantanea(propia.id), ajena.id: mundo.instantanea(ajena.id)}
    id_ = transaccion["id_transaccion"]

    respuestas = {
        "webhook paypal": _webhook(mundo, "paypal", id_),
        "webhook qr_online": _webhook(mundo, "qr_online", id_, secreto=AJUSTES.qr_online_webhook_secret),
        "pantalla qr": mundo.client.get(f"{API}/pagos/qr/{id_}", headers=propia.admin),
        "confirmar qr": mundo.client.post(f"{API}/pagos/qr/{id_}/confirmar", headers=propia.admin),
    }
    for nombre, respuesta in respuestas.items():
        assert respuesta.status_code == 404, f"{nombre}: {respuesta.status_code} {respuesta.text[:200]}"
    _intactas(mundo, antes, [propia, ajena])
    assert _estado_venta(mundo, ajena, transaccion["venta_id"]) == "pendiente_pago"


@pytest.mark.parametrize("lado", ["A", "B"])
def test_la_transaccion_de_una_empresa_no_existe_para_la_otra_en_el_webhook_de_la_misma_pasarela(mundo, lado):
    """Un id que no es de nadie da 404 con firma válida y no toca a ninguna empresa."""
    propia, ajena = _lado(mundo, lado)
    antes = {propia.id: mundo.instantanea(propia.id), ajena.id: mundo.instantanea(ajena.id)}
    respuesta = _webhook(mundo, "libelula", f"TXN-{propia.tag}-NO-EXISTE")
    assert respuesta.status_code == 404
    _intactas(mundo, antes, [propia, ajena])


def test_firma_invalida_da_403_sin_leer_nada_y_sin_distinguir_ids(mundo):
    a, b = mundo.a, mundo.b
    existente = nueva_transaccion(a, "libelula")["id_transaccion"]
    antes = {a.id: mundo.instantanea(a.id), b.id: mundo.instantanea(b.id)}
    casos = {
        "id real de A": existente,
        "id del universo de B": b.ids["id_transaccion"],
        "id inexistente": "TXN-QUE-NO-EXISTE",
    }
    respuestas = []
    for nombre, id_ in casos.items():
        for variante, kwargs in (
            ("firma basura", {"firma": "firma-trucha"}),
            ("secreto equivocado", {"secreto": "otro-secreto-que-no-es-el-del-servidor"}),
        ):
            respuesta = _webhook(mundo, "libelula", id_, **kwargs)
            assert respuesta.status_code == 403, f"{nombre} / {variante}: {respuesta.status_code} {respuesta.text[:200]}"
            respuestas.append(respuesta.json())
    # Sin cabecera de firma tampoco.
    cuerpo = json.dumps({"id_transaccion": existente, "estado": "aprobado"}).encode("utf-8")
    sin_firma = mundo.client.post(f"{API}/pagos/webhook/libelula", content=cuerpo, headers={"Content-Type": "application/json"})
    assert sin_firma.status_code == 403
    # Un id real y uno inventado responden exactamente igual: no se puede sondear ids.
    assert all(r == respuestas[0] for r in respuestas) and sin_firma.json() == respuestas[0]
    _intactas(mundo, antes, [a, b])


def test_una_pasarela_desconocida_da_404_sin_tocar_nada(mundo):
    antes = {mundo.a.id: mundo.instantanea(mundo.a.id), mundo.b.id: mundo.instantanea(mundo.b.id)}
    respuesta = mundo.client.post(f"{API}/pagos/webhook/no-existe", content=b"{}", headers={"x-signature": "x"})
    assert respuesta.status_code == 404
    _intactas(mundo, antes, [mundo.a, mundo.b])


def test_las_tres_rutas_de_pasarela_estan_cubiertas():
    pasarela = rutas_de({"PASARELA"})
    assert len(pasarela) == 3
    assert {c[1] for c in pasarela} == {
        f"{API}/pagos/webhook/{{pasarela}}",
        f"{API}/pagos/qr/{{id_transaccion}}",
        f"{API}/pagos/qr/{{id_transaccion}}/confirmar",
    }
