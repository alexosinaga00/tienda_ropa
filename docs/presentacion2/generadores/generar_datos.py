"""Extrae el diseño de datos físico real desde los modelos SQLAlchemy del backend:
tablas agrupadas por paquete, columnas con tipo/tamaño/nulo/llave, y el script
DDL de PostgreSQL. Escribe datos_fisicos.json y script_postgres.sql.

Uso (con el venv del backend):
    backend/.venv/Scripts/python.exe generar_datos.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

AQUI = Path(__file__).parent
BACKEND = AQUI.parents[1] / "tiendaoficial" / "tienda_ropa" / "backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "solo-para-generar-documentacion")

import app.main  # noqa: E402,F401  (registra todos los modelos)
from app.core.database import Base  # noqa: E402
from sqlalchemy import Boolean, Date, DateTime, Integer, BigInteger, SmallInteger, Numeric, String, Text, Time  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.schema import CreateTable  # noqa: E402

DESCRIPCIONES = {
    "id": "Identificador único del registro.",
    "activo": "Indica si el registro está vigente (borrado lógico).",
    "creado_en": "Fecha y hora de creación del registro.",
    "actualizado_en": "Fecha y hora de la última modificación.",
    "creado_por": "Usuario que creó el registro.",
    "nombre": "Nombre descriptivo.",
    "descripcion": "Descripción del registro.",
    "codigo": "Código único de negocio.",
    "email": "Correo electrónico, usado como identificador de acceso.",
    "password_hash": "Hash bcrypt de la contraseña (nunca texto plano).",
    "telefono": "Número de teléfono de contacto.",
    "direccion": "Dirección física.",
    "estado": "Estado actual dentro de su ciclo de vida.",
    "fecha": "Fecha y hora de la operación.",
    "cantidad": "Cantidad de unidades.",
    "precio": "Precio de venta.",
    "total": "Importe total.",
    "subtotal": "Importe antes de descuentos.",
    "observacion": "Observación libre.",
    "sku": "Código de inventario de la variante.",
    "cantidad_fisica": "Unidades físicamente presentes en la sucursal.",
    "cantidad_reservada": "Unidades bloqueadas por reservas o ventas pendientes.",
    "cantidad_disponible": "Columna generada: física menos reservada.",
    "costo_promedio": "Costo promedio ponderado vigente.",
    "costo_unitario": "Costo por unidad de la operación.",
}


def tipo_y_tamano(col) -> tuple[str, str]:
    t = col.type
    nombre = t.compile(dialect=postgresql.dialect()).lower()
    if isinstance(t, String) and not isinstance(t, Text):
        return nombre, f"{t.length} caracteres" if t.length else "variable"
    if isinstance(t, Text):
        return nombre, "variable"
    if isinstance(t, BigInteger):
        return nombre, "8 bytes"
    if isinstance(t, SmallInteger):
        return nombre, "2 bytes"
    if isinstance(t, Integer):
        return nombre, "4 bytes"
    if isinstance(t, Numeric):
        return nombre, f"{t.precision},{t.scale} dígitos" if t.precision else "variable"
    if isinstance(t, Boolean):
        return nombre, "1 byte"
    if isinstance(t, DateTime):
        return nombre, "8 bytes"
    if isinstance(t, Date):
        return nombre, "4 bytes"
    if isinstance(t, Time):
        return nombre, "8 bytes"
    return nombre, "variable"


def descripcion(tabla: str, col) -> str:
    if col.name in DESCRIPCIONES:
        return DESCRIPCIONES[col.name]
    fks = list(col.foreign_keys)
    if fks:
        return f"Referencia a {fks[0].column.table.name}."
    return col.name.replace("_", " ").capitalize() + "."


def paquete_de(tabla) -> str:
    for mapper in Base.registry.mappers:
        if mapper.local_table is tabla:
            return mapper.class_.__module__.split(".")[1]
    return "seguridad" if tabla.name in ("usuario_rol", "rol_permiso") else "otros"


tablas = []
for tabla in Base.metadata.sorted_tables:
    unicas = {c.name for c in tabla.columns if c.unique}
    for restr in tabla.constraints:
        if restr.__class__.__name__ == "UniqueConstraint" and len(restr.columns) == 1:
            unicas.update(c.name for c in restr.columns)
    compuestas = [
        [c.name for c in r.columns]
        for r in tabla.constraints
        if r.__class__.__name__ == "UniqueConstraint" and len(r.columns) > 1
    ]
    columnas = []
    for col in tabla.columns:
        tipo, tam = tipo_y_tamano(col)
        llaves = []
        if col.primary_key:
            llaves.append("PK")
        if col.foreign_keys:
            llaves.append("FK → " + next(iter(col.foreign_keys)).column.table.name)
        if col.name in unicas:
            llaves.append("Única")
        if any(col.name in comp for comp in compuestas):
            llaves.append("Única compuesta")
        columnas.append({
            "nombre": col.name,
            "tipo": tipo,
            "tamano": tam,
            "nulo": "Sí" if col.nullable and not col.primary_key else "No",
            "llave": ", ".join(llaves),
            "descripcion": descripcion(tabla.name, col),
        })
    tablas.append({"nombre": tabla.name, "paquete": paquete_de(tabla), "columnas": columnas})

ORDEN = ["seguridad", "organizacion", "catalogo", "abastecimiento", "inventario", "reservas",
         "ventas", "pagos", "entregas", "probador", "inteligencia", "core", "otros"]
tablas.sort(key=lambda t: (ORDEN.index(t["paquete"]) if t["paquete"] in ORDEN else 99, t["nombre"]))

ddl = []
for tabla in Base.metadata.sorted_tables:
    ddl.append(str(CreateTable(tabla).compile(dialect=postgresql.dialect())).strip() + ";\n")

(AQUI / "datos_fisicos.json").write_text(json.dumps(tablas, ensure_ascii=False, indent=1), encoding="utf8")
(AQUI / "script_postgres.sql").write_text("\n".join(ddl), encoding="utf8")
print(len(tablas), "tablas;", sum(len(t["columnas"]) for t in tablas), "columnas")
print({p: sum(1 for t in tablas if t["paquete"] == p) for p in ORDEN})
