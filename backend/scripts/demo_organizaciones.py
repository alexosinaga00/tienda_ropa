"""Datos de las organizaciones de demostración (solo datos, sin base de datos).

`scripts.poblar_demo` recorre `ORGANIZACIONES`: agregar una organización es una
entrada más. Reglas que respeta cada una:

- Las sucursales activas (el depósito cuenta) caben en el límite de su plan:
  Básico 2, Estándar 5, Profesional 10.
- El código de cada sucursal tiene 13 caracteres o menos (el de la recepción de
  stock, `RD-<código>-<n>`, admite 20).
- Los nombres no llevan tildes ni eñe: se escriben en el login y `empresa.codigo`
  sale del nombre.
- Las fotos son los ids del dataset de `catalogo.json` (24 prendas).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from scripts.seed_operativo import StaffSeed, SucursalSeed

# ---- Plan nuevo -----------------------------------------------------------------------

# El plan Estándar es un dato (lo crea el CU-04 como lo haría el superadministrador),
# no una migración: una prueba espera exactamente 2 planes sembrados (Básico y Profesional).
PLAN_ESTANDAR: dict = {
    "codigo": "estandar",
    "nombre": "Estándar",
    "max_sucursales": 5,
    "reportes_convencionales": True,
    "reportes_ia": True,
    "operacion_offline": True,
    "analitica_ml": False,
    "copias_seguridad": True,
    "gestion_productos": True,
    "gestion_ventas": True,
    "reservas": True,
    "max_copias_historial": 6,
    "plazo_cambio_horas_defecto": 48,
    "precio_mensual_bs": Decimal("290.00"),
}

# Lo que sube con el plan (decisión del usuario, 29/10/2026): copias que guarda 3 (Básico) < 6
# (Estándar) < 10 (Profesional) y plazo de cambio 24 h < 48 h < 72 h. Esto cambia D07 en los datos de
# demostración: el Básico pasa a INCLUIR copias de seguridad (la migración lo deja sin ellas, el
# Profesional con 5 copias y 24 h; esos literales y `seed_planes.py` no se tocan porque una prueba
# los compara). Se aplican SOLO con `poblar_demo --ajustar-planes`, para que repetir el script no
# pise lo que el superadministrador cambie a mano.
AJUSTES_PLANES: dict[str, dict] = {
    "basico": {"copias_seguridad": True, "max_copias_historial": 3},
    "estandar": {"max_copias_historial": 6, "plazo_cambio_horas_defecto": 48},
    "profesional": {"max_copias_historial": 10, "plazo_cambio_horas_defecto": 72},
}

LIMITE_SUCURSALES = {"basico": 2, "estandar": 5, "profesional": 10}

# La temporada de todas las prendas (la del dataset es de 2010 a 2012). Hemisferio sur.
TEMPORADA_DEMO: tuple[str, int, dt.date, dt.date] = ("Primavera", 2026, dt.date(2026, 9, 1), dt.date(2026, 11, 30))

TALLAS_DEMO = ["S", "M", "L", "XL"]  # la primera lleva el overlay del probador y las demás lo reutilizan

CLIENTES_POR_ORGANIZACION = 5

# ---- Estructuras ----------------------------------------------------------------------

Ciudad = tuple[str, str]  # (nombre, departamento) como en `CIUDADES_BASE`
SANTA_CRUZ: Ciudad = ("Santa Cruz de la Sierra", "Santa Cruz")
LA_PAZ: Ciudad = ("La Paz", "La Paz")
COCHABAMBA: Ciudad = ("Cochabamba", "Cochabamba")
ORURO: Ciudad = ("Oruro", "Oruro")
POTOSI: Ciudad = ("Potosí", "Potosí")
SUCRE: Ciudad = ("Sucre", "Chuquisaca")
TARIJA: Ciudad = ("Tarija", "Tarija")


@dataclass(frozen=True)
class SucursalDemo:
    codigo: str
    nombre: str
    direccion: str
    telefono: str
    latitud: str
    longitud: str
    ciudad: Ciudad
    factor: float  # tamaño relativo: multiplica las unidades de stock (la mayor vende ~2x la menor)
    es_deposito: bool = False

    @property
    def stock_minimo(self) -> int:
        return 5 if self.es_deposito else 3

    @property
    def stock_maximo(self) -> int:
        return 60 if self.es_deposito else 30

    def como_seed(self) -> SucursalSeed:
        """La forma que usa `seed_operativo.seed_sucursales` (las cantidades de stock
        no se usan: este seed calcula el stock por variante)."""
        return SucursalSeed(
            self.codigo, self.nombre, self.direccion, self.telefono,
            Decimal(self.latitud), Decimal(self.longitud), self.es_deposito,
            {}, self.stock_minimo, self.stock_maximo,
        )  # fmt: skip


@dataclass(frozen=True)
class OrganizacionDemo:
    nombre: str
    codigo: str  # lo que sale de normalizar el nombre (una prueba lo comprueba)
    plan: str
    dominio: str
    color_acento: str | None
    tema: str
    sucursales: tuple[SucursalDemo, ...]
    prendas: tuple[int, ...]  # ids del dataset de este catálogo
    factor_precio: Decimal
    costo_pct: Decimal  # costo = precio x costo_pct (los seeds actuales usan 0,45)
    proveedor: tuple[str, str]  # (nombre, NIT)
    indice: int  # 0..n: reparte nombres de personal, teléfonos y CI sin repetirlos
    # "registro": la crea GestionarEmpresas.registrar; "migracion": ya existe (empresa
    # semilla de E01); "boutique": la crea scripts.seed_empresas_prueba.sembrar_boutique.
    origen: str = "registro"

    @property
    def admin_email(self) -> str:
        return f"admin@{self.dominio}"

    @property
    def tiendas(self) -> tuple[SucursalDemo, ...]:
        return tuple(s for s in self.sucursales if not s.es_deposito)

    def email_cliente(self, numero: int) -> str:
        return f"cliente{numero:02d}@demo.{self.dominio}"

    def personal(self) -> list[StaffSeed]:
        """El administrador y, por cada tienda (los depósitos no llevan personal), un
        encargado y un cajero. Nombres repartidos de forma estable por `indice`. El correo
        lleva lo que sigue al guion del código de la sucursal (`encargado.plaza@...`), por eso
        dos tiendas de una misma organización no pueden terminar igual."""
        if self.origen == "boutique":
            from scripts.seed_empresas_prueba import STAFF_BOUTIQUE

            return list(STAFF_BOUTIQUE)
        base = 70_000_000 + self.indice * 1000
        personal = [
            StaffSeed(self.admin_email, "Administrador", "General", str(base + 1), "administrador", "",
                      "Administrador", str(9_100_000 + self.indice * 100 + 1)),
        ]  # fmt: skip
        n = 2
        for tienda in self.tiendas:
            local = tienda.codigo.split("-", 1)[1].lower()
            for rol, prefijo, cargo in (
                ("encargado_sucursal", "encargado", "Encargado de sucursal"),
                ("cajero", "cajero", "Cajero"),
            ):
                nombre = _NOMBRES[(self.indice * 5 + n) % len(_NOMBRES)]
                apellido = _APELLIDOS[(self.indice * 7 + n * 3) % len(_APELLIDOS)]
                personal.append(
                    StaffSeed(f"{prefijo}.{local}@{self.dominio}", nombre, apellido, str(base + n), rol,
                              tienda.codigo, cargo, str(9_100_000 + self.indice * 100 + n))
                )  # fmt: skip
                n += 1
        return personal


_NOMBRES = (
    "Carla", "Diego", "Mariana", "Luis", "Andrea", "Marco", "Lucia", "Pablo", "Daniela", "Ricardo",
    "Valeria", "Jorge", "Camila", "Sergio", "Paola", "Rodrigo", "Fernanda", "Javier", "Gabriela",
    "Mauricio", "Natalia", "Alvaro", "Silvia", "Hugo",
)
_APELLIDOS = (
    "Rojas", "Suarez", "Justiniano", "Vaca", "Mamani", "Quispe", "Flores", "Choque", "Rivero",
    "Salvatierra", "Condori", "Villarroel", "Gutierrez", "Ribera", "Arce", "Mendoza", "Camacho",
    "Antelo", "Terrazas", "Pinto",
)

# ---- Selección de prendas (ids del dataset) -----------------------------------------------
# Hombre: 10005 10006 10008 10009 10010 10022(polo) 10032 14006(jersey) 15348(polo) 2620 28639
#         3730(jersey, camiseta de equipo con patrocinador) 38606 38608 38639(polo) 5433
# Mujer:  10003 10007 10019 10026 10027 10028 10030     Chamarra (unisex): 10017
TODAS = (
    10003, 10005, 10006, 10007, 10008, 10009, 10010, 10017, 10019, 10022, 10026, 10027,
    10028, 10030, 10032, 14006, 15348, 2620, 28639, 3730, 38606, 38608, 38639, 5433,
)  # fmt: skip
PRENDAS_DEPORTIVAS = (
    10005, 10006, 10008, 10009, 10010, 10017, 10022, 10032, 14006, 2620, 28639,
    10003, 10007, 10019, 10026, 10030,
)  # fmt: skip
PRENDAS_BLANCO_Y_NEGRO = (
    10003, 10007, 10019, 10027, 10028, 28639, 38606, 10006, 10010, 10026, 10030, 10032, 14006, 15348,
)  # fmt: skip
PRENDAS_CASUALES = (15348, 38606, 38608, 38639, 5433, 28639, 10003, 10007, 10019, 10026, 10027, 10030)
PRENDAS_VARIADAS = (10005, 10009, 10017, 10022, 10028, 2620, 38639, 5433, 10008, 38608, 10026, 10027)
PRENDAS_COLORES_VIVOS = (10005, 10022, 2620, 38639, 10017, 10009, 5433, 3730, 10008, 38608)
PRENDAS_BOUTIQUE = (28639, 38606, 38608, 10007, 10019, 10027, 15348, 10030)
PRENDAS_BASICAS = (38606, 38608, 5433, 28639, 10026, 10027, 10006, 38639)

# ---- Las 8 organizaciones ---------------------------------------------------------------------

ORGANIZACIONES: tuple[OrganizacionDemo, ...] = (
    OrganizacionDemo(
        nombre="FashionStore", codigo="fashionstore", plan="profesional", dominio="fashionstore.bo",
        color_acento=None, tema="Catálogo completo", prendas=TODAS,
        factor_precio=Decimal("1.00"), costo_pct=Decimal("0.45"),
        proveedor=("Textiles Andina SRL", "1020304011"), indice=0, origen="migracion",
        sucursales=(
            SucursalDemo("SC-CENTRO", "FashionStore Centro", "Calle 24 de Septiembre 145, Casco Viejo",
                         "33345678", "-17.7833000", "-63.1821000", SANTA_CRUZ, 1.0),
            SucursalDemo("SC-EQUIPETROL", "FashionStore Equipetrol", "Av. San Martin 820, Equipetrol",
                         "33398765", "-17.7625000", "-63.1960000", SANTA_CRUZ, 0.7),
            SucursalDemo("SC-DEPOSITO", "Deposito Central", "Parque Industrial, Mz. 12",
                         "33321000", "-17.7300000", "-63.1500000", SANTA_CRUZ, 2.2, es_deposito=True),
        ),  # fmt: skip
    ),
    OrganizacionDemo(
        nombre="Chaski Sport", codigo="chaski-sport", plan="profesional", dominio="chaskisport.bo",
        color_acento="#D9531E", tema="Deportivo", prendas=PRENDAS_DEPORTIVAS,
        factor_precio=Decimal("1.10"), costo_pct=Decimal("0.42"),
        proveedor=("Deportes Andinos SA", "3010500011"), indice=1,
        sucursales=(
            SucursalDemo("SC-PLAZA", "Chaski Plaza", "Calle Libertad 210, Plaza 24 de Septiembre",
                         "33411100", "-17.7834000", "-63.1822000", SANTA_CRUZ, 1.0),
            SucursalDemo("CB-NORTE", "Chaski Cochabamba Norte", "Av. America 1180, Cala Cala",
                         "44411200", "-17.3620000", "-66.1560000", COCHABAMBA, 0.75),
            SucursalDemo("SC-DEPOSITO", "Deposito Chaski", "Parque Industrial, Mz. 8",
                         "33411300", "-17.7290000", "-63.1480000", SANTA_CRUZ, 2.2, es_deposito=True),
        ),  # fmt: skip
    ),
    OrganizacionDemo(
        nombre="Illimani Urban", codigo="illimani-urban", plan="profesional", dominio="illimaniurban.bo",
        color_acento="#2E6F95", tema="Urbano, blanco y negro", prendas=PRENDAS_BLANCO_Y_NEGRO,
        factor_precio=Decimal("1.15"), costo_pct=Decimal("0.48"),
        proveedor=("Distribuidora Altiplano SRL", "3020500021"), indice=2,
        sucursales=(
            SucursalDemo("LP-SOPOCACHI", "Illimani Sopocachi", "Av. 6 de Agosto 2170, Sopocachi",
                         "22411300", "-16.5112000", "-68.1290000", LA_PAZ, 1.0),
            SucursalDemo("LP-ZSUR", "Illimani Zona Sur", "Calle 21 de Calacoto 8050, Zona Sur",
                         "22411400", "-16.5390000", "-68.0830000", LA_PAZ, 0.85),
            SucursalDemo("OR-CENTRO", "Illimani Oruro", "Calle Adolfo Mier 640, Centro",
                         "25211500", "-17.9697000", "-67.1150000", ORURO, 0.55),
        ),  # fmt: skip
    ),
    OrganizacionDemo(
        nombre="Canaveral Moda", codigo="canaveral-moda", plan="estandar", dominio="canaveralmoda.bo",
        color_acento="#A83A5A", tema="Casual de mujer y hombre", prendas=PRENDAS_CASUALES,
        factor_precio=Decimal("0.95"), costo_pct=Decimal("0.44"),
        proveedor=("Tejidos Crucenos SRL", "3030500031"), indice=3,
        sucursales=(
            SucursalDemo("SC-CENTRO", "Canaveral Centro", "Calle Ayacucho 330, Centro",
                         "33511100", "-17.7840000", "-63.1810000", SANTA_CRUZ, 1.0),
            SucursalDemo("SC-URBARI", "Canaveral Urbari", "Av. Beni 2do anillo, Urbari",
                         "33511200", "-17.7690000", "-63.1850000", SANTA_CRUZ, 0.8),
            SucursalDemo("SC-DEPOSITO", "Deposito Canaveral", "Av. Cristo Redentor km 4",
                         "33511300", "-17.7200000", "-63.1700000", SANTA_CRUZ, 2.0, es_deposito=True),
        ),  # fmt: skip
    ),
    OrganizacionDemo(
        nombre="Valle Alegre", codigo="valle-alegre", plan="estandar", dominio="vallealegre.bo",
        color_acento="#3C7A4B", tema="Variado", prendas=PRENDAS_VARIADAS,
        factor_precio=Decimal("0.90"), costo_pct=Decimal("0.46"),
        proveedor=("Manufacturas Valle SRL", "3040500041"), indice=4,
        sucursales=(
            SucursalDemo("CB-CENTRO", "Valle Alegre Centro", "Calle Bolivar 540, Centro",
                         "44511100", "-17.3935000", "-66.1570000", COCHABAMBA, 1.0),
            SucursalDemo("CB-CALACALA", "Valle Alegre Cala Cala", "Av. Ballivian 1890, Cala Cala",
                         "44511200", "-17.3720000", "-66.1480000", COCHABAMBA, 0.7),
            SucursalDemo("TJ-TARIJA", "Valle Alegre Tarija", "Calle Bolivar 305, Centro",
                         "46611300", "-21.5355000", "-64.7296000", TARIJA, 0.6),
        ),  # fmt: skip
    ),
    OrganizacionDemo(
        nombre="Tinku Wear", codigo="tinku-wear", plan="estandar", dominio="tinkuwear.bo",
        color_acento="#7A3E9D", tema="Colores vivos", prendas=PRENDAS_COLORES_VIVOS,
        factor_precio=Decimal("0.85"), costo_pct=Decimal("0.50"),
        proveedor=("Textil Chaco Ltda", "3050500051"), indice=5,
        sucursales=(
            SucursalDemo("SU-CENTRO", "Tinku Sucre", "Calle Estudiantes 95, Centro",
                         "46411100", "-19.0477000", "-65.2596000", SUCRE, 1.0),
            SucursalDemo("PO-POTOSI", "Tinku Potosi", "Calle Bolivar 770, Centro",
                         "26211200", "-19.5836000", "-65.7531000", POTOSI, 0.6),
            SucursalDemo("SU-DEPOSITO", "Deposito Tinku", "Av. del Maestro km 2",
                         "46411300", "-19.0300000", "-65.2700000", SUCRE, 2.0, es_deposito=True),
        ),  # fmt: skip
    ),
    OrganizacionDemo(
        nombre="Boutique Andina", codigo="boutique-andina", plan="basico", dominio="boutiqueandina.bo",
        color_acento="#8A5A44", tema="Boutique andina (suma 8 poleras con foto)", prendas=PRENDAS_BOUTIQUE,
        factor_precio=Decimal("0.90"), costo_pct=Decimal("0.45"),
        proveedor=("Tejidos del Altiplano SRL", "2030405011"), indice=6, origen="boutique",
        sucursales=(
            SucursalDemo("LP-CENTRO", "Boutique Andina Centro", "Av. 16 de Julio 1550, El Prado",
                         "22123456", "-16.4955000", "-68.1336000", LA_PAZ, 1.0),
            SucursalDemo("LP-DEPOSITO", "Deposito Andino", "Zona Villa Adela, Calle 3",
                         "22654321", "-16.5000000", "-68.1500000", LA_PAZ, 2.0, es_deposito=True),
        ),  # fmt: skip
    ),
    OrganizacionDemo(
        nombre="Pampa Casual", codigo="pampa-casual", plan="basico", dominio="pampacasual.bo",
        color_acento="#0F766E", tema="Básico y casual", prendas=PRENDAS_BASICAS,
        factor_precio=Decimal("0.80"), costo_pct=Decimal("0.40"),
        proveedor=("Distribuidora Sur Ltda", "3070500071"), indice=7,
        sucursales=(
            SucursalDemo("TJ-CENTRO", "Pampa Centro", "Calle Sucre 450, Centro",
                         "46611400", "-21.5350000", "-64.7290000", TARIJA, 1.0),
            SucursalDemo("TJ-MERCADO", "Pampa Mercado Central", "Calle Bolivar 120, Mercado Central",
                         "46611500", "-21.5370000", "-64.7330000", TARIJA, 0.7),
        ),  # fmt: skip
    ),
)


def por_codigo(codigo: str) -> OrganizacionDemo:
    for organizacion in ORGANIZACIONES:
        if organizacion.codigo == codigo:
            return organizacion
    raise KeyError(codigo)
