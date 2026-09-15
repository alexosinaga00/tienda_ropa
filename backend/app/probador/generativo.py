"""Interfaz del modo generativo del probador.

Todo lo que sabe llamar a un proveedor de IA generativa externo vive
detrás de `ProbadorGenerativoBase`. El resto del paquete (`service.py`)
solo conoce esta interfaz, nunca al proveedor concreto: cambiar de
Vertex AI a otra cosa es escribir una clase nueva acá, no tocar el flujo
de caché, límites ni persistencia.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod

from app.core.config import get_settings

PROMPT_PROBADOR = (
    "Genera una imagen fotorrealista de la persona de la primera imagen "
    "vistiendo la prenda que aparece en la segunda imagen (una vista plana "
    "de la prenda). Conservá la pose, el fondo y el rostro de la persona "
    "sin alterarlos; reemplazá únicamente la ropa del torso superior."
)


class ProbadorGenerativoBase(ABC):
    """Cada implementación concreta llama a un proveedor distinto de IA
    generativa. `nombre` se guarda en `probador_generacion.proveedor` para
    saber, a futuro, con qué proveedor se generó cada resultado."""

    nombre: str

    @abstractmethod
    def generar(self, foto_cliente: bytes, imagen_prenda: bytes) -> bytes:
        """Recibe la foto del cliente y una imagen de referencia de la
        prenda (el flat-lay u overlay validado), ambas en memoria, y
        devuelve los bytes de la imagen PNG generada. Ninguna de las dos
        imágenes de entrada se persiste acá: es responsabilidad del
        llamador descartarlas después de esta llamada."""
        raise NotImplementedError


class VertexAIProbadorGenerativo(ProbadorGenerativoBase):
    """Prueba virtual generativa vía Vertex AI (Google Gen AI SDK, modo
    `vertexai=True`). Las credenciales se resuelven por Application
    Default Credentials (variable de entorno GOOGLE_APPLICATION_CREDENTIALS
    o el entorno de Railway/GCP) — nunca hay una clave en el código."""

    nombre = "vertex_ai"

    def __init__(self) -> None:
        settings = get_settings()
        self._project = settings.vertex_project_id
        self._location = settings.vertex_location
        self._modelo = settings.vertex_modelo
        self._credenciales_json = settings.google_credentials_json

    def _credenciales(self):
        """Sin GOOGLE_CREDENTIALS_JSON devuelve None y el SDK usa las
        Application Default Credentials (GOOGLE_APPLICATION_CREDENTIALS)."""
        if not self._credenciales_json:
            return None
        from google.oauth2 import service_account

        return service_account.Credentials.from_service_account_info(
            json.loads(self._credenciales_json),
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )

    def _cliente(self):
        from google import genai

        if not self._project:
            raise RuntimeError("VERTEX_PROJECT_ID no está configurado")
        return genai.Client(
            vertexai=True, project=self._project, location=self._location, credentials=self._credenciales()
        )

    def generar(self, foto_cliente: bytes, imagen_prenda: bytes) -> bytes:
        from google.genai import types

        cliente = self._cliente()
        respuesta = cliente.models.generate_content(
            model=self._modelo,
            contents=[
                types.Part.from_bytes(data=foto_cliente, mime_type="image/jpeg"),
                types.Part.from_bytes(data=imagen_prenda, mime_type="image/png"),
                PROMPT_PROBADOR,
            ],
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        for parte in respuesta.parts:
            if parte.inline_data:
                return parte.inline_data.data
        raise RuntimeError("Vertex AI no devolvió ninguna imagen")


def obtener_proveedor_generativo() -> ProbadorGenerativoBase:
    return VertexAIProbadorGenerativo()
