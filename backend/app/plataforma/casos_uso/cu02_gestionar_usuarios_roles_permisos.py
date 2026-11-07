"""CU-02 — Gestionar usuarios, roles y permisos

Absorbe el antiguo CU-03 (Gestionar usuarios, roles y permisos).

Actor: Administrador.
Precondición: sesión de administrador con los permisos usuarios.gestionar
y roles.gestionar.
Postcondición: el usuario y sus roles quedan registrados; los cambios de
roles y permisos se aplican de inmediato. Cada cambio deja su fila en la
bitácora de auditoría, en el mismo commit (si se llama con un contexto de
auditoría; sin él no se registra nada).

Caso de uso COMPUESTO: las dos entidades (Usuario y Rol/Permiso) viven en
este archivo, cada una con su propia clase CRUD pequeña."""

from sqlalchemy.orm import Session

from app.core.auditoria import (
    ACCION_ACTUALIZAR,
    ACCION_ASIGNAR_PERMISOS,
    ACCION_ASIGNAR_ROLES,
    ACCION_CREAR,
    ACCION_DESACTIVAR,
    ENTIDAD_ROL,
    ENTIDAD_USUARIO,
    ContextoAuditoria,
    diff_campos,
)
from app.core.deps import ParametrosPaginacion
from app.plataforma import politicas
from app.plataforma.models import Permiso, Rol, Usuario
from app.plataforma.repository import RolRepository, UsuarioRepository
from app.plataforma.schemas import RolActualizar, RolCrear, UsuarioActualizar, UsuarioCrear


class GestionarUsuarios:
    def __init__(self) -> None:
        self._repo = UsuarioRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion, buscar: str | None = None) -> list[Usuario]:
        """Los usuarios activos de la empresa, paginados. `buscar` filtra en el servidor (nombre, apellido y correo)
        sobre TODOS los usuarios, no solo sobre la página que se está viendo."""
        return list(self._repo.listar(db, paginacion, buscar=buscar))

    def crear(self, db: Session, datos: UsuarioCrear, contexto: ContextoAuditoria | None = None) -> Usuario:
        # Un usuario dado de baja con el mismo correo se reactiva en vez de duplicarse.
        reactivado = self._repo.obtener_por_email(db, datos.email) is not None
        usuario = self._repo.crear(db, datos, commit=False)
        politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_USUARIO, usuario.id, ACCION_CREAR, {"reactivado": reactivado}
        )
        db.commit()
        db.refresh(usuario)
        return usuario

    def actualizar(
        self, db: Session, usuario_id: int, datos: UsuarioActualizar, contexto: ContextoAuditoria | None = None
    ) -> Usuario:
        # Solo los NOMBRES de los campos cambiados (nunca el teléfono ni el
        # nombre); de `activo` sí se ve el valor.
        actual = self._repo.buscar(db, usuario_id)
        cambios = diff_campos(actual, datos.model_dump(exclude_unset=True), ("activo",)) if actual else {}
        usuario = self._repo.actualizar(db, usuario_id, datos, commit=False)
        politicas.registrar_bitacora_de(db, contexto, ENTIDAD_USUARIO, usuario.id, ACCION_ACTUALIZAR, cambios)
        db.commit()
        db.refresh(usuario)
        return usuario

    def desactivar(self, db: Session, usuario_id: int, contexto: ContextoAuditoria | None = None) -> Usuario:
        usuario = self._repo.desactivar(db, usuario_id, commit=False)
        politicas.registrar_bitacora_de(db, contexto, ENTIDAD_USUARIO, usuario.id, ACCION_DESACTIVAR, {})
        db.commit()
        db.refresh(usuario)
        return usuario

    def asignar_roles(
        self, db: Session, usuario_id: int, nombres_rol: list[str], contexto: ContextoAuditoria | None = None
    ) -> Usuario:
        usuario = self._repo.obtener(db, usuario_id)
        antes = sorted(r.nombre for r in usuario.roles)
        usuario = self._repo.asignar_roles(db, usuario, nombres_rol, commit=False)
        despues = sorted(r.nombre for r in usuario.roles)
        politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_USUARIO, usuario.id, ACCION_ASIGNAR_ROLES, {"antes": antes, "despues": despues}
        )
        db.commit()
        db.refresh(usuario)
        return usuario


class GestionarRolesPermisos:
    def __init__(self) -> None:
        self._repo = RolRepository()

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[Rol]:
        return list(self._repo.listar(db, paginacion))

    def obtener(self, db: Session, rol_id: int) -> Rol:
        return self._repo.obtener(db, rol_id)

    def crear(self, db: Session, datos: RolCrear, contexto: ContextoAuditoria | None = None) -> Rol:
        rol = self._repo.crear(db, datos, commit=False)
        politicas.registrar_bitacora_de(db, contexto, ENTIDAD_ROL, rol.id, ACCION_CREAR, {"nombre": rol.nombre})
        db.commit()
        db.refresh(rol)
        return rol

    def actualizar(
        self, db: Session, rol_id: int, datos: RolActualizar, contexto: ContextoAuditoria | None = None
    ) -> Rol:
        actual = self._repo.buscar(db, rol_id)
        cambios = diff_campos(actual, datos.model_dump(exclude_unset=True)) if actual else {}
        rol = self._repo.actualizar(db, rol_id, datos, commit=False)
        politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_ROL, rol.id, ACCION_ACTUALIZAR, {"nombre": rol.nombre, **cambios}
        )
        db.commit()
        db.refresh(rol)
        return rol

    def desactivar(self, db: Session, rol_id: int, contexto: ContextoAuditoria | None = None) -> Rol:
        rol = self._repo.desactivar(db, rol_id, commit=False)
        politicas.registrar_bitacora_de(db, contexto, ENTIDAD_ROL, rol.id, ACCION_DESACTIVAR, {"nombre": rol.nombre})
        db.commit()
        db.refresh(rol)
        return rol

    def asignar_permisos(
        self, db: Session, rol_id: int, codigos_permiso: list[str], contexto: ContextoAuditoria | None = None
    ) -> Rol:
        rol = self._repo.obtener(db, rol_id)
        antes = {p.codigo for p in rol.permisos}
        rol = self._repo.asignar_permisos(db, rol, codigos_permiso, commit=False)
        despues = {p.codigo for p in rol.permisos}
        politicas.registrar_bitacora_de(
            db, contexto, ENTIDAD_ROL, rol.id, ACCION_ASIGNAR_PERMISOS,
            {"agregados": sorted(despues - antes), "quitados": sorted(antes - despues)},
        )  # fmt: skip
        db.commit()
        db.refresh(rol)
        return rol

    def listar_permisos(self, db: Session) -> list[Permiso]:
        """El catálogo de permisos disponibles. Sin esto, `asignar_permisos`
        no tenía de dónde sacar los códigos válidos desde una interfaz: es la
        mitad de lectura de la misma operación del CU."""
        return self._repo.listar_permisos(db)
