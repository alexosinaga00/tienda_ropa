import datetime as dt
import os
from dataclasses import dataclass
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "clave-de-pruebas")
os.environ.setdefault("TAREAS_TOKEN", "token-de-pruebas")
os.environ.setdefault("TAREAS_AUTOMATICAS", "false")
# bcrypt al costo mínimo: sin esto cada usuario creado en una prueba cuesta ~0,25 s y la suite tarda el doble.
# Producción usa el valor por defecto (12).
os.environ.setdefault("BCRYPT_ROUNDS", "4")
# Sin valor por defecto en el código (regla 9): los tests firman los
# webhooks con estos.
os.environ.setdefault("LIBELULA_WEBHOOK_SECRET", "secreto-libelula-de-pruebas")
os.environ.setdefault("PAYPAL_WEBHOOK_SECRET", "secreto-paypal-de-pruebas")
# Hermético: las pruebas NUNCA usan claves reales de servicios externos (Groq, Cloudinary, Vertex, PayPal),
# aunque exista un backend/.env con ellas. Una variable de entorno vacía gana sobre el .env. Sin esto, las
# pruebas llamarían de verdad a Groq (respuestas distintas en cada corrida y gasto de la clave). Los tests
# que necesitan estos servicios los simulan.
for _clave in (
    "GROQ_API_KEY", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET",
    "GOOGLE_CREDENTIALS_JSON", "VERTEX_PROJECT_ID", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET",
    "BREVO_API_KEY", "CORREO_REMITENTE_EMAIL",
):  # fmt: skip
    os.environ[_clave] = ""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.rate_limit import limiter, limitador_intentos, limitador_recuperacion
from app.main import app
from app.catalogo import models as _catalogo_models  # noqa: F401  (registra las tablas)
from app.catalogo.repository import VW_INVENTARIO_CONSOLIDADO_V2_SQL
from app.comercial import models as _comercial_models  # noqa: F401  (registra las tablas)
from app.plataforma import models as _plataforma_models  # noqa: F401  (registra las tablas)
from app.sincronizacion import models as _sincronizacion_models  # noqa: F401  (registra las tablas)
from app.core.security import crear_access_token, hash_password, permisos_de_usuario
from app.core.tenant import CLAVE_EMPRESA, empresa_de, fijar_empresa, fijar_plataforma
from app.core.tiempo import hoy_utc
from app.plataforma.models import Empresa, Plan, Rol, Suscripcion, Usuario
from app.plataforma.repository import UsuarioRepository
from app.plataforma.schemas import UsuarioCrear
from scripts.seed_entregas import seed as seed_entregas
from scripts.seed_inventario import seed as seed_inventario
from scripts.seed_pagos import seed as seed_pagos
from scripts.seed_planes import sembrar_planes
from scripts.seed_reservas import seed as seed_reservas
from scripts.seed_seguridad import seed as seed_seguridad
from scripts.seed_ventas import seed as seed_ventas


@pytest.fixture(autouse=True)
def _limpiar_limite_de_trafico():
    """Todas las pruebas comparten la IP del cliente de pruebas, así que
    comparten el balde del limiter: sin esto, las fixtures que hacen login
    agotan el límite de /auth/login y el resto de la suite recibe 429 en vez
    del token. Se resetea por prueba para que cada una arranque con el balde
    vacío, sin desactivar el limiter (queda activo y se comporta como en
    producción dentro de cada prueba)."""
    limiter.reset()
    limitador_intentos.reiniciar()
    limitador_recuperacion.reiniciar()
    yield
    limiter.reset()
    limitador_intentos.reiniciar()
    limitador_recuperacion.reiniciar()


