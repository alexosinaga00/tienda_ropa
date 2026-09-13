"""Carga las prendas del dataset (catalogo.json + JPG + overlays PNG) al
catálogo y al probador virtual. Idempotente y reanudable.

Por cada prenda del JSON:
  1. Producto `FS-{id}` (categoría Poleras/Chamarras, género hombre, tallas
     L y XL, precio fijo) vía catalogo.service.crear_producto().
  2. Foto JPG de catálogo -> fashionstore/productos/{producto_id}/ vía
     catalogo.service.subir_imagen_producto().
  3. Overlay PNG -> fashionstore/probador/{variante_L_id}/ vía
     probador.service.subir_asset(), con anclajes calculados a partir de
     la máscara alfa, y validado. La variante XL reutiliza el mismo archivo
     (probador.service.clonar_asset_a_variante), sin volver a subirlo.

Por defecto NO escribe nada (dry-run): muestra lo que haría y genera una
hoja de vista previa con los anclajes dibujados. Para escribir de verdad
hace falta --ejecutar. Cada corrida real deja un manifiesto en backups/
con todo lo creado, que sirve para deshacer con --revertir.

Uso (desde backend/):
    python -m scripts.seed_prendas_probador --origen "<carpeta>"
    python -m scripts.seed_prendas_probador --origen "<carpeta>" --solo 10005 --ejecutar
    python -m scripts.seed_prendas_probador --origen "<carpeta>" --ejecutar
    python -m scripts.seed_prendas_probador --revertir backups/manifiesto_prendas_XXXX.json --ejecutar

Variables de entorno para --ejecutar: DATABASE_URL, JWT_SECRET_KEY (la
exige Settings, cualquier valor sirve acá) y CLOUDINARY_*.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import statistics
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageDraw

DIR_BACKUPS = Path(__file__).resolve().parent.parent / "backups"

TAMANIO_MAXIMO_PNG = 3 * 1024 * 1024  # mismo límite que probador.service
LADO_MINIMO_PX = 512
TALLAS = ["L", "XL"]

CATEGORIA_PADRE = "Ropa superior"
CATEGORIA_POR_TIPO = {"Tshirts": "Poleras", "Jackets": "Chamarras"}

COLORES: dict[str, tuple[str, str]] = {
    "White": ("Blanco", "#FFFFFF"),
    "Black": ("Negro", "#1A1A1A"),
    "Blue": ("Azul", "#1D4ED8"),
    "Navy Blue": ("Azul marino", "#1E3A5F"),
    "Red": ("Rojo", "#DC2626"),
    "Grey": ("Gris", "#9CA3AF"),
    "Yellow": ("Amarillo", "#FACC15"),
}

PRECIO_POLERA = Decimal("149.00")
PRECIO_POLO_JERSEY = Decimal("189.00")
PRECIO_CHAMARRA = Decimal("399.00")

USOS = {"Sports": "deportivo", "Casual": "casual"}

# Palabras del nombre original que no aportan al nombre en español: género,
# tipo de prenda (ya va como prefijo) y abreviaturas del dataset.
_PALABRAS_DESCARTADAS = {
    "men", "mens", "men's", "women", "women's", "womens", "as", "ss",
    "t-shirt", "t-shirts", "tshirt", "tshirts", "jersey", "jerseys",
    "jacket", "jackets", "polo",
}


# ---- Mapeos (sin base de datos) ---------------------------------------------


@dataclass
class PrendaPlan:
    id_dataset: int
    codigo: str
    nombre: str
    descripcion: str
    categoria: str
    color: str
    color_hex: str
    temporada: str
    anio: int
    fecha_inicio: dt.date
    fecha_fin: dt.date
    precio: Decimal
    ruta_jpg: Path
    ruta_png: Path


def _tipo_y_precio(item: dict) -> tuple[str, Decimal]:
    nombre = item["productDisplayName"].lower()
    if item["articleType"] == "Jackets":
        return "Chamarra", PRECIO_CHAMARRA
    if "polo" in nombre:
        return "Polo", PRECIO_POLO_JERSEY
    if "jersey" in nombre:
        return "Camiseta", PRECIO_POLO_JERSEY
    return "Polera", PRECIO_POLERA


def _nombre_es(item: dict, tipo: str, color_es: str) -> str:
    palabras = item["productDisplayName"].split()
    marca = palabras[0]
    colores = {p.lower() for p in item["baseColour"].split()}
    modelo = [
        p
        for p in palabras[1:]
        if p.lower() not in _PALABRAS_DESCARTADAS and p.lower() not in colores and p.lower() != marca.lower()
    ]
    partes = [tipo, marca, *modelo]
    return f"{' '.join(partes)} ({color_es})"[:120]


def _temporada(item: dict) -> tuple[str, int, dt.date, dt.date]:
    anio = int(item["year"])
    # Hemisferio sur (Bolivia).
    if item["season"] == "Summer":
        return "Verano", anio, dt.date(anio, 12, 1), dt.date(anio + 1, 2, 28)
    if item["season"] == "Fall":
        return "Otoño", anio, dt.date(anio, 3, 1), dt.date(anio, 5, 31)
    if item["season"] == "Winter":
        return "Invierno", anio, dt.date(anio, 6, 1), dt.date(anio, 8, 31)
    return "Primavera", anio, dt.date(anio, 9, 1), dt.date(anio, 11, 30)


def planificar(origen: Path, solo: set[int] | None) -> list[PrendaPlan]:
    items = json.loads((origen / "catalogo.json").read_text(encoding="utf-8"))
    planes: list[PrendaPlan] = []
    for item in items:
        if solo and item["id"] not in solo:
            continue
        if item["articleType"] not in CATEGORIA_POR_TIPO:
            raise ValueError(f"{item['id']}: articleType '{item['articleType']}' sin categoría mapeada")
        if item["baseColour"] not in COLORES:
            raise ValueError(f"{item['id']}: color '{item['baseColour']}' sin mapeo")
        color_es, color_hex = COLORES[item["baseColour"]]
        tipo, precio = _tipo_y_precio(item)
        temporada, anio, inicio, fin = _temporada(item)
        uso = USOS.get(item.get("usage", ""), item.get("usage", "").lower())
        planes.append(
            PrendaPlan(
                id_dataset=item["id"],
                codigo=f"FS-{item['id']}",
                nombre=_nombre_es(item, tipo, color_es),
                descripcion=f"{item['productDisplayName']}. Uso {uso}.",
                categoria=CATEGORIA_POR_TIPO[item["articleType"]],
                color=color_es,
                color_hex=color_hex,
                temporada=temporada,
                anio=anio,
                fecha_inicio=inicio,
                fecha_fin=fin,
                precio=precio,
                ruta_jpg=origen / item["archivo"],
                ruta_png=origen / item["overlay"],
            )
        )
    return planes


# ---- PNG del overlay ----------------------------------------------------------


def preparar_png(contenido: bytes) -> tuple[bytes, Image.Image]:
    """Deja el PNG por debajo de 3MB sin perder el canal alfa. Primero
    re-comprime sin pérdida; si no alcanza, reduce el tamaño de a 10%.
    Los anclajes son fracciones 0..1, así que achicar no los invalida."""
    imagen = Image.open(io.BytesIO(contenido))
    imagen.load()
    if imagen.mode != "RGBA":
        imagen = imagen.convert("RGBA")
    if len(contenido) <= TAMANIO_MAXIMO_PNG:
        return contenido, imagen

    escala = 1.0
    while True:
        actual = imagen
        if escala < 1.0:
            nuevo = (round(imagen.width * escala), round(imagen.height * escala))
            if min(nuevo) < LADO_MINIMO_PX:
                raise ValueError("No se pudo bajar el PNG de 3MB sin quedar por debajo de 512px")
            actual = imagen.resize(nuevo, Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        actual.save(buffer, format="PNG", optimize=True)
        if buffer.tell() <= TAMANIO_MAXIMO_PNG:
            return buffer.getvalue(), actual
        escala -= 0.1


# ---- Anclajes automáticos a partir de la máscara alfa -----------------------

_UMBRAL_ALFA = 32
_ANCHO_ANALISIS = 360


def _tramo_que_contiene(fila: list[bool], x: int) -> tuple[int, int]:
    izq = x
    while izq > 0 and fila[izq - 1]:
        izq -= 1
    der = x
    while der < len(fila) - 1 and fila[der + 1]:
        der += 1
    return izq, der


def calcular_anclajes(imagen: Image.Image) -> dict[str, dict[str, float]]:
    """Estima hombro_izq, hombro_der y cadera (fracciones 0..1, izquierda =
    lado izquierdo de la imagen, igual que las plantillas del editor).

    - El torso es el tramo opaco que contiene la columna central, medido
      entre el 55% y el 75% del alto de la prenda (debajo de las mangas
      cortas). La mediana de sus bordes da el ancho del torso.
    - Cada hombro está en el borde del torso, un 3% por debajo del primer
      píxel opaco de esa columna (la costura del hombro, no el contorno).
    - La cadera está en el centro del torso, un 3% por encima del ruedo.
    Es una estimación: se afina a mano en el editor de anclajes si hace falta."""
    alfa = imagen.getchannel("A")
    ancho = _ANCHO_ANALISIS
    alto = max(1, round(imagen.height * ancho / imagen.width))
    datos = alfa.resize((ancho, alto), Image.Resampling.BILINEAR).tobytes()
    filas = [[datos[y * ancho + x] > _UMBRAL_ALFA for x in range(ancho)] for y in range(alto)]

    filas_opacas = [y for y in range(alto) if any(filas[y])]
    if not filas_opacas:
        raise ValueError("El PNG no tiene píxeles opacos")
    y0, y1 = filas_opacas[0], filas_opacas[-1]
    alto_prenda = y1 - y0
    xs = [x for y in filas_opacas for x in (filas[y].index(True), ancho - 1 - filas[y][::-1].index(True))]
    centro_x = (min(xs) + max(xs)) // 2

    izqs: list[int] = []
    ders: list[int] = []
    for y in range(y0 + int(0.55 * alto_prenda), y0 + int(0.75 * alto_prenda) + 1):
        if filas[y][centro_x]:
            izq, der = _tramo_que_contiene(filas[y], centro_x)
            izqs.append(izq)
            ders.append(der)
    torso_izq = int(statistics.median(izqs)) if izqs else min(xs)
    torso_der = int(statistics.median(ders)) if ders else max(xs)
    torso_centro = (torso_izq + torso_der) // 2

    def primera_opaca(x: int) -> int:
        return next((y for y in range(y0, y1 + 1) if filas[y][x]), y0)

    def ultima_opaca(x: int) -> int:
        return next((y for y in range(y1, y0 - 1, -1) if filas[y][x]), y1)

    margen = round(0.03 * alto_prenda)

    def punto(x: int, y: int) -> dict[str, float]:
        return {"x": round(min(max(x / ancho, 0.0), 1.0), 4), "y": round(min(max(y / alto, 0.0), 1.0), 4)}

    hombro_izq_y = primera_opaca(torso_izq) + margen
    hombro_der_y = primera_opaca(torso_der) + margen
    limite_hombros = y0 + 0.4 * alto_prenda
    if hombro_izq_y > limite_hombros or hombro_der_y > limite_hombros:
        # Manga larga pegada al cuerpo: el "torso" medido incluye los brazos
        # y sus bordes no tienen hombro arriba. Se busca bajando desde arriba
        # la primera fila donde la prenda alcanza el 60% de su ancho total
        # (debajo del cuello o de la capucha) y se entra un 8% desde los bordes.
        ancho_total = max(xs) - min(xs)
        for y in range(y0, y1 + 1):
            if filas[y][centro_x]:
                izq, der = _tramo_que_contiene(filas[y], centro_x)
                if der - izq >= 0.6 * ancho_total:
                    entrada = round(0.08 * (der - izq))
                    torso_izq, torso_der = izq + entrada, der - entrada
                    hombro_izq_y = hombro_der_y = y + margen
                    break

    return {
        "hombro_izq": punto(torso_izq, hombro_izq_y),
        "hombro_der": punto(torso_der, hombro_der_y),
        "cadera": punto(torso_centro, ultima_opaca(torso_centro) - margen),
    }


def generar_vista_previa(planes_con_anclajes: list[tuple[PrendaPlan, Image.Image, dict]], destino: Path) -> None:
    celda_w, celda_h, columnas = 240, 320, 6
    filas = (len(planes_con_anclajes) + columnas - 1) // columnas
    hoja = Image.new("RGB", (celda_w * columnas, (celda_h + 20) * filas), "#EAE4DA")
    dibujo = ImageDraw.Draw(hoja)
    for i, (plan, imagen, anclajes) in enumerate(planes_con_anclajes):
        miniatura = imagen.copy()
        miniatura.thumbnail((celda_w, celda_h))
        ox = (i % columnas) * celda_w + (celda_w - miniatura.width) // 2
        oy = (i // columnas) * (celda_h + 20) + (celda_h - miniatura.height) // 2
        hoja.paste(miniatura, (ox, oy), miniatura)
        for nombre, color in (("hombro_izq", "#16A34A"), ("hombro_der", "#1D4ED8"), ("cadera", "#DC2626")):
            px = ox + anclajes[nombre]["x"] * miniatura.width
            py = oy + anclajes[nombre]["y"] * miniatura.height
            dibujo.ellipse((px - 5, py - 5, px + 5, py + 5), fill=color, outline="white")
        dibujo.text(((i % columnas) * celda_w + 6, (i // columnas) * (celda_h + 20) + celda_h), plan.codigo, fill="#1C1713")
    destino.parent.mkdir(parents=True, exist_ok=True)
    hoja.save(destino)


# ---- Ejecución real ------------------------------------------------------------


class Manifiesto:
    """Registro de todo lo creado en una corrida. Se guarda a disco después
    de cada paso, así una corrida cortada a mitad igual se puede revertir."""

    CLAVES = ["categorias", "colores", "temporadas", "productos", "variantes", "imagenes", "activos", "public_ids"]

    def __init__(self, ruta: Path, host: str):
        self.ruta = ruta
        self.datos: dict = {"creado_en": dt.datetime.now().isoformat(timespec="seconds"), "host": host}
        self.datos.update({clave: [] for clave in self.CLAVES})

    def agregar(self, clave: str, valor) -> None:
        self.datos[clave].append(valor)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.ruta.write_text(json.dumps(self.datos, indent=2, ensure_ascii=False), encoding="utf-8")


def _host_de_la_base() -> str:
    from app.core.database import engine

    return f"{engine.url.host}:{engine.url.port}/{engine.url.database}"


def _obtener_o_crear_categoria(db, manifiesto: Manifiesto, nombre: str, padre_id: int | None) -> int:
    from app.catalogo import service as catalogo_service
    from app.catalogo.models import Categoria
    from app.catalogo.schemas import CategoriaCrear

    existente = db.query(Categoria).filter(Categoria.nombre.ilike(nombre), Categoria.activo.is_(True)).first()
    if existente:
        return existente.id
    categoria = catalogo_service.crear_categoria(db, CategoriaCrear(nombre=nombre, categoria_padre_id=padre_id))
    manifiesto.agregar("categorias", categoria.id)
    return categoria.id


def _obtener_o_crear_color(db, manifiesto: Manifiesto, nombre: str, hexa: str) -> int:
    from app.catalogo import service as catalogo_service
    from app.catalogo.models import Color
    from app.catalogo.schemas import ColorCrear

    existente = db.query(Color).filter(Color.nombre.ilike(nombre)).first()
    if existente:
        return existente.id
    color = catalogo_service.crear_color(db, ColorCrear(nombre=nombre, codigo_hex=hexa))
    manifiesto.agregar("colores", color.id)
    return color.id


def _obtener_o_crear_temporada(db, manifiesto: Manifiesto, plan: PrendaPlan) -> int:
    from app.catalogo import service as catalogo_service
    from app.catalogo.models import Temporada
    from app.catalogo.schemas import TemporadaCrear

    existente = db.query(Temporada).filter(Temporada.nombre == plan.temporada, Temporada.anio == plan.anio).first()
    if existente:
        return existente.id
    temporada = catalogo_service.crear_temporada(
        db,
        TemporadaCrear(
            nombre=plan.temporada, anio=plan.anio, fecha_inicio=plan.fecha_inicio, fecha_fin=plan.fecha_fin
        ),
    )
    manifiesto.agregar("temporadas", temporada.id)
    return temporada.id


def cargar(planes: list[PrendaPlan]) -> None:
    import app.main  # noqa: F401  (registra todos los modelos y configura Cloudinary)
    from app.catalogo import service as catalogo_service
    from app.catalogo.models import Producto, ProductoImagen, ProductoVariante, Talla
    from app.catalogo.schemas import ProductoCrear
    from app.core.config import get_settings
    from app.core.database import SessionLocal
    from app.probador import service as probador_service
    from app.probador.models import ActivoProbador
    from app.probador.schemas import AnclajesActualizar

    settings = get_settings()
    if not (settings.cloudinary_cloud_name and settings.cloudinary_api_key and settings.cloudinary_api_secret):
        sys.exit("Faltan las variables CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET")

    host = _host_de_la_base()
    marca = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    manifiesto = Manifiesto(DIR_BACKUPS / f"manifiesto_prendas_{marca}.json", host)
    print(f"Base destino: {host}")
    print(f"Manifiesto:   {manifiesto.ruta}")

    db = SessionLocal()
    try:
        tallas = {t.codigo: t.id for t in db.query(Talla).filter(Talla.codigo.in_(TALLAS))}
        faltantes = set(TALLAS) - set(tallas)
        if faltantes:
            sys.exit(f"Faltan las tallas {sorted(faltantes)}: correr antes scripts.seed_catalogo")

        padre_id = _obtener_o_crear_categoria(db, manifiesto, CATEGORIA_PADRE, None)

        for plan in planes:
            print(f"\n[{plan.codigo}] {plan.nombre}")
            categoria_id = _obtener_o_crear_categoria(db, manifiesto, plan.categoria, padre_id)
            color_id = _obtener_o_crear_color(db, manifiesto, plan.color, plan.color_hex)
            temporada_id = _obtener_o_crear_temporada(db, manifiesto, plan)

            producto = db.query(Producto).filter(Producto.codigo == plan.codigo).one_or_none()
            if producto is None:
                producto = catalogo_service.crear_producto(
                    db,
                    ProductoCrear(
                        codigo=plan.codigo,
                        nombre=plan.nombre,
                        descripcion=plan.descripcion,
                        categoria_id=categoria_id,
                        temporada_id=temporada_id,
                        genero="hombre",
                        precio_base=plan.precio,
                        admite_probador=True,
                        tallas_ids=[tallas[c] for c in TALLAS],
                        colores_ids=[color_id],
                    ),
                    creado_por=None,
                )
                manifiesto.agregar("productos", producto.id)
                for variante in catalogo_service.listar_variantes_producto(db, producto.id):
                    manifiesto.agregar("variantes", variante.id)
                print(f"  producto creado id={producto.id}")
            else:
                print(f"  producto ya existía id={producto.id}")
            if not producto.admite_probador:
                sys.exit(f"  {plan.codigo} quedó con admite_probador=false: revisar la categoría")

            if db.query(ProductoImagen).filter(ProductoImagen.producto_id == producto.id).count() == 0:
                imagen, _ = catalogo_service.subir_imagen_producto(
                    db, producto.id, plan.ruta_jpg.read_bytes(), "image/jpeg", color_id, es_principal=True
                )
                manifiesto.agregar("imagenes", imagen.id)
                manifiesto.agregar("public_ids", imagen.url)
                print(f"  foto de catálogo subida ({imagen.url})")
            else:
                print("  foto de catálogo ya existía")

            variantes = {
                v.talla_id: v
                for v in db.query(ProductoVariante).filter(
                    ProductoVariante.producto_id == producto.id, ProductoVariante.color_id == color_id
                )
            }
            variante_base = variantes[tallas[TALLAS[0]]]

            def overlay_de(variante_id: int) -> ActivoProbador | None:
                return (
                    db.query(ActivoProbador)
                    .filter(
                        ActivoProbador.variante_id == variante_id,
                        ActivoProbador.tipo == "overlay_2d",
                        ActivoProbador.estado != "rechazado",
                    )
                    .one_or_none()
                )

            base = overlay_de(variante_base.id)
            if base is None:
                png, imagen_png = preparar_png(plan.ruta_png.read_bytes())
                anclajes = calcular_anclajes(imagen_png)
                base, _ = probador_service.subir_asset(db, variante_base.id, "overlay_2d", png, "image/png", None)
                manifiesto.agregar("activos", base.id)
                manifiesto.agregar("public_ids", base.url)
                probador_service.guardar_anclajes(db, base.id, AnclajesActualizar.model_validate(anclajes))
                base, _ = probador_service.validar_asset(db, base.id)
                print(f"  overlay subido y validado ({base.url}) anclajes={anclajes}")
            else:
                print(f"  overlay ya existía en talla {TALLAS[0]}")

            for codigo_talla in TALLAS[1:]:
                variante = variantes[tallas[codigo_talla]]
                if overlay_de(variante.id) is None:
                    copia = probador_service.clonar_asset_a_variante(db, base.id, variante.id)
                    manifiesto.agregar("activos", copia.id)
                    print(f"  overlay asignado a talla {codigo_talla}")
    finally:
        db.close()

    if manifiesto.ruta.exists():
        print(f"\nListo. Para deshacer: python -m scripts.seed_prendas_probador --revertir \"{manifiesto.ruta}\" --ejecutar")
    else:
        print("\nListo. No se creó nada nuevo (todo ya existía).")


def revertir(ruta_manifiesto: Path, ejecutar: bool) -> None:
    datos = json.loads(ruta_manifiesto.read_text(encoding="utf-8"))
    resumen = {clave: len(datos.get(clave, [])) for clave in Manifiesto.CLAVES}
    print(f"Manifiesto de {datos['creado_en']} contra {datos['host']}")
    print(f"Se eliminaría: {resumen}")
    if not ejecutar:
        print("(dry-run: agregar --ejecutar para eliminar)")
        return

    import app.main  # noqa: F401
    from app.catalogo.models import Categoria, Color, Producto, ProductoImagen, ProductoVariante, Temporada
    from app.core import storage
    from app.core.database import SessionLocal
    from app.probador.models import ActivoProbador

    host = _host_de_la_base()
    if host != datos["host"]:
        sys.exit(f"La base actual ({host}) no es la del manifiesto ({datos['host']}). No se toca nada.")

    # Borrado físico a propósito: deshace un seed recién creado, sin ventas
    # ni stock asociados. Si alguna fila ya tiene uso (FK), la transacción
    # entera se revierte y Cloudinary no se toca.
    db = SessionLocal()
    try:
        for modelo, clave in (
            (ActivoProbador, "activos"),
            (ProductoImagen, "imagenes"),
            (ProductoVariante, "variantes"),
            (Producto, "productos"),
            (Temporada, "temporadas"),
            (Color, "colores"),
        ):
            ids = datos.get(clave, [])
            if ids:
                db.query(modelo).filter(modelo.id.in_(ids)).delete(synchronize_session=False)
        for categoria_id in reversed(datos.get("categorias", [])):  # hijas antes que el padre
            db.query(Categoria).filter(Categoria.id == categoria_id).delete(synchronize_session=False)
        db.commit()
    except Exception as exc:
        db.rollback()
        sys.exit(f"No se pudo revertir la base (nada cambió): {exc}")
    finally:
        db.close()
    print("Filas eliminadas de la base.")

    for public_id in dict.fromkeys(datos.get("public_ids", [])):
        try:
            storage.eliminar_imagen(public_id)
            print(f"  Cloudinary: eliminado {public_id}")
        except Exception as exc:  # noqa: BLE001 -- se informa y se sigue con el resto
            print(f"  Cloudinary: no se pudo eliminar {public_id}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--origen", type=Path, help="Carpeta con catalogo.json, los JPG y overlays/")
    parser.add_argument("--solo", type=int, nargs="*", help="Ids del dataset a procesar (por defecto, todos)")
    parser.add_argument("--ejecutar", action="store_true", help="Escribir de verdad (sin esto es dry-run)")
    parser.add_argument("--revertir", type=Path, help="Manifiesto de una corrida anterior a deshacer")
    args = parser.parse_args()

    if args.revertir:
        revertir(args.revertir, args.ejecutar)
        return
    if not args.origen:
        parser.error("--origen es obligatorio")

    planes = planificar(args.origen, set(args.solo) if args.solo else None)
    if not planes:
        sys.exit("Ninguna prenda coincide con --solo")

    if args.ejecutar:
        cargar(planes)
        return

    vista: list[tuple[PrendaPlan, Image.Image, dict]] = []
    for plan in planes:
        original = plan.ruta_png.read_bytes()
        png, imagen = preparar_png(original)
        anclajes = calcular_anclajes(imagen)
        vista.append((plan, imagen, anclajes))
        comprimido = f" -> {len(png) / 1048576:.2f}MB {imagen.size}" if png is not original else ""
        print(
            f"{plan.codigo:9} {plan.categoria:9} {plan.precio:>7} Bs  {plan.color:12} "
            f"{plan.temporada} {plan.anio}  {plan.nombre}\n"
            f"          png {len(original) / 1048576:.2f}MB{comprimido}  anclajes {anclajes}"
        )
    destino = DIR_BACKUPS / "vista_previa_anclajes.png"
    generar_vista_previa(vista, destino)
    print(f"\n{len(planes)} prendas, tallas {TALLAS}. Vista previa: {destino}")
    print("(dry-run: no se escribió nada en la base ni en Cloudinary; agregar --ejecutar)")


if __name__ == "__main__":
    main()
