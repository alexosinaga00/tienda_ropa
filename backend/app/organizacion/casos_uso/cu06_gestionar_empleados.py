"""CU-06 — Gestionar empleados y asignarlos a sucursal

Actor: Administrador.
Precondición: sesión de administrador; existen el usuario (CU-03) y la
sucursal (CU-05).
Postcondición: el empleado queda asignado a su sucursal; las reservas,
ventas y recepciones que registre se asocian a esa sucursal.
"""

from sqlalchemy.orm import Session

from app.core.deps import ParametrosPaginacion
from app.core.exceptions import ConflictoError, NoEncontradoError
from app.organizacion.models import Empleado
from app.organizacion.repository import EmpleadoRepository, SucursalRepository
from app.organizacion.schemas import EmpleadoActualizar, EmpleadoCrear, EmpleadoRespuesta
from app.seguridad import politicas as seguridad_politicas


class GestionarEmpleados:
    def __init__(self) -> None:
        self._empleados = EmpleadoRepository()
        self._sucursales = SucursalRepository()

    def _enriquecer(self, db: Session, empleados: list[Empleado]) -> list[EmpleadoRespuesta]:
        """Resuelve usuario_nombre/usuario_apellido/sucursal_nombre para que la
        tabla de empleados en Angular no muestre ids crudos. `organizacion` no
        puede consultar la tabla `usuario` directamente (regla 2 de CLAUDE.md),
        así que el nombre de usuario se resuelve vía seguridad.politicas."""
        usuarios = seguridad_politicas.obtener_usuarios_por_ids(db, [e.usuario_id for e in empleados])
        sucursal_ids = [e.sucursal_id for e in empleados if e.sucursal_id is not None]
        sucursales = {s.id: s for s in self._sucursales.listar_por_ids(db, sucursal_ids)}
        resultado = []
        for e in empleados:
            usuario = usuarios.get(e.usuario_id)
            sucursal = sucursales.get(e.sucursal_id) if e.sucursal_id is not None else None
            resultado.append(
                EmpleadoRespuesta.model_validate(e).model_copy(
                    update={
                        "usuario_nombre": usuario.nombre if usuario else None,
                        "usuario_apellido": usuario.apellido if usuario else None,
                        "sucursal_nombre": sucursal.nombre if sucursal else None,
                    }
                )
            )
        return resultado

    def listar(self, db: Session, paginacion: ParametrosPaginacion) -> list[EmpleadoRespuesta]:
        return self._enriquecer(db, list(self._empleados.listar(db, paginacion)))

    def obtener(self, db: Session, empleado_id: int) -> EmpleadoRespuesta:
        return self._enriquecer(db, [self._empleados.obtener(db, empleado_id)])[0]

    def obtener_mi_empleado(self, db: Session, usuario_id: int) -> EmpleadoRespuesta:
        """GET /empleados/yo: para que la caja (Angular) sepa en qué sucursal
        trabaja el cajero logueado, sin necesitar el permiso de administración
        de organizacion.gestionar (ver router)."""
        empleado = self._empleados.obtener_por_usuario(db, usuario_id)
        if empleado is None:
            raise NoEncontradoError("Este usuario no tiene un registro de empleado")
        return self._enriquecer(db, [empleado])[0]

    def crear(self, db: Session, datos: EmpleadoCrear) -> Empleado:
        seguridad_politicas.obtener_usuario(db, datos.usuario_id)  # valida que el usuario exista

        if datos.sucursal_id is not None:
            self._sucursales.obtener(db, datos.sucursal_id)  # 404 si no existe / está inactiva

        existente = self._empleados.obtener_por_usuario(db, datos.usuario_id)
        if existente is not None:
            if existente.activo:
                raise ConflictoError("Ese usuario ya es empleado")
            return self._empleados.reactivar(db, existente, datos)

        return self._empleados.crear(db, datos)

    def actualizar(self, db: Session, empleado_id: int, datos: EmpleadoActualizar) -> Empleado:
        if datos.sucursal_id is not None:
            self._sucursales.obtener(db, datos.sucursal_id)  # 404 si no existe / está inactiva
        return self._empleados.actualizar(db, empleado_id, datos)

    def desactivar(self, db: Session, empleado_id: int) -> Empleado:
        return self._empleados.desactivar(db, empleado_id)
