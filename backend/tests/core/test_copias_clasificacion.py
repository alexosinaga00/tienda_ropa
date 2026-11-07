"""E22, G1-G3: la lista explícita de lo que la copia incluye, referencia y excluye.

Esta prueba es la que impide que alguien agregue una tabla sin decidir si se respalda, y que una columna con
aspecto de secreto llegue al ZIP."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.core import copias
from app.core.database import Base

ESPERADAS_EXCLUIDAS = {
    "copia_seguridad", "metodo_pago_guardado", "modelo_ml", "pedido_contratacion", "permiso", "probador_generacion",
    "rol_permiso", "transaccion_pasarela",
}  # fmt: skip


# ---- G1: cada tabla está en exactamente una categoría -------------------------------------------------------------


def test_g1_cada_tabla_esta_en_exactamente_una_categoria():
    assert copias.tablas_sin_clasificar() == [], (
        "Cada tabla de Base.metadata debe estar en exactamente una de TABLAS_INCLUIDAS, TABLAS_REFERENCIA o "
        "TABLAS_EXCLUIDAS (core/copias.py): decide si se respalda antes de agregarla."
    )


def test_g1_los_conteos_y_las_listas_no_tienen_repetidos():
    assert len(set(copias.TABLAS_INCLUIDAS)) == len(copias.TABLAS_INCLUIDAS) == 54
    assert len(set(copias.TABLAS_REFERENCIA)) == len(copias.TABLAS_REFERENCIA) == 7
    assert set(copias.TABLAS_EXCLUIDAS) == ESPERADAS_EXCLUIDAS
    assert 54 + 7 + 8 == len(Base.metadata.tables) == 69


def test_g1_el_detector_ve_una_tabla_sin_clasificar(monkeypatch):
    """Control del detector: si dejara de ver una tabla nueva, G1 sería un falso verde."""
    nueva = sa.Table("tabla_nueva_sin_clasificar", sa.MetaData(), sa.Column("id", sa.Integer, primary_key=True))
    nueva.to_metadata(Base.metadata)
    try:
        assert copias.tablas_sin_clasificar() == ["tabla_nueva_sin_clasificar (en 0 categorías)"]
    finally:
        Base.metadata.remove(Base.metadata.tables["tabla_nueva_sin_clasificar"])
    assert copias.tablas_sin_clasificar() == []


def test_g1_toda_tabla_con_empresa_id_esta_incluida_o_excluida_a_proposito():
    """Una tabla de empresa nunca queda fuera de la copia por descuido: o se copia o está excluida con su razón."""
    for nombre, tabla in Base.metadata.tables.items():
        if "empresa_id" in tabla.c:
            assert nombre in copias.TABLAS_INCLUIDAS or nombre in copias.TABLAS_EXCLUIDAS, nombre
    for razon in copias.TABLAS_EXCLUIDAS.values():
        assert len(razon) >= 20


# ---- G2: toda tabla incluida tiene camino a la empresa ------------------------------------------------------------


def _sql(nombre: str) -> str:
    consulta = copias.consulta_de(nombre, 7)
    return str(consulta.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_g2_toda_tabla_incluida_se_filtra_por_empresa():
    for nombre in copias.TABLAS_INCLUIDAS:
        sql = _sql(nombre)
        if nombre == "empresa":
            assert "empresa.id = 7" in sql
        elif nombre == "usuario_rol":
            assert "usuario.empresa_id = 7" in sql  # hereda la empresa de su usuario
        else:
            assert f"{nombre}.empresa_id = 7" in sql, f"{nombre}: la consulta no filtra por empresa_id"


def test_g2_las_referencias_solo_traen_lo_que_la_empresa_usa_o_son_catalogos_del_sistema():
    assert "suscripcion.empresa_id = 7" in _sql("plan")
    assert "usuario.empresa_id = 7" in _sql("rol")
    for nombre in ("estado_pago", "estado_reserva", "estado_venta", "metodo_pago", "tipo_movimiento"):
        assert " WHERE " not in _sql(nombre)  # catálogos pequeños del sistema, iguales para todas las empresas


def test_g2_las_consultas_van_ordenadas_por_clave_primaria():
    for nombre in (*copias.TABLAS_INCLUIDAS, *copias.TABLAS_REFERENCIA):
        assert " ORDER BY " in _sql(nombre), nombre


# ---- G3: ninguna columna sensible sale en la copia ---------------------------------------------------------------


def test_g3_ninguna_columna_copiada_parece_un_secreto():
    for nombre in (*copias.TABLAS_INCLUIDAS, *copias.TABLAS_REFERENCIA):
        for columna in copias.columnas_copiadas(nombre):
            assert copias.PATRON_COLUMNA_SENSIBLE.search(columna.name.lower()) is None, f"{nombre}.{columna.name}"


def test_g3_password_hash_ip_y_la_columna_generada_estan_omitidas():
    assert "password_hash" in copias.columnas_omitidas("usuario")
    assert "ip" in copias.columnas_omitidas("bitacora")
    assert "cantidad_disponible" in copias.columnas_omitidas("stock")
    assert "password_hash" not in {c.name for c in copias.columnas_copiadas("usuario")}
    descripcion = copias.descripcion_de_tablas()["columnas_excluidas"]
    assert descripcion["usuario"] == ["password_hash"]
    assert descripcion["bitacora"] == ["ip"]


def test_g3_ninguna_tabla_copiada_tiene_columnas_binarias():
    for nombre in (*copias.TABLAS_INCLUIDAS, *copias.TABLAS_REFERENCIA):
        for columna in copias.columnas_copiadas(nombre):
            assert not isinstance(columna.type, sa.LargeBinary), f"{nombre}.{columna.name}"


def test_g3_el_patron_reconoce_los_nombres_de_secretos():
    for nombre in ("password", "password_hash", "token_acceso", "api_key", "secret", "clave_api", "credencial", "hash_foto"):
        assert copias.PATRON_COLUMNA_SENSIBLE.search(nombre), nombre
    for nombre in ("nombre", "email", "monto", "creado_en", "orden"):
        assert not copias.PATRON_COLUMNA_SENSIBLE.search(nombre), nombre


def test_g3_las_tablas_de_secretos_estan_excluidas():
    for nombre in (
        "transaccion_pasarela", "probador_generacion", "modelo_ml", "copia_seguridad", "pedido_contratacion",
        "metodo_pago_guardado",
    ):  # fmt: skip
        assert nombre in copias.TABLAS_EXCLUIDAS
        assert nombre not in copias.TABLAS_INCLUIDAS
