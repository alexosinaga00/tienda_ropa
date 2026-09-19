"""CU-32 — Recomendar productos al cliente

Actor: Cliente, Servicio de inteligencia artificial.
Precondición: ninguna (funciona también para navegación anónima).
Postcondición: se sugieren hasta 6 prendas, nunca una lista vacía.

Híbrido de tres capas: reglas (stock disponible, temporada vigente,
excluir lo ya comprado), historial (ponderar por eventos de navegación y
uso del probador) y Groq (ordenar los candidatos y redactar el motivo).
Si el cliente no tiene historial, recomienda por popularidad de la
temporada vigente.
"""

import datetime as dt
from collections import defaultdict

from sqlalchemy.orm import Session

from app.catalogo import politicas as catalogo_politicas
from app.catalogo.schemas import CatalogoItemRespuesta
from app.inteligencia.groq_cliente import obtener_rankeador_recomendacion
from app.inteligencia.repository import HistorialNavegacionRepository, RecomendacionRepository
from app.inteligencia.schemas import CandidatoRecomendacion, PerfilClienteRecomendacion, RecomendacionItemRespuesta, RecomendacionesRespuesta
from app.inventario.politicas import listar_variantes_con_stock
from app.probador.politicas import listar_sesiones_recientes_cliente
from app.seguridad.politicas import obtener_perfil_cliente
from app.ventas.politicas import contar_ventas_por_variante, listar_variantes_compradas

CANTIDAD_CANDIDATOS = 20
CANTIDAD_FINAL = 6

_PESO_TIPO_EVENTO = {"favorito": 3.0, "carrito": 2.5, "vista": 1.0, "busqueda": 0.5}
_PESO_PROBADOR = 2.0

_MOTIVO_GENERICO_HISTORIAL = "Basado en lo que viste recientemente"
_MOTIVO_GENERICO_POPULAR = "Popular esta temporada"


