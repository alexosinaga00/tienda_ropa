"""Configuración del registro (logs) del backend.

Python, por omisión, solo muestra avisos y errores: los mensajes informativos (la sincronización escribe una línea
`clave=valor` por lote y por operación, RNF10) no aparecen en los registros de Railway si nadie los enciende. Esto los
enciende SOLO para los loggers de la aplicación (`app.*`): las librerías (httpx, SQLAlchemy...) siguen en WARNING para no
llenar los registros ni volcar direcciones o datos de más.

Infraestructura: no importa ningún paquete de negocio."""

from __future__ import annotations

import logging

FORMATO = "%(asctime)s %(levelname)s %(name)s %(message)s"
NIVELES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def nivel_valido(nivel: str) -> str:
    """El nombre del nivel en mayúsculas; uno desconocido se reemplaza por INFO (un error de tipeo no apaga los logs)."""
    texto = (nivel or "").strip().upper()
    return texto if texto in NIVELES else "INFO"


def configurar_logs(nivel: str = "INFO") -> None:
    """Enciende los logs de `app.*` en `nivel`. Si el proceso aún no tiene un manejador de logs (uvicorn no pone uno en
    la raíz) agrega uno que escribe a la salida estándar con fecha y hora; si ya hay uno (las pruebas, otro arranque) no
    lo duplica. Se puede llamar varias veces."""
    nivel = nivel_valido(nivel)
    raiz = logging.getLogger()
    if not raiz.handlers:
        logging.basicConfig(level=logging.WARNING, format=FORMATO)
    logging.getLogger("app").setLevel(getattr(logging, nivel))
