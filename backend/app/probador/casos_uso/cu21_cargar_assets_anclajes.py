"""CU-21 — Cargar assets y marcar anclajes

Actor: Administrador.
Precondición: sesión de administrador con el permiso probador.gestionar; la
variante existe.
Postcondición: la variante queda habilitada para el vestidor virtual con
sus anclajes validados.
"""

import io

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.core import storage
from app.core.exceptions import DomainError
from app.catalogo import politicas as catalogo_politicas
from app.probador.models import ActivoProbador
from app.probador.repository import ActivoRepository
from app.probador.schemas import AnclajesActualizar

TIPOS_VALIDOS = {"overlay_2d", "flatlay_ia", "thumb"}
LADO_MINIMO_PX = 512
TAMANIO_MAXIMO_BYTES = 3 * 1024 * 1024  # 3MB


class CargarAssetsAnclajes:
    def __init__(self) -> None:
        self._activos = ActivoRepository()

    def _validar_png_con_alfa(self, contenido: bytes) -> tuple[int, int]:
        """Abre el archivo con Pillow (no confía en la extensión ni en el
        content-type que mandó el cliente) y confirma que sea un PNG real
        con canal alfa, y que cumpla el tamaño mínimo/máximo."""
        if len(contenido) > TAMANIO_MAXIMO_BYTES:
            raise DomainError("El archivo supera el tamaño máximo permitido (3MB)")

        try:
            imagen = Image.open(io.BytesIO(contenido))
            imagen.load()
        except UnidentifiedImageError as exc:
            raise DomainError("El archivo no es una imagen válida") from exc

        if imagen.format != "PNG":
            raise DomainError("El archivo debe ser un PNG")

        tiene_alfa = imagen.mode in ("RGBA", "LA") or "transparency" in imagen.info
        if not tiene_alfa:
            raise DomainError("El PNG debe tener canal alfa real")

        ancho, alto = imagen.size
        if ancho < LADO_MINIMO_PX or alto < LADO_MINIMO_PX:
            raise DomainError(f"La imagen debe medir al menos {LADO_MINIMO_PX}px de lado")

        return ancho, alto

    def subir(
        self,
        db: Session,
        variante_id: int,
        tipo: str,
        contenido: bytes,
        content_type: str | None,
        creado_por: int | None,
    ) -> tuple[ActivoProbador, str]:
        catalogo_politicas.obtener_variante(db, variante_id)  # 404 si no existe

        if tipo not in TIPOS_VALIDOS:
            raise DomainError(f"tipo debe ser uno de {sorted(TIPOS_VALIDOS)}")
        if content_type != "image/png":
            raise DomainError("El archivo debe subirse como image/png")

        ancho, alto = self._validar_png_con_alfa(contenido)

        # Nunca f_auto acá: hay que preservar el canal alfa (ver core/storage.py).
        public_id = storage.subir_imagen(
            contenido, storage.carpeta_probador(variante_id), formato_forzado="png"
        )

        activo = self._activos.crear(db, variante_id, tipo, public_id, ancho, alto, creado_por)
        return activo, storage.url_probador(public_id)

    def guardar_anclajes(self, db: Session, activo_id: int, datos: AnclajesActualizar) -> tuple[ActivoProbador, str]:
        activo = self._activos.obtener(db, activo_id)
        activo = self._activos.guardar_anclajes(db, activo, datos.model_dump())
        return activo, storage.url_probador(activo.url)

    def validar(self, db: Session, activo_id: int) -> tuple[ActivoProbador, str]:
        activo = self._activos.obtener(db, activo_id)
        if activo.estado != "pendiente":
            raise DomainError(f"El asset ya está en estado '{activo.estado}'")
        if not activo.anclajes:
            raise DomainError("No se puede validar un asset sin anclajes")
        activo = self._activos.marcar_validado(db, activo)
        return activo, storage.url_probador(activo.url)

    def clonar_a_variante(
        self, db: Session, activo_id: int, variante_id: int, creado_por: int | None = None
    ) -> ActivoProbador:
        """Asigna un asset ya subido (mismo public_id, anclajes y estado) a
        otra variante del mismo producto. El overlay no cambia entre tallas
        del mismo color, así que no hace falta volver a subir el archivo a
        Cloudinary."""
        origen = self._activos.obtener(db, activo_id)
        variante_origen = catalogo_politicas.obtener_variante(db, origen.variante_id)
        variante_destino = catalogo_politicas.obtener_variante(db, variante_id)
        if variante_origen.producto_id != variante_destino.producto_id:
            raise DomainError("Solo se puede reutilizar un asset entre variantes del mismo producto")

        copia = self._activos.crear(
            db, variante_id, origen.tipo, origen.url, origen.ancho_px, origen.alto_px, creado_por
        )
        if origen.anclajes:
            copia = self._activos.guardar_anclajes(db, copia, dict(origen.anclajes))
        if origen.estado == "validado":
            copia = self._activos.marcar_validado(db, copia)
        return copia

    def listar(self, db: Session, variante_id: int) -> list[tuple[ActivoProbador, str]]:
        catalogo_politicas.obtener_variante(db, variante_id)  # 404 si no existe
        activos = self._activos.listar_por_variante(db, variante_id)
        return [(a, storage.url_probador(a.url)) for a in activos]
