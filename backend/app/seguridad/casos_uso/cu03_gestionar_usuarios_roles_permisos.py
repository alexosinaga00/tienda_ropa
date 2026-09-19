"""CU-03 — Gestionar usuarios, roles y permisos

Actor: Administrador.
Precondición: sesión de administrador con los permisos usuarios.gestionar
y roles.gestionar.
Postcondición: el usuario y sus roles quedan registrados; los cambios de
roles y permisos se aplican de inmediato.

Caso de uso COMPUESTO: el catálogo lo modela como un solo CU, así que las
dos entidades (Usuario y Rol/Permiso) viven en este archivo, cada una con
su propia clase CRUD pequeña.
"""

from sqlalchemy.orm import Session

from app.core.deps import ParametrosPaginacion
from app.seguridad.models import Rol, Usuario
from app.seguridad.repository import RolRepository, UsuarioRepository
from app.seguridad.schemas import RolActualizar, RolCrear, UsuarioActualizar, UsuarioCrear


class GestionarUsuarios:
    def __init__(self) -> None:
        self._repo = UsuarioRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Usuario]:
        return list(self._repo.listar(db, paginacion))

    def crear(self, db: Session, datos: UsuarioCrear) -> Usuario:
        return self._repo.crear(db, datos)

    def actualizar(self, db: Session, usuario_id: int, datos: UsuarioActualizar) -> Usuario:
        return self._repo.actualizar(db, usuario_id, datos)

    def desactivar(self, db: Session, usuario_id: int) -> Usuario:
        return self._repo.desactivar(db, usuario_id)

    def asignar_roles(self, db: Session, usuario_id: int, nombres_rol: list[str]) -> Usuario:
        usuario = self._repo.obtener(db, usuario_id)
        return self._repo.asignar_roles(db, usuario, nombres_rol)


class GestionarRolesPermisos:
    def __init__(self) -> None:
        self._repo = RolRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Rol]:
        return list(self._repo.listar(db, paginacion))

    def obtener(self, db: Session, rol_id: int) -> Rol:
        return self._repo.obtener(db, rol_id)

    def crear(self, db: Session, datos: RolCrear) -> Rol:
        return self._repo.crear(db, datos)

    def actualizar(self, db: Session, rol_id: int, datos: RolActualizar) -> Rol:
        return self._repo.actualizar(db, rol_id, datos)

    def desactivar(self, db: Session, rol_id: int) -> Rol:
        return self._repo.desactivar(db, rol_id)

    def asignar_permisos(self, db: Session, rol_id: int, codigos_permiso: list[str]) -> Rol:
        rol = self._repo.obtener(db, rol_id)
        return self._repo.asignar_permisos(db, rol, codigos_permiso)
