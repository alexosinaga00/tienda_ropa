"""CU-39 — Generar prueba realista con IA

Actor: Cliente, Servicio de inteligencia artificial.
Precondición: sesión de cliente; la variante admite probador y tiene un
overlay validado.
Postcondición: se genera (o se sirve desde caché) una imagen del cliente
con la prenda puesta, y se le sugiere una talla a partir de sus medidas.

Caso de uso COMPUESTO: agrupa la generación de la imagen y la
recomendación de talla, porque la descripción del catálogo las junta
("generar una imagen... y sugerirle una talla").
"""

import datetime as dt
import hashlib
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturoTimeoutError

import httpx
from fastapi import BackgroundTasks
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.core import storage
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.exceptions import DomainError, PermisoDenegadoError
from app.catalogo import politicas as catalogo_politicas
from app.probador.casos_uso.cu22_probar_prenda_modo_espejo import ProbarPrendaModoEspejo
from app.probador.generativo import ProbadorGenerativoBase, obtener_proveedor_generativo
from app.probador.models import ProbadorGeneracion
from app.probador.repository import GeneracionRepository
from app.probador.schemas import TallaRecomendadaRespuesta, TallaRequest
from app.seguridad.politicas import obtener_perfil_cliente

logger = logging.getLogger(__name__)

TAMANIO_MAXIMO_FOTO_BYTES = 8 * 1024 * 1024  # 8MB, foto de celular sin exigir canal alfa
LIMITE_GENERACIONES_DIARIAS = get_settings().probador_limite_diario
TIMEOUT_GENERACION_SEG = 60

# Cuánto se corre el índice de talla (ordenado por talla.orden) según la
# preferencia de ajuste, a partir de la talla que mejor calza con las
# medidas estimadas.
_CORRIMIENTO_AJUSTE = {"ajustado": -1, "regular": 0, "holgado": 1}


def _validar_foto_cliente(contenido: bytes, content_type: str | None) -> None:
    if content_type not in ("image/jpeg", "image/png"):
        raise DomainError("La foto debe ser JPEG o PNG")
    if len(contenido) > TAMANIO_MAXIMO_FOTO_BYTES:
        raise DomainError("La foto supera el tamaño máximo permitido (8MB)")
    try:
        imagen = Image.open(io.BytesIO(contenido))
        imagen.load()
    except UnidentifiedImageError as exc:
        raise DomainError("El archivo no es una imagen válida") from exc


def _descargar_bytes(url: str) -> bytes:
    respuesta = httpx.get(url, timeout=10)
    respuesta.raise_for_status()
    return respuesta.content


def _ejecutar_generacion(
    generacion_id: int, imagen_prenda_url: str, foto_cliente: bytes, proveedor: ProbadorGenerativoBase
) -> None:
    """Corre en segundo plano (FastAPI BackgroundTasks) después de que la
    respuesta de POST /probador/generar ya se envió. Abre su propia sesión
    de base de datos -- la del request que la disparó se cierra apenas
    termina el request, antes de que esto corra.

    `foto_cliente` vive solo en memoria de este proceso en segundo plano y
    se descarta al terminar la función: nunca se escribe a disco ni a la
    base de datos, solo su hash (ya guardado por `iniciar`)."""
    generacion_repo = GeneracionRepository()
    db = SessionLocal()
    try:
        imagen_prenda = _descargar_bytes(imagen_prenda_url)
        ejecutor = ThreadPoolExecutor(max_workers=1)
        try:
            futuro = ejecutor.submit(proveedor.generar, foto_cliente, imagen_prenda)
            try:
                resultado_png = futuro.result(timeout=TIMEOUT_GENERACION_SEG)
            except FuturoTimeoutError:
                generacion_repo.marcar_fallido(db, generacion_id, "Tiempo de espera agotado (60s)")
                return
        finally:
            # wait=False: si el proveedor externo se colgó más allá del
            # timeout, no hay que esperar a que su hilo termine solo -- eso
            # anularía el propio timeout (es lo que hace `with ThreadPoolExecutor`,
            # cuyo __exit__ llama shutdown(wait=True) por defecto).
            ejecutor.shutdown(wait=False)
        generacion = generacion_repo.obtener(db, generacion_id)
        public_id = storage.subir_imagen(
            resultado_png, storage.carpeta_probador_generado(generacion.variante_id), formato_forzado="png"
        )
        url_resultado = storage.url_probador(public_id)
        generacion_repo.marcar_completado(db, generacion_id, url_resultado, proveedor.nombre)
    except Exception:  # noqa: BLE001 -- cualquier falla del proveedor externo termina en 'fallido'
        # El detalle técnico (stacktrace de httpx, del proveedor, etc.)
        # queda en el log del servidor -- al cliente le llega un mensaje
        # genérico, nunca la excepción cruda.
        logger.exception("Falló la generación %s", generacion_id)
        generacion_repo.marcar_fallido(db, generacion_id, "No se pudo generar la imagen. Probá de nuevo más tarde.")
    finally:
        db.close()


def _estimar_medidas(estatura_cm: float, peso_kg: float) -> tuple[float, float]:
    """Heurística aproximada -- no reemplaza una medición real. A partir
    del IMC (desvío respecto de 22, tomado como "sin desvío") ajusta un
    contorno de pecho y cintura proporcional a la estatura, para acotar la
    búsqueda en tabla_medida."""
    estatura_m = estatura_cm / 100
    imc = peso_kg / (estatura_m**2)
    desvio = imc - 22
    pecho_cm = estatura_cm * 0.52 + desvio * 1.8
    cintura_cm = estatura_cm * 0.45 + desvio * 2.2
    return round(pecho_cm, 1), round(cintura_cm, 1)