class RecomendarProductos:
    def __init__(self) -> None:
        self._historial = HistorialNavegacionRepository()
        self._recomendaciones = RecomendacionRepository()

    def _candidatos_por_reglas(self, db: Session, cliente_id: int | None, excluir_producto_id: int | None) -> set[int]:
        """Capa 1: variantes con stock disponible, de temporada vigente,
        excluyendo lo ya comprado por el cliente. Si eso deja cero
        candidatos (temporada sin stock, caso límite) se relaja a
        "cualquier variante con stock" -- nunca se devuelve una lista
        vacía por esta capa."""
        candidatos = listar_variantes_con_stock(db)
        vigentes = catalogo_politicas.listar_variantes_temporada_vigente(db)
        if vigentes:
            candidatos &= vigentes
        if cliente_id is not None:
            candidatos -= listar_variantes_compradas(db, cliente_id)
        if excluir_producto_id is not None:
            candidatos -= catalogo_politicas.listar_variantes_de_producto(db, excluir_producto_id)

        if not candidatos:
            candidatos = listar_variantes_con_stock(db)
            if excluir_producto_id is not None:
                candidatos -= catalogo_politicas.listar_variantes_de_producto(db, excluir_producto_id)

        return candidatos

    def _top_variantes(self, db: Session, cliente_id: int | None, candidatos: set[int]) -> tuple[list[int], bool]:
        """Capa 2: pondera candidatos según historial_navegacion (peso por
        tipo de evento, más peso a lo reciente) y uso del probador. Sin
        historial (cliente nuevo o anónimo) cae a popularidad por ventas de
        la temporada vigente. Devuelve (top 20 ids, True si vino de
        historial real)."""
        puntajes: dict[int, float] = defaultdict(float)
        if cliente_id is not None:
            # `evento.creado_en`/`sesion.creado_en` vienen de columnas
            # TIMESTAMP WITHOUT TIME ZONE (server_default=func.now() en
            # UTC): SQLAlchemy los devuelve como datetime naive que
            # representan UTC. Restarles dt.datetime.now() (hora LOCAL del
            # proceso, también naive) desfasa "antigüedad_dias" por el
            # offset horario del servidor si no corre en UTC -- acá se arma
            # un "ahora" naive pero en UTC, para restar naive contra naive
            # de forma consistente.
            ahora = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
            for evento in self._historial.listar_reciente_por_cliente(db, cliente_id, limite=100):
                if evento.variante_id is None or evento.variante_id not in candidatos:
                    continue
                antiguedad_dias = max((ahora - evento.creado_en).days, 0)
                peso = _PESO_TIPO_EVENTO.get(evento.tipo_evento, 0.5)
                puntajes[evento.variante_id] += peso / (1 + antiguedad_dias)

            for sesion in listar_sesiones_recientes_cliente(db, cliente_id, limite=50):
                if sesion.variante_id not in candidatos:
                    continue
                antiguedad_dias = max((ahora - sesion.creado_en).days, 0)
                puntajes[sesion.variante_id] += _PESO_PROBADOR / (1 + antiguedad_dias)

        if puntajes:
            ordenados = sorted(puntajes, key=puntajes.get, reverse=True)
            resto = [v for v in candidatos if v not in puntajes]
            return (ordenados + resto)[:CANTIDAD_CANDIDATOS], True

        conteo = contar_ventas_por_variante(db, list(candidatos))
        ordenados = sorted(candidatos, key=lambda v: conteo.get(v, 0), reverse=True)
        return ordenados[:CANTIDAD_CANDIDATOS], False

    def _colapsar_por_producto(self, items: dict[int, CatalogoItemRespuesta], orden: list[int]) -> list[int]:
        """De varias variantes candidatas del mismo producto se queda con
        la de mejor puntaje (la primera en `orden`) -- el carrusel muestra
        tarjetas de producto, no de talla/color."""
        vistos: set[int] = set()
        resultado: list[int] = []
        for variante_id in orden:
            item = items.get(variante_id)
            if item is None or item.id in vistos:
                continue
            vistos.add(item.id)
            resultado.append(variante_id)
        return resultado

    def ejecutar(self, db: Session, usuario, excluir_producto_id: int | None = None) -> RecomendacionesRespuesta:
        """POST /api/v1/ia/recomendaciones. `usuario` es `None` en
        navegación anónima -- se calcula y devuelve la recomendación
        igual, pero no se persiste (recomendacion.cliente_id es NOT NULL,
        no hay a quién asociarla)."""
        cliente_id = obtener_perfil_cliente(db, usuario.id).id if usuario else None

        candidatos = self._candidatos_por_reglas(db, cliente_id, excluir_producto_id)
        if not candidatos:
            return RecomendacionesRespuesta(recomendaciones=[])

        top_ids, hay_historial = self._top_variantes(db, cliente_id, candidatos)
        items = catalogo_politicas.listar_items_por_variantes(db, top_ids)
        top_ids = self._colapsar_por_producto(items, top_ids)

        candidatos_groq = [
            CandidatoRecomendacion(
                variante_id=v,
                nombre=items[v].nombre,
                categoria_id=items[v].categoria_id,
                precio_base=items[v].precio_base,
            )
            for v in top_ids
        ]
        resultado_groq = obtener_rankeador_recomendacion().rankear(
            candidatos_groq, PerfilClienteRecomendacion(hay_historial=hay_historial)
        )

        ids_validos = {c.variante_id for c in candidatos_groq}
        finales: list[tuple[int, str]] = []
        if resultado_groq:
            finales = [(fila.variante_id, fila.motivo) for fila in resultado_groq if fila.variante_id in ids_validos]
            finales = finales[:CANTIDAD_FINAL]

        if not finales:
            motivo_generico = _MOTIVO_GENERICO_HISTORIAL if hay_historial else _MOTIVO_GENERICO_POPULAR
            finales = [(v, motivo_generico) for v in top_ids[:CANTIDAD_FINAL]]

        recomendaciones = [
            RecomendacionItemRespuesta(variante_id=v, producto=items[v], motivo=motivo)
            for v, motivo in finales
            if v in items
        ]

        if cliente_id is not None and recomendaciones:
            self._recomendaciones.crear_lote(
                db, cliente_id, [(r.variante_id, None, r.motivo) for r in recomendaciones]
            )

        return RecomendacionesRespuesta(recomendaciones=recomendaciones)