def crear_empresa(db, codigo: str, plan: str = "profesional", nombre: str | None = None) -> Empresa:
    """Crea una empresa con su suscripción activa del `plan` dado (vence en 365
    días). Los planes ya existen (la fixture `db_session` los siembra). NO cambia
    la empresa fijada en la sesión: la suscripción se crea con la empresa nueva
    y la fijada se restaura al terminar."""
    empresa = Empresa(nombre=nombre or codigo, codigo=codigo)
    db.add(empresa)
    db.flush()
    plan_id = db.scalar(select(Plan.id).where(Plan.codigo == plan))
    assert plan_id is not None, f"El plan '{plan}' no existe"
    hoy = hoy_utc()  # la fecha de la aplicación es UTC: dt.date.today() desfasa de noche en Bolivia
    fijada = db.info.pop(CLAVE_EMPRESA, None)
    try:
        db.add(
            Suscripcion(
                empresa_id=empresa.id,
                plan_id=plan_id,
                estado="activa",
                fecha_inicio=hoy,
                fecha_vencimiento=hoy + dt.timedelta(days=365),
            )
        )
        db.flush()
    finally:
        if fijada is not None:
            db.info[CLAVE_EMPRESA] = fijada
    db.commit()
    return empresa


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Receta oficial de SQLAlchemy para SQLite (docs "Serializable isolation /
    # Savepoints / Transactional DDL"): el driver pysqlite no emite BEGIN por su
    # cuenta, así que un SAVEPOINT (begin_nested, que usan los repositorios con
    # `commit=False`) abría y CONFIRMABA la transacción al liberarse, y un
    # rollback posterior no deshacía nada. Con BEGIN explícito, SQLite se
    # comporta como Postgres: savepoints y rollback de la unidad de trabajo.
    @event.listens_for(engine, "connect")
    def _sin_begin_implicito(dbapi_conexion, _registro):
        dbapi_conexion.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_explicito(conexion):
        conexion.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(VW_INVENTARIO_CONSOLIDADO_V2_SQL))
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSessionLocal()
    # El mundo de una sola empresa (E01): los planes, la empresa 'fashionstore'
    # (id 1) con su suscripción y la empresa fijada en la sesión, ANTES de los
    # seeds, para que las pruebas existentes no cambien.
    sembrar_planes(session)
    empresa = Empresa(nombre="FashionStore", codigo="fashionstore")
    session.add(empresa)
    session.flush()
    hoy = hoy_utc()  # la fecha de la aplicación es UTC: dt.date.today() desfasa de noche en Bolivia
    session.add(
        Suscripcion(
            empresa_id=empresa.id,
            plan_id=session.scalar(select(Plan.id).where(Plan.codigo == "profesional")),
            estado="activa",
            fecha_inicio=hoy,
            fecha_vencimiento=hoy + dt.timedelta(days=365),
        )
    )
    session.commit()
    fijar_empresa(session, empresa.id)
    seed_seguridad(session)
    seed_inventario(session)
    seed_reservas(session)
    seed_ventas(session)
    seed_pagos(session)
    seed_entregas(session)
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        # rollback (no close) al final de cada request: simula el
        # `finally: db.close()` de get_db real -- si un endpoint lanza a
        # mitad de una transacción con varios flush() antes del commit
        # final (p. ej. RegistrarRecepcionMercaderia.registrar), lo que quedó sin
        # commitear no debe filtrarse al siguiente request de este mismo
        # test. rollback() y no close() para no dejar detached los objetos
        # que ya tienen otros fixtures (p. ej. admin_headers).
        try:
            yield db_session
        finally:
            db_session.rollback()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def crear_superadmin_de_prueba(db, email: str = "super@plataforma.example.com", password: str = "claveSegura123") -> int:
    """Un superadministrador (usuario sin empresa y con el rol global
    superadministrador), creado como lo haria el script: en modo plataforma.
    Deja la sesion como estaba y devuelve el id del usuario."""
    original = empresa_de(db)
    fijar_plataforma(db)
    try:
        usuario = Usuario(nombre="Super", apellido="Admin", email=email, password_hash=hash_password(password))
        db.add(usuario)
        db.flush()
        usuario.roles = [db.scalar(select(Rol).where(Rol.nombre == "superadministrador"))]
        usuario_id = usuario.id
        db.commit()
    finally:
        fijar_empresa(db, original)
    return usuario_id


def token_de(db, usuario) -> dict:
    """Cabeceras con el access token de `usuario` (firmado como lo hace el
    login, con la empresa de su fila)."""
    roles = [r.nombre for r in usuario.roles]
    token = crear_access_token(
        usuario.id, roles, permisos_de_usuario(db, usuario.id), empresa_id=usuario.empresa_id
    )
    return {"Authorization": f"Bearer {token}"}


@dataclass
class EmpresaDePrueba:
    id: int
    codigo: str
    admin_id: int
    headers: dict


@pytest.fixture()
def dos_empresas(db_session):
    """Dos empresas independientes, cada una con su administrador: A
    ('tienda-a', plan profesional) y B ('tienda-b', plan básico). Vacías de
    datos de negocio: cada prueba crea lo que necesite. Para usarlas por HTTP,
    junto con `client_por_peticion`. Deja la sesión como estaba."""
    original = empresa_de(db_session)
    repo = UsuarioRepository()
    creadas = {}
    for clave, codigo, plan in (("a", "tienda-a", "profesional"), ("b", "tienda-b", "basico")):
        empresa = crear_empresa(db_session, codigo, plan=plan)
        fijar_empresa(db_session, empresa.id)
        admin = repo.crear(
            db_session,
            UsuarioCrear(
                nombre="Admin", apellido=clave.upper(), email=f"admin@{codigo}.example.com", password="claveSegura123"
            ),
        )
        repo.asignar_roles(db_session, admin, ["administrador"])
        creadas[clave] = EmpresaDePrueba(
            id=empresa.id, codigo=codigo, admin_id=admin.id, headers=token_de(db_session, admin)
        )
    fijar_empresa(db_session, original)
    return SimpleNamespace(**creadas)


