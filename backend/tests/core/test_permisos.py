"""core/permisos.py: las constantes conservan exactamente los códigos que
antes estaban sueltos en los routers y las políticas (y que siembra
scripts/seed_seguridad.py)."""

import ast
import pathlib

from app.core import permisos
from scripts.seed_seguridad import PERMISOS

VALORES_ESPERADOS = {
    "PERMISO_USUARIOS": "usuarios.gestionar",
    "PERMISO_ROLES": "roles.gestionar",
    "PERMISO_ORGANIZACION": "organizacion.gestionar",
    "PERMISO_ALCANCE_GLOBAL": "organizacion.gestionar",
    "PERMISO_PLATAFORMA": "plataforma.gestionar",
    "PERMISO_EMPRESA": "empresa.gestionar",
    "PERMISO_BITACORA_VER": "bitacora.ver",
    "PERMISO_COPIAS": "copias.gestionar",
    "PERMISO_SINCRONIZAR": "sincronizacion.operar",
    "PERMISO_SINCRONIZACION_SUPERVISAR": "sincronizacion.supervisar",
    "PERMISO_SINCRONIZACION_RESOLVER": "sincronizacion.resolver",
    "PERMISO_CATALOGO": "catalogo.gestionar",
    "PERMISO_CATALOGO_VER": "catalogo.ver",
    "PERMISO_INVENTARIO_VER": "inventario.ver",
    "PERMISO_INVENTARIO_GESTIONAR": "inventario.gestionar",
    "PERMISO_ABASTECIMIENTO": "abastecimiento.gestionar",
    "PERMISO_PROBADOR": "probador.gestionar",
    "PERMISO_RESERVAS_CREAR": "reservas.crear",
    "PERMISO_STAFF_RESERVAS": "reservas.gestionar_sucursal",
    "PERMISO_VENTAS_DIGITAL": "ventas.digital",
    "PERMISO_VENTAS_PRESENCIAL": "ventas.presencial",
    "PERMISO_STAFF_VENTAS": "ventas.gestionar_sucursal",
    "PERMISO_VENTAS_GESTIONAR": "ventas.gestionar",
    "PERMISO_PAGOS": "pagos.gestionar",
    "PERMISO_CAJA_SUPERVISAR": "caja.supervisar",
    "PERMISO_ENTREGAS": "entregas.gestionar",
    "PERMISO_REPORTES_VER": "reportes.ver",
}


def _asignaciones() -> dict[str, ast.expr]:
    fuente = pathlib.Path(permisos.__file__).read_text(encoding="utf-8")
    return {
        nodo.targets[0].id: nodo.value
        for nodo in ast.parse(fuente).body
        if isinstance(nodo, ast.Assign) and isinstance(nodo.targets[0], ast.Name)
    }


def test_las_constantes_conservan_los_codigos_de_siempre():
    publicas = {nombre: valor for nombre, valor in vars(permisos).items() if nombre.startswith("PERMISO_")}

    assert publicas == VALORES_ESPERADOS


def test_cada_constante_es_un_permiso_que_siembra_seed_seguridad():
    codigos_sembrados = {codigo for codigo, _modulo, _descripcion in PERMISOS}

    assert set(VALORES_ESPERADOS.values()) <= codigos_sembrados


def test_alcance_global_y_organizacion_son_constantes_distintas_con_el_mismo_valor():
    # Mismo código hoy, distinto significado: no se unifican (ver core/permisos.py).
    asignaciones = _asignaciones()

    assert isinstance(asignaciones["PERMISO_ALCANCE_GLOBAL"], ast.Constant)
    assert isinstance(asignaciones["PERMISO_ORGANIZACION"], ast.Constant)
    assert permisos.PERMISO_ALCANCE_GLOBAL == permisos.PERMISO_ORGANIZACION


def test_los_nombres_de_siempre_siguen_importables_desde_donde_se_importaban():
    from app.comercial import politicas as comercial_politicas
    from app.plataforma import politicas as plataforma_politicas
    from app.plataforma import router as plataforma_router

    assert plataforma_politicas.PERMISO_ALCANCE_GLOBAL == "organizacion.gestionar"
    assert comercial_politicas.PERMISO_STAFF_RESERVAS == "reservas.gestionar_sucursal"
    assert comercial_politicas.PERMISO_STAFF_VENTAS == "ventas.gestionar_sucursal"
    assert plataforma_router.PERMISO_ROLES == "roles.gestionar"
    assert plataforma_router.PERMISO_USUARIOS == "usuarios.gestionar"
    assert plataforma_router.PERMISO_ORGANIZACION == "organizacion.gestionar"


def test_core_permisos_no_importa_de_ningun_paquete():
    fuente = pathlib.Path(permisos.__file__).read_text(encoding="utf-8")

    assert not [n for n in ast.walk(ast.parse(fuente)) if isinstance(n, (ast.Import, ast.ImportFrom))]
