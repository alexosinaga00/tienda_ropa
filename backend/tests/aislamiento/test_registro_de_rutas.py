"""E05, 4.1: pruebas guardianas del registro de rutas. Hacen fallar la suite si
alguien agrega, quita o cambia una ruta sin pasar por `rutas_esperadas.py`."""

from fastapi.routing import APIRoute

from app.main import app

from .introspeccion import funcionalidades_de, metodo_y_ruta, permisos_de, rutas_api
from .rutas_esperadas import EXENTA, RUTAS

CLASES_DE_NEGOCIO = {"POR_ID", "LISTADO", "CREA_O_ACCION", "PROPIA"}
# 12 + las 4 rutas de la compra de un plan (`/public/contratacion/pedidos...`): anónimas, sin {codigo} y con servicio
# externo (PayPal) o creación de empresa; la matriz pública por tienda no puede ejecutarlas. Ver sus notas.
MAXIMO_DE_EXENTAS = 16
LARGO_MINIMO_DE_NOTA = 20
RUTAS_NO_API = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}

COMO_CLASIFICAR = (
    "Agrégala a tests/aislamiento/rutas_esperadas.py con su clase (POR_ID, LISTADO, "
    "CREA_O_ACCION, PROPIA, PUBLICA, PLATAFORMA, MI_EMPRESA, PASARELA, SERVICIO o AUTH), "
    "el permiso y la funcionalidad de plan que exige, y cobertura MATRIZ (o EXENTA con la "
    "razón por escrito). Si es de negocio, también un cuerpo de ejemplo en plantillas.py. "
    "Puedes partir de: python -m tests.aislamiento.generar_rutas"
)


def _como_lista(valor) -> list[str]:
    if valor is None:
        return []
    return sorted([valor] if isinstance(valor, str) else valor)


def test_toda_ruta_esta_clasificada():
    sin_clasificar = sorted(metodo_y_ruta() - set(RUTAS))
    assert not sin_clasificar, (
        f"Hay {len(sin_clasificar)} ruta(s) sin clasificar en el registro de aislamiento:\n  "
        + "\n  ".join(f"{m} {p}" for m, p in sin_clasificar)
        + f"\n{COMO_CLASIFICAR}"
    )


def test_no_hay_entradas_obsoletas():
    obsoletas = sorted(set(RUTAS) - metodo_y_ruta())
    assert not obsoletas, (
        "rutas_esperadas.py tiene entradas de rutas que ya no existen:\n  "
        + "\n  ".join(f"{m} {p}" for m, p in obsoletas)
        + "\nBórralas del registro."
    )


def test_las_exenciones_tienen_razon():
    exentas = {clave: ruta for clave, ruta in RUTAS.items() if ruta.cobertura == EXENTA}
    sin_razon = sorted(f"{m} {p}" for (m, p), ruta in exentas.items() if len(ruta.nota.strip()) < LARGO_MINIMO_DE_NOTA)
    assert not sin_razon, f"Rutas EXENTAS sin razón de al menos {LARGO_MINIMO_DE_NOTA} caracteres: {sin_razon}"
    assert len(exentas) <= MAXIMO_DE_EXENTAS, (
        f"Hay {len(exentas)} rutas EXENTAS (máximo {MAXIMO_DE_EXENTAS}). Subir el tope exige editar "
        "MAXIMO_DE_EXENTAS en esta prueba y justificarlo en la revisión de la etapa."
    )


def test_cobertura_valida():
    invalidas = sorted(f"{m} {p}: {r.cobertura}" for (m, p), r in RUTAS.items() if r.cobertura not in {"MATRIZ", EXENTA})
    assert not invalidas, f"Cobertura inválida (solo MATRIZ o EXENTA): {invalidas}"


def test_permiso_y_funcionalidad_declarados_coinciden():
    por_clave = {(metodo, ruta.path): ruta for ruta in rutas_api() for metodo in ruta.methods}
    distintas = []
    for (metodo, path), declarada in RUTAS.items():
        real = por_clave[(metodo, path)]
        if permisos_de(real) != _como_lista(declarada.permiso):
            distintas.append(f"{metodo} {path}: permiso real {permisos_de(real)}, declarado {_como_lista(declarada.permiso)}")
        if funcionalidades_de(real) != _como_lista(declarada.funcionalidad):
            distintas.append(
                f"{metodo} {path}: funcionalidad real {funcionalidades_de(real)}, "
                f"declarada {_como_lista(declarada.funcionalidad)}"
            )
    assert not distintas, "El registro no coincide con lo que la ruta exige hoy:\n  " + "\n  ".join(distintas)


def test_ruta_de_negocio_sin_permiso_esta_anotada_como_solo_autenticado():
    sueltas = sorted(
        f"{m} {p}"
        for (m, p), r in RUTAS.items()
        if r.clase in CLASES_DE_NEGOCIO and not _como_lista(r.permiso) and not r.nota.startswith("solo autenticado")
    )
    assert not sueltas, (
        "Rutas de negocio sin permiso que no están anotadas como 'solo autenticado' "
        f"(¿se olvidó require_permission?): {sueltas}"
    )


def test_rutas_no_api():
    no_api = {getattr(r, "path", None) for r in app.routes if not isinstance(r, APIRoute)}
    assert no_api == RUTAS_NO_API, f"Rutas que no son APIRoute: {sorted(map(str, no_api))}"


def test_sin_marcas_revisar():
    pendientes = sorted(f"{m} {p}" for (m, p), r in RUTAS.items() if "REVISAR" in r.nota)
    assert not pendientes, f"El generador dejó rutas por revisar a mano: {pendientes}"
