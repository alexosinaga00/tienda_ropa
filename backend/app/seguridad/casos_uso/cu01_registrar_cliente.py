"""CU-01 — Registrar cliente

Actor: Cliente.
Precondición: ninguna (accesible sin sesión) para el alta; sesión propia
para consultar o editar el perfil.
Postcondición: existe un usuario con rol cliente y su perfil (Cliente); el
propio cliente puede consultar y actualizar sus datos y direcciones.

Caso de uso COMPUESTO: agrupa el alta (RF de "Registrar cliente") con la
gestión del propio perfil, que en el catálogo de 43 no tiene un CU aparte.
"""

from sqlalchemy.orm import Session

from app.seguridad.models import Cliente, Usuario
from app.seguridad.politicas import obtener_perfil_cliente
from app.seguridad.repository import ClienteRepository, UsuarioRepository
from app.seguridad.schemas import ClientePerfilActualizar, RegistroRequest, UsuarioCrear

ROL_CLIENTE = "cliente"


class RegistrarCliente:
    def __init__(self) -> None:
        self._usuarios = UsuarioRepository()
        self._clientes = ClienteRepository()

    def registrar(self, db: Session, datos: RegistroRequest) -> Usuario:
        usuario = self._usuarios.crear(
            db,
            UsuarioCrear(
                nombre=datos.nombre,
                apellido=datos.apellido,
                email=datos.email,
                telefono=datos.telefono,
                password=datos.password,
            ),
        )
        self._usuarios.asignar_roles(db, usuario, [ROL_CLIENTE])

        # Si el usuario venía reactivado (estaba dado de baja con este mismo
        # email), puede ya tener un perfil de Cliente de antes -- cliente.usuario_id
        # es único, así que insertar uno nuevo rompería con IntegrityError.
        cliente = self._clientes.buscar_por_usuario(db, usuario.id)
        if cliente is not None:
            cliente.ci_nit = datos.ci_nit
        else:
            cliente = Cliente(usuario_id=usuario.id, ci_nit=datos.ci_nit)
            db.add(cliente)
        db.commit()
        db.refresh(usuario)
        return usuario

    def obtener_perfil(self, db: Session, usuario_id: int) -> Cliente:
        return obtener_perfil_cliente(db, usuario_id)

    def actualizar_perfil(
        self, db: Session, usuario_id: int, datos: ClientePerfilActualizar
    ) -> Cliente:
        return self._clientes.actualizar_perfil(db, usuario_id, datos)