def _en_rango(valor: float, minimo, maximo) -> bool:
    if minimo is not None and valor < float(minimo):
        return False
    if maximo is not None and valor > float(maximo):
        return False
    return True


def _distancia_centro_pecho(medida, pecho_cm: float) -> float:
    if medida.pecho_min_cm is not None and medida.pecho_max_cm is not None:
        centro = (float(medida.pecho_min_cm) + float(medida.pecho_max_cm)) / 2
    elif medida.pecho_min_cm is not None:
        centro = float(medida.pecho_min_cm)
    elif medida.pecho_max_cm is not None:
        centro = float(medida.pecho_max_cm)
    else:
        return 0.0
    return abs(centro - pecho_cm)


class GenerarPruebaRealistaIA:
    def __init__(self) -> None:
        self._generaciones = GeneracionRepository()
        self._modo_espejo = ProbarPrendaModoEspejo()

    def iniciar(
        self,
        db: Session,
        usuario_id: int,
        variante_id: int,
        contenido_foto: bytes,
        content_type: str | None,
        background_tasks: BackgroundTasks,
    ) -> tuple[ProbadorGeneracion, bool]:
        """POST /probador/generar. Devuelve la generación (cacheada o
        recién creada en estado 'en_proceso') y si vino de caché."""
        variante = catalogo_politicas.obtener_variante(db, variante_id)  # 404 si no existe
        if not variante.producto.admite_probador:
            raise DomainError("Esta prenda no admite probador virtual")
        _validar_foto_cliente(contenido_foto, content_type)

        cliente = obtener_perfil_cliente(db, usuario_id)
        hash_foto = hashlib.sha256(contenido_foto).hexdigest()

        cacheado = self._generaciones.buscar_completado(db, hash_foto, variante_id)
        if cacheado is not None:
            return cacheado, True

        _, overlay_url, _, flatlay_url = self._modo_espejo.obtener_assets(db, variante_id)
        imagen_prenda_url = flatlay_url or overlay_url

        # "por día" = desde la medianoche del servidor, no una ventana
        # rodante de 24hs -- así el límite se resetea a una hora predecible.
        inicio_dia = dt.datetime.combine(dt.date.today(), dt.time.min)
        usadas_hoy = self._generaciones.contar_desde(db, cliente.id, inicio_dia)
        if usadas_hoy >= LIMITE_GENERACIONES_DIARIAS:
            raise DomainError(
                f"Alcanzaste el máximo de {LIMITE_GENERACIONES_DIARIAS} generaciones por día", status_code=429
            )

        generacion = self._generaciones.crear(db, cliente.id, variante_id, hash_foto)

        proveedor = obtener_proveedor_generativo()
        background_tasks.add_task(_ejecutar_generacion, generacion.id, imagen_prenda_url, contenido_foto, proveedor)

        return generacion, False

    def consultar(self, db: Session, usuario_id: int, generacion_id: int) -> ProbadorGeneracion:
        generacion = self._generaciones.obtener(db, generacion_id)
        cliente = obtener_perfil_cliente(db, usuario_id)
        if generacion.cliente_id != cliente.id:
            raise PermisoDenegadoError("Esta generación no te pertenece")
        return generacion

    def recomendar_talla(self, db: Session, datos: TallaRequest) -> TallaRecomendadaRespuesta:
        pecho_cm, cintura_cm = _estimar_medidas(datos.estatura_cm, datos.peso_kg)
        catalogo_politicas.obtener_variante(db, datos.variante_id)  # 404 si no existe
        medidas = catalogo_politicas.listar_medidas_para_variante(db, datos.variante_id)

        if not medidas:
            return TallaRecomendadaRespuesta(
                talla_id=None,
                talla_codigo=None,
                pecho_estimado_cm=pecho_cm,
                cintura_estimado_cm=cintura_cm,
                advertencia="Esta prenda no tiene tabla de medidas cargada; no se puede recomendar una talla.",
            )

        tallas = {medida.talla_id: catalogo_politicas.obtener_talla(db, medida.talla_id) for medida in medidas}
        medidas_ordenadas = sorted(medidas, key=lambda medida: tallas[medida.talla_id].orden)

        exactas = [
            medida
            for medida in medidas_ordenadas
            if _en_rango(pecho_cm, medida.pecho_min_cm, medida.pecho_max_cm)
            and _en_rango(cintura_cm, medida.cintura_min_cm, medida.cintura_max_cm)
        ]
        candidatas = exactas or [
            medida for medida in medidas_ordenadas if _en_rango(pecho_cm, medida.pecho_min_cm, medida.pecho_max_cm)
        ]

        advertencia = None
        if candidatas:
            elegida = candidatas[0]
        else:
            elegida = min(medidas_ordenadas, key=lambda medida: _distancia_centro_pecho(medida, pecho_cm))
            advertencia = "Ninguna talla calza exactamente con las medidas estimadas; se sugiere la más cercana."

        indice = medidas_ordenadas.index(elegida)
        indice_final = min(
            max(indice + _CORRIMIENTO_AJUSTE[datos.preferencia_ajuste], 0), len(medidas_ordenadas) - 1
        )
        talla_final = tallas[medidas_ordenadas[indice_final].talla_id]

        return TallaRecomendadaRespuesta(
            talla_id=talla_final.id,
            talla_codigo=talla_final.codigo,
            pecho_estimado_cm=pecho_cm,
            cintura_estimado_cm=cintura_cm,
            advertencia=advertencia,
        )
