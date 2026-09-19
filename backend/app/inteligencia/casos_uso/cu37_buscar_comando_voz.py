"""CU-37 — Buscar prendas por comando de voz

Actor: Cliente, Servicio de inteligencia artificial.
Precondición: ninguna (funciona también en búsqueda anónima).
Postcondición: se devuelven los resultados del catálogo que coinciden con
lo dictado, y se registra la consulta.

Recibe el texto ya transcrito por el dispositivo, pide a Groq un JSON
estricto de filtros, lo valida con Pydantic, y si falla cae a búsqueda de
texto plano. La búsqueda la ejecuta llamando a CU-10 del paquete catalogo.
"""

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.catalogo.casos_uso.cu10_buscar_filtrar_prendas import BuscarFiltrarPrendas
from app.catalogo.schemas import FiltrosCatalogo
from app.core.deps import ParametrosPaginacion
from app.inteligencia.groq_cliente import obtener_parser_voz
from app.inteligencia.repository import ConsultaVozRepository
from app.inteligencia.schemas import GENEROS_VALIDOS, VozRespuesta
from app.organizacion import politicas as organizacion_politicas
from app.seguridad.politicas import obtener_perfil_cliente

CANTIDAD_RESULTADOS = 20


def _genero_valido(genero: str | None) -> str | None:
    """Groq puede devolver cualquier string en `genero`; solo se usa como
    filtro si matchea uno de los cuatro valores que catalogo.schemas.Genero
    acepta (case-insensitive), si no se descarta ese campo sin romper el
    resto de la búsqueda."""
    if genero and genero.strip().lower() in GENEROS_VALIDOS:
        return genero.strip().lower()
    return None


class BuscarComandoVoz:
    def __init__(self) -> None:
        self._consultas = ConsultaVozRepository()
        self._buscar_prendas = BuscarFiltrarPrendas()

    def ejecutar(self, db: Session, texto: str, usuario) -> VozRespuesta:
        """POST /api/v1/ia/voz. `usuario` es `None` en búsqueda anónima."""
        valores = catalogo_politicas.listar_valores_referencia(db)
        filtros_voz = obtener_parser_voz().parsear(texto, valores)

        etiquetas: dict[str, str] = {}
        sucursal_id = None
        if filtros_voz is None:
            # Groq no configurado, falló, o su JSON no validó: fallback
            # explícito a búsqueda de texto plano sobre el catálogo.
            filtros = FiltrosCatalogo(texto=texto)
        else:
            filtros = catalogo_politicas.resolver_filtros_por_nombre(
                db,
                categoria=filtros_voz.categoria,
                material=filtros_voz.material,
                color=filtros_voz.color,
                talla=filtros_voz.talla,
                temporada=filtros_voz.temporada,
                genero=_genero_valido(filtros_voz.genero),
                precio_max=filtros_voz.precio_max,
            )
            sucursal_id = organizacion_politicas.resolver_sucursal_por_nombre(db, filtros_voz.sucursal)
            filtros = filtros.model_copy(update={"sucursal_id": sucursal_id})

            if filtros.categoria_id is not None:
                etiquetas["categoria"] = filtros_voz.categoria
            if filtros.material_id is not None:
                etiquetas["material"] = filtros_voz.material
            if filtros.color_id is not None:
                etiquetas["color"] = filtros_voz.color
            if filtros.talla_id is not None:
                etiquetas["talla"] = filtros_voz.talla
            if filtros.temporada_id is not None:
                etiquetas["temporada"] = filtros_voz.temporada
            if filtros.genero is not None:
                etiquetas["genero"] = filtros.genero
            if filtros.precio_max is not None:
                etiquetas["precio_max"] = str(filtros.precio_max)
            if sucursal_id is not None:
                etiquetas["sucursal"] = filtros_voz.sucursal

        paginacion = ParametrosPaginacion(pagina=1, tamanio=CANTIDAD_RESULTADOS)
        resultados = self._buscar_prendas.buscar(db, paginacion, filtros)

        cliente_id = obtener_perfil_cliente(db, usuario.id).id if usuario else None
        # mode="json": precio_max es Decimal, y el encoder JSON estándar que
        # usa psycopg para la columna JSONB no lo serializa (a diferencia de
        # la respuesta HTTP, que pasa por el jsonable_encoder de FastAPI).
        filtros_json = filtros_voz.model_dump(mode="json") if filtros_voz is not None else {"texto": texto}
        self._consultas.crear(db, cliente_id, texto, filtros_json, len(resultados))

        return VozRespuesta(resultados=resultados, filtros=filtros, etiquetas=etiquetas, cantidad=len(resultados))