@pytest.fixture()
def client_por_peticion(db_session):
    """Como `client`, pero cada petición recibe una sesión NUEVA y sin empresa,
    igual que en producción: la empresa la fija la propia petición (el usuario
    del token o el código de /public/{codigo}). `client` (sesión compartida y
    con la empresa de las semillas) se conserva para las pruebas anteriores.

    Lo que la prueba haya dejado sin confirmar en `db_session` se confirma
    antes de cada petición (comparten conexión), y `db_session` se refresca
    después para ver lo que la petición escribió."""
    fabrica = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)

    def _override_get_db():
        db_session.commit()
        sesion = fabrica()
        try:
            yield sesion
        finally:
            sesion.close()
            db_session.expire_all()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# Empresa de las semillas de las pruebas (la que fija `db_session`).
EMPRESA_DEFECTO = "fashionstore"


def _login(client, email, password, empresa=EMPRESA_DEFECTO):
    respuesta = client.post("/api/v1/auth/login", json={"empresa": empresa, "email": email, "password": password})
    return respuesta.json()["access_token"]


@pytest.fixture()
def admin_headers(client, db_session):
    usuario_repo = UsuarioRepository()
    usuario = usuario_repo.crear(
        db_session,
        UsuarioCrear(nombre="Admin", apellido="Root", email="admin@example.com", password="claveSegura123"),
    )
    usuario_repo.asignar_roles(db_session, usuario, ["administrador"])

    token = _login(client, "admin@example.com", "claveSegura123")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def cliente_headers(client):
    # Vía el registro de la tienda (no usuario_repo.crear a mano): así el usuario
    # también tiene su fila en `cliente`, igual que en producción. Varios
    # endpoints (favoritos, perfil) la necesitan.
    client.post(
        f"/api/v1/public/{EMPRESA_DEFECTO}/registro",
        json={
            "nombre": "Cli",
            "apellido": "Ente",
            "email": "cliente@example.com",
            "password": "claveSegura123",
        },
    )
    token = _login(client, "cliente@example.com", "claveSegura123")
    return {"Authorization": f"Bearer {token}"}


def crear_staff(
    client, admin_headers, db_session, *, rol: str, cargo: str, sucursal_id: int, email: str
):
    """No es un fixture (necesita `sucursal_id`, que cada test arma
    distinto): un helper que los tests llaman directo. Devuelve los headers
    del empleado ya logueado, con su rol y su fila en `empleado`."""
    usuario_repo = UsuarioRepository()
    usuario = usuario_repo.crear(
        db_session,
        UsuarioCrear(nombre="Staff", apellido="Prueba", email=email, password="claveSegura123"),
    )
    usuario_repo.asignar_roles(db_session, usuario, [rol])

    client.post(
        "/api/v1/empleados",
        json={"usuario_id": usuario.id, "sucursal_id": sucursal_id, "cargo": cargo},
        headers=admin_headers,
    )

    token = _login(client, email, "claveSegura123")
    return {"Authorization": f"Bearer {token}"}


def crear_cajero(client, admin_headers, db_session, *, sucursal_id: int, email: str = "cajero@example.com"):
    return crear_staff(
        client, admin_headers, db_session, rol="cajero", cargo="Cajero", sucursal_id=sucursal_id, email=email
    )


class EspiaBloqueos:
    """Registra cómo se piden los bloqueos de stock (T3). SQLite no aplica
    FOR UPDATE, así que lo único verificable es el ORDEN en que se piden:
    cada evento es ("lote", [claves]) (pasada previa ordenada) o
    ("linea", clave) (bloqueo línea por línea)."""

    def __init__(self) -> None:
        self.eventos: list[tuple[str, object]] = []

    def lotes(self) -> list[list[tuple[int, int]]]:
        return [dato for tipo, dato in self.eventos if tipo == "lote"]

    def orden_de_adquisicion(self) -> list[tuple[int, int]]:
        """Claves (variante_id, sucursal_id) en el orden en que se tocaron por
        primera vez: lo que decide si hay deadlock entre dos lotes."""
        vistas: list[tuple[int, int]] = []
        for tipo, dato in self.eventos:
            for clave in dato if tipo == "lote" else [dato]:
                if clave not in vistas:
                    vistas.append(clave)
        return vistas


@pytest.fixture()
def espia_bloqueos(monkeypatch):
    from app.catalogo.repository import StockRepository

    espia = EspiaBloqueos()
    original_lote = StockRepository.bloquear_existentes
    original_linea = StockRepository.obtener_o_crear_bloqueado

    def lote(self, db, claves):
        espia.eventos.append(("lote", list(claves)))
        return original_lote(self, db, claves)

    def linea(self, db, variante_id, sucursal_id):
        espia.eventos.append(("linea", (variante_id, sucursal_id)))
        return original_linea(self, db, variante_id, sucursal_id)

    monkeypatch.setattr(StockRepository, "bloquear_existentes", lote)
    monkeypatch.setattr(StockRepository, "obtener_o_crear_bloqueado", linea)
    return espia
