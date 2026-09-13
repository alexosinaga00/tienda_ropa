from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crud_base import CRUDBase
from app.core.exceptions import ConflictoError, DomainError, NoEncontradoError
from app.core.security import hash_password
from app.seguridad.models import Cliente, Permiso, Rol, Usuario
from app.seguridad.schemas import (
    ClientePerfilActualizar,
    RolActualizar,
    RolCrear,
    UsuarioActualizar,
    UsuarioCrear,
)


class RolRepository(CRUDBase[Rol, RolCrear, RolActualizar]):
    def __init__(self) -> None:
        super().__init__(Rol)

    def obtener_por_nombre(self, db: Session, nombre: str) -> Rol | None:
        return db.scalar(select(Rol).where(Rol.nombre == nombre))

    def asignar_permisos(self, db: Session, rol: Rol, codigos: list[str]) -> Rol:
        codigos_unicos = set(codigos)
        permisos = list(db.scalars(select(Permiso).where(Permiso.codigo.in_(codigos_unicos))))
        if len(permisos) != len(codigos_unicos):
            raise DomainError("Uno o más códigos de permiso no existen")
        rol.permisos = permisos
        db.commit()
        db.refresh(rol)
        return rol


class UsuarioRepository(CRUDBase[Usuario, UsuarioCrear, UsuarioActualizar]):
    def __init__(self) -> None:
        super().__init__(Usuario)

    def obtener_por_email(self, db: Session, email: str) -> Usuario | None:
        return db.scalar(select(Usuario).where(Usuario.email == email))

    def crear(self, db: Session, datos: UsuarioCrear) -> Usuario:
        existente = self.obtener_por_email(db, datos.email)
        if existente is not None:
            if existente.activo:
                raise ConflictoError("Ya existe un usuario con ese email")
            existente.nombre = datos.nombre
            existente.apellido = datos.apellido
            existente.telefono = datos.telefono
            existente.password_hash = hash_password(datos.password)
            existente.activo = True
            db.commit()
            db.refresh(existente)
            return existente
        usuario = Usuario(
            nombre=datos.nombre,
            apellido=datos.apellido,
            email=datos.email,
            telefono=datos.telefono,
            password_hash=hash_password(datos.password),
        )
        db.add(usuario)
        db.commit()
        db.refresh(usuario)
        return usuario

    def actualizar_password(self, db: Session, usuario: Usuario, password: str) -> None:
        usuario.password_hash = hash_password(password)
        db.commit()

    def asignar_roles(self, db: Session, usuario: Usuario, nombres_rol: list[str]) -> Usuario:
        nombres_unicos = set(nombres_rol)
        roles = list(
            db.scalars(select(Rol).where(Rol.nombre.in_(nombres_unicos), Rol.activo.is_(True)))
        )
        if len(roles) != len(nombres_unicos):
            raise DomainError("Uno o más roles no existen o están inactivos")
        usuario.roles = roles
        db.commit()
        db.refresh(usuario)
        return usuario


class ClienteRepository:
    def obtener(self, db: Session, cliente_id: int) -> Cliente:
        cliente = db.get(Cliente, cliente_id)
        if cliente is None:
            raise NoEncontradoError("Cliente no encontrado")
        return cliente

    def obtener_por_usuario(self, db: Session, usuario_id: int) -> Cliente:
        cliente = db.scalar(select(Cliente).where(Cliente.usuario_id == usuario_id))
        if cliente is None:
            raise NoEncontradoError("Perfil de cliente no encontrado")
        return cliente

    def buscar_por_usuario(self, db: Session, usuario_id: int) -> Cliente | None:
        """Variante de obtener_por_usuario que no lanza si no existe, para
        que el caller decida si crea el perfil o lo reusa (ver
        seguridad.service.registrar_cliente)."""
        return db.scalar(select(Cliente).where(Cliente.usuario_id == usuario_id))

    def actualizar_perfil(
        self, db: Session, usuario_id: int, datos: ClientePerfilActualizar
    ) -> Cliente:
        cliente = self.obtener_por_usuario(db, usuario_id)
        for campo, valor in datos.model_dump(exclude_unset=True).items():
            setattr(cliente, campo, valor)
        db.commit()
        db.refresh(cliente)
        return cliente
