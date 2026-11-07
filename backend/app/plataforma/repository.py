import datetime as dt

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.crud_base import CRUDBase, CRUDBaseSinActivo
from app.core.exceptions import ConflictoError, DomainError, NoEncontradoError
from app.core.repository import confirmar, obtener_por_clave
from app.core.permisos import ROL_ADMINISTRADOR, ROL_SUPERADMINISTRADOR
from app.core.security import hash_password
from app.core.tenant import empresa_de, sin_filtro
from app.plataforma.models import (
    Bitacora,
    Ciudad,
    Cliente,
    CopiaSeguridad,
    DispositivoPush,
    Empleado,
    Empresa,
    HorarioSucursal,
    ESTADOS_PEDIDO_LIBERAN_CORREO,
    Notificacion,
    Permiso,
    PedidoContratacion,
    Plan,
    Rol,
    Sucursal,
    Suscripcion,
    Usuario,
    usuario_rol,
)
from app.plataforma.schemas import (
    CiudadActualizar,
    FiltrosBitacora,
    CiudadCrear,
    ClientePerfilActualizar,
    EmpleadoActualizar,
    EmpleadoCrear,
    EmpresaActualizar,
    EmpresaRegistrar,
    PlanActualizar,
    PlanCrear,
    RolActualizar,
    RolCrear,
    SucursalActualizar,
    SucursalCrear,
    SuscripcionAsignar,
    SuscripcionEstadoActualizar,
    UsuarioActualizar,
    UsuarioCrear,
)


# ---- Seguridad ----


class RolRepository(CRUDBase[Rol, RolCrear, RolActualizar]):
    def __init__(self) -> None:
        super().__init__(Rol)

    # Los roles son globales, pero el superadministrador es de la plataforma:
    # una sesion de empresa no lo ve (ni en listados ni por id).
    def buscar(self, db: Session, id_) -> Rol | None:
        rol = super().buscar(db, id_)
        if rol is not None and rol.nombre == ROL_SUPERADMINISTRADOR and empresa_de(db) is not None:
            return None
        return rol

    def listar(self, db: Session, paginacion, filtros=None) -> list[Rol]:
        roles = super().listar(db, paginacion, filtros)
        if empresa_de(db) is None:
            return roles
        return [r for r in roles if r.nombre != ROL_SUPERADMINISTRADOR]

    def asignar_permisos(self, db: Session, rol: Rol, codigos: list[str], commit: bool = True) -> Rol:
        codigos_unicos = set(codigos)
        permisos = list(db.scalars(select(Permiso).where(Permiso.codigo.in_(codigos_unicos))))
        if len(permisos) != len(codigos_unicos):
            raise DomainError("Uno o más códigos de permiso no existen")
        rol.permisos = permisos
        confirmar(db, commit)
        db.refresh(rol)
        return rol

    def listar_permisos(self, db: Session) -> list[Permiso]:
        """El catálogo completo de permisos, para que la pantalla de roles
        pueda ofrecerlos como casillas. Ordenado por módulo y código para que
        salga agrupado sin que el cliente tenga que ordenarlo. No se pagina:
        son pocos y fijos, y una página parcial dejaría permisos fuera de la
        vista sin que se note."""
        return list(db.scalars(select(Permiso).order_by(Permiso.modulo, Permiso.codigo)))


class UsuarioRepository(CRUDBase[Usuario, UsuarioCrear, UsuarioActualizar]):
    def __init__(self) -> None:
        super().__init__(Usuario)

    def obtener_por_email(self, db: Session, email: str) -> Usuario | None:
        """El usuario con ese correo DENTRO de la empresa de la sesión. El
        correo no distingue mayúsculas (los datos anteriores a que se
        guardara en minúsculas siguen encontrándose)."""
        return db.scalar(select(Usuario).where(func.lower(Usuario.email) == email.lower()))

    def obtener_de_plataforma_por_email(self, db: Session, email: str) -> Usuario | None:
        """El usuario SIN empresa (superadministrador) con ese correo, si de
        verdad tiene el rol superadministrador. Único uso, junto con
        get_current_user, de una consulta de usuarios sin filtro de empresa."""
        usuario = db.scalar(
            sin_filtro(
                select(Usuario).where(Usuario.empresa_id.is_(None), func.lower(Usuario.email) == email.lower())
            )
        )
        if usuario is None or ROL_SUPERADMINISTRADOR not in {r.nombre for r in usuario.roles}:
            return None
        return usuario

    def obtener_sin_empresa_por_correo(self, db: Session, email: str) -> Usuario | None:
        """El usuario sin empresa con ese correo, tenga el rol que tenga: para
        que scripts/crear_superadmin.py no duplique ni pise a un usuario ajeno."""
        return db.scalar(
            sin_filtro(
                select(Usuario).where(Usuario.empresa_id.is_(None), func.lower(Usuario.email) == email.lower())
            )
        )

    def listar_por_ids(self, db: Session, ids: list[int]) -> list[Usuario]:
        if not ids:
            return []
        return list(db.scalars(select(Usuario).where(Usuario.id.in_(ids))))

    def crear(self, db: Session, datos: UsuarioCrear, commit: bool = True) -> Usuario:
        return self.crear_con_hash(db, datos, hash_password(datos.password), commit)

    def crear_con_hash(self, db: Session, datos, password_hash: str, commit: bool = True) -> Usuario:
        """Como `crear`, pero con un hash bcrypt YA calculado (la contratación pública guarda solo el hash
        del pedido, nunca la contraseña). `datos` aporta nombre, apellido, email y teléfono; su
        `password`, si la tiene, se ignora."""
        existente = self.obtener_por_email(db, datos.email)
        if existente is not None:
            if existente.activo:
                raise ConflictoError("Ya existe un usuario con ese email")
            existente.nombre = datos.nombre
            existente.apellido = datos.apellido
            existente.telefono = datos.telefono
            existente.password_hash = password_hash
            existente.activo = True
            confirmar(db, commit)
            db.refresh(existente)
            return existente
        usuario = Usuario(
            nombre=datos.nombre,
            apellido=datos.apellido,
            email=datos.email,
            telefono=datos.telefono,
            password_hash=password_hash,
        )
        db.add(usuario)
        confirmar(db, commit)
        db.refresh(usuario)
        return usuario

    def actualizar_password(self, db: Session, usuario: Usuario, password: str, commit: bool = True) -> None:
        usuario.password_hash = hash_password(password)
        confirmar(db, commit)

    # -- Siempre al menos un administrador activo por empresa (D36) ------------

    def contar_otros_administradores_activos(self, db: Session, usuario_id: int) -> int:
        """Usuarios activos con el rol administrador, de la empresa de la
        sesión, sin contar a `usuario_id`."""
        consulta = (
            select(func.count(func.distinct(Usuario.id)))
            .select_from(Usuario)
            .join(usuario_rol, usuario_rol.c.usuario_id == Usuario.id)
            .join(Rol, Rol.id == usuario_rol.c.rol_id)
            .where(Rol.nombre == ROL_ADMINISTRADOR, Usuario.activo.is_(True), Usuario.id != usuario_id)
        )
        return db.scalar(consulta) or 0

    def _exigir_otro_administrador(self, db: Session, usuario: Usuario, accion: str) -> None:
        """409 si `usuario` es el último administrador activo de su empresa y se
        le va a desactivar o quitar el rol (`accion` completa el mensaje)."""
        if usuario.empresa_id is None or not usuario.activo:
            return
        if ROL_ADMINISTRADOR not in {r.nombre for r in usuario.roles}:
            return
        if self.contar_otros_administradores_activos(db, usuario.id) == 0:
            raise ConflictoError(
                f"No se puede {accion}: es el último administrador activo de la empresa. "
                "Asigne primero el rol de administrador a otro usuario"
            )

    def actualizar(self, db: Session, id_, datos, commit: bool = True) -> Usuario:
        if datos.activo is False:
            usuario = self.buscar(db, id_)
            if usuario is not None:
                self._exigir_otro_administrador(db, usuario, "desactivar al usuario")
        return super().actualizar(db, id_, datos, commit)

    def desactivar(self, db: Session, id_, commit: bool = True) -> Usuario:
        self._exigir_otro_administrador(db, self.obtener(db, id_), "desactivar al usuario")
        return super().desactivar(db, id_, commit)

    def asignar_roles(
        self, db: Session, usuario: Usuario, nombres_rol: list[str], commit: bool = True
    ) -> Usuario:
        from app.plataforma.politicas import validar_roles_asignables  # import diferido: politicas importa este módulo

        nombres_unicos = set(nombres_rol)
        validar_roles_asignables(usuario.empresa_id, nombres_unicos)
        if ROL_ADMINISTRADOR not in nombres_unicos:
            self._exigir_otro_administrador(db, usuario, "quitar el rol de administrador")
        roles = list(
            db.scalars(select(Rol).where(Rol.nombre.in_(nombres_unicos), Rol.activo.is_(True)))
        )
        if len(roles) != len(nombres_unicos):
            raise DomainError("Uno o más roles no existen o están inactivos")
        usuario.roles = roles
        confirmar(db, commit)
        db.refresh(usuario)
        return usuario


class ClienteRepository:
    def obtener(self, db: Session, cliente_id: int) -> Cliente:
        cliente = obtener_por_clave(db, Cliente, cliente_id)
        if cliente is None:
            raise NoEncontradoError("Cliente no encontrado")
        return cliente

    def obtener_por_usuario(self, db: Session, usuario_id: int) -> Cliente:
        cliente = db.scalar(select(Cliente).where(Cliente.usuario_id == usuario_id))
        if cliente is None:
            raise NoEncontradoError("Perfil de cliente no encontrado")
        return cliente

    def listar_minimos(self, db: Session, desde_id: int, limite: int) -> tuple[list[tuple], int, bool]:
        """Clientes de la empresa con usuario activo, SOLO (id, nombre, apellido, ci_nit), por
        clave (`id > desde_id`). Se piden columnas sueltas, no el modelo: así correo, teléfono y el
        resto del perfil ni siquiera se leen. Devuelve (filas, total de clientes activos,
        hay_mas)."""
        activos = (Usuario.activo.is_(True),)
        total = (
            db.scalar(
                select(func.count()).select_from(Cliente).join(Usuario, Usuario.id == Cliente.usuario_id).where(*activos)
            )
            or 0
        )
        filas = list(
            db.execute(
                select(Cliente.id, Usuario.nombre, Usuario.apellido, Cliente.ci_nit)
                .join(Usuario, Usuario.id == Cliente.usuario_id)
                .where(*activos, Cliente.id > desde_id)
                .order_by(Cliente.id)
                .limit(limite + 1)
            )
        )
        return filas[:limite], total, len(filas) > limite

    def buscar_por_usuario(self, db: Session, usuario_id: int) -> Cliente | None:
        """Variante de obtener_por_usuario que no lanza si no existe, para
        que el caller decida si crea el perfil o lo reusa (ver
        plataforma.casos_uso.cu01_autenticar_registrar_usuarios.RegistrarCliente.registrar)."""
        return db.scalar(select(Cliente).where(Cliente.usuario_id == usuario_id))

    def crear_o_actualizar_perfil(
        self, db: Session, usuario_id: int, ci_nit: str | None, commit: bool = True
    ) -> Cliente:
        """Alta del perfil de cliente de un usuario. Si el usuario venía
        reactivado (estaba dado de baja con este mismo email) puede ya tener un
        perfil de antes -- cliente.usuario_id es único, así que insertar uno
        nuevo rompería con IntegrityError: en ese caso se reutiliza y se le
        actualiza el ci_nit."""
        cliente = self.buscar_por_usuario(db, usuario_id)
        if cliente is not None:
            cliente.ci_nit = ci_nit
        else:
            cliente = Cliente(usuario_id=usuario_id, ci_nit=ci_nit)
            db.add(cliente)
        confirmar(db, commit)
        db.refresh(cliente)
        return cliente

    def actualizar_perfil(
        self, db: Session, usuario_id: int, datos: ClientePerfilActualizar, commit: bool = True
    ) -> Cliente:
        cliente = self.obtener_por_usuario(db, usuario_id)
        for campo, valor in datos.model_dump(exclude_unset=True).items():
            setattr(cliente, campo, valor)
        confirmar(db, commit)
        db.refresh(cliente)
        return cliente


# ---- Notificaciones ----


class NotificacionRepository:
    """Sin `activo`: una notificación no se desactiva, se marca leída o
    simplemente se acumula."""

    def crear(
        self,
        db: Session,
        usuario_id: int,
        titulo: str,
        mensaje: str | None,
        tipo: str | None,
        referencia_id: int | None,
    ) -> Notificacion:
        notificacion = Notificacion(
            usuario_id=usuario_id, titulo=titulo, mensaje=mensaje, tipo=tipo, referencia_id=referencia_id
        )
        db.add(notificacion)
        db.flush()
        return notificacion

    def listar_por_usuario(self, db: Session, usuario_id: int) -> list[Notificacion]:
        return list(
            db.scalars(
                select(Notificacion)
                .where(Notificacion.usuario_id == usuario_id)
                # `id` desempata: dos avisos creados en el mismo instante (la misma transacción)
                # comparten `creado_en` y sin esto su orden sería indeterminado.
                .order_by(Notificacion.creado_en.desc(), Notificacion.id.desc())
            )
        )

    def marcar_leida(self, db: Session, usuario_id: int, notificacion_id: int) -> Notificacion:
        notificacion = obtener_por_clave(db, Notificacion, notificacion_id)
        if notificacion is None or notificacion.usuario_id != usuario_id:
            raise NoEncontradoError("Notificación no encontrada")
        notificacion.leida = True
        db.commit()
        db.refresh(notificacion)
        return notificacion


# ---- Dispositivos de notificaciones push ----


class DispositivoPushRepository:
    """Los teléfonos que reciben push. Todas las consultas pasan por el filtro automático de empresa. El token es único
    por empresa: se busca SIN mirar el usuario, porque un teléfono puede cambiar de dueño."""

    def obtener_por_token(self, db: Session, token: str) -> DispositivoPush | None:
        return db.scalar(select(DispositivoPush).where(DispositivoPush.token == token))

    def crear(self, db: Session, usuario_id: int, token: str, plataforma: str) -> DispositivoPush:
        dispositivo = DispositivoPush(usuario_id=usuario_id, token=token, plataforma=plataforma, activo=True)
        db.add(dispositivo)
        db.flush()
        return dispositivo

    def listar_activos(self, db: Session, usuario_id: int) -> list[DispositivoPush]:
        """Del más antiguo al más reciente (por último uso; `id` desempata)."""
        return list(
            db.scalars(
                select(DispositivoPush)
                .where(DispositivoPush.usuario_id == usuario_id, DispositivoPush.activo.is_(True))
                .order_by(DispositivoPush.actualizado_en, DispositivoPush.id)
            )
        )

    def para_notificaciones(self, db: Session, notificacion_ids: list[int]) -> list[tuple[Notificacion, DispositivoPush]]:
        """Cada notificación (si sigue existiendo) con los dispositivos ACTIVOS de su usuario, si el usuario sigue activo."""
        return [
            (notificacion, dispositivo)
            for notificacion, dispositivo in db.execute(
                select(Notificacion, DispositivoPush)
                .join(DispositivoPush, DispositivoPush.usuario_id == Notificacion.usuario_id)
                .join(Usuario, Usuario.id == Notificacion.usuario_id)
                .where(
                    Notificacion.id.in_(notificacion_ids),
                    DispositivoPush.activo.is_(True),
                    Usuario.activo.is_(True),
                )
                .order_by(Notificacion.id, DispositivoPush.id)
            )
        ]

    def desactivar(self, db: Session, dispositivo_ids: list[int], ahora: dt.datetime) -> None:
        db.execute(
            update(DispositivoPush)
            .where(DispositivoPush.id.in_(dispositivo_ids))
            .values(activo=False, actualizado_en=ahora)
        )


# ---- Organización ----


class CiudadRepository(CRUDBase[Ciudad, CiudadCrear, CiudadActualizar]):
    def __init__(self) -> None:
        super().__init__(Ciudad)

    def crear(self, db: Session, datos: CiudadCrear, commit: bool = True) -> Ciudad:
        existe = db.scalar(
            select(Ciudad).where(
                Ciudad.nombre == datos.nombre, Ciudad.departamento == datos.departamento
            )
        )
        if existe is not None:
            raise ConflictoError("Ya existe una ciudad con ese nombre y departamento")
        return super().crear(db, datos, commit)


class SucursalRepository(CRUDBase[Sucursal, SucursalCrear, SucursalActualizar]):
    def __init__(self) -> None:
        super().__init__(Sucursal)

    def obtener_por_codigo(self, db: Session, codigo: str) -> Sucursal | None:
        return db.scalar(select(Sucursal).where(Sucursal.codigo == codigo))

    def listar_por_ids(self, db: Session, ids: list[int]) -> list[Sucursal]:
        if not ids:
            return []
        return list(db.scalars(select(Sucursal).where(Sucursal.id.in_(ids))))

    def listar_activas(self, db: Session) -> list[Sucursal]:
        """Todas las sucursales activas de la empresa (el depósito incluido), por id."""
        return list(db.scalars(select(Sucursal).where(Sucursal.activo.is_(True)).order_by(Sucursal.id)))

    def crear(self, db: Session, datos: SucursalCrear, commit: bool = True) -> Sucursal:
        if self.obtener_por_codigo(db, datos.codigo) is not None:
            raise ConflictoError("Ya existe una sucursal con ese código")
        ciudad = obtener_por_clave(db, Ciudad, datos.ciudad_id)
        if ciudad is None or not ciudad.activo:
            raise NoEncontradoError("Ciudad no encontrada")
        self._verificar_limite_del_plan(db)
        return super().crear(db, datos, commit)

    def actualizar(self, db: Session, id_: int, datos: SucursalActualizar, commit: bool = True) -> Sucursal:
        # La ciudad llega del cliente y se escribe como FK: se resuelve con una
        # búsqueda filtrada por empresa (404 si no existe, está inactiva o es
        # de otra empresa), igual que en `crear`.
        if datos.ciudad_id is not None:
            CiudadRepository().obtener(db, datos.ciudad_id)
        # Reactivar una sucursal inactiva ocupa un cupo del plan, igual que
        # crearla. Editar una sucursal ya activa (o desactivar) no cuenta.
        if datos.activo is True:
            existente = self.buscar(db, id_)
            if existente is not None and not existente.activo:
                self._verificar_limite_del_plan(db)
        return super().actualizar(db, id_, datos, commit)

    @staticmethod
    def _verificar_limite_del_plan(db: Session) -> None:
        # Import diferido: politicas importa este módulo. Toma el bloqueo de la
        # suscripción (PostgreSQL) hasta el commit, así dos altas simultáneas
        # no pasan las dos con un solo cupo.
        from app.plataforma.politicas import verificar_limite_sucursales

        verificar_limite_sucursales(db)


class HorarioRepository:
    """No hereda de CRUDBase: horario_sucursal no tiene columna `activo`,
    las filas se eliminan físicamente."""

    def listar_por_sucursal(self, db: Session, sucursal_id: int) -> list[HorarioSucursal]:
        return list(
            db.scalars(
                select(HorarioSucursal)
                .where(HorarioSucursal.sucursal_id == sucursal_id)
                .order_by(HorarioSucursal.dia_semana)
            )
        )

    def listar_por_sucursales(self, db: Session, sucursal_ids: list[int]) -> dict[int, list[HorarioSucursal]]:
        """Los horarios de varias sucursales en UNA consulta: {sucursal_id: horarios por día}."""
        agrupados: dict[int, list[HorarioSucursal]] = {sucursal_id: [] for sucursal_id in sucursal_ids}
        if sucursal_ids:
            for horario in db.scalars(
                select(HorarioSucursal)
                .where(HorarioSucursal.sucursal_id.in_(sucursal_ids))
                .order_by(HorarioSucursal.sucursal_id, HorarioSucursal.dia_semana)
            ):
                agrupados[horario.sucursal_id].append(horario)
        return agrupados

    def obtener(self, db: Session, sucursal_id: int, horario_id: int) -> HorarioSucursal:
        horario = db.scalar(
            select(HorarioSucursal).where(
                HorarioSucursal.id == horario_id, HorarioSucursal.sucursal_id == sucursal_id
            )
        )
        if horario is None:
            raise NoEncontradoError("Horario no encontrado")
        return horario

    def obtener_por_dia(self, db: Session, sucursal_id: int, dia_semana: int) -> HorarioSucursal | None:
        return db.scalar(
            select(HorarioSucursal).where(
                HorarioSucursal.sucursal_id == sucursal_id,
                HorarioSucursal.dia_semana == dia_semana,
            )
        )

    def crear(self, db: Session, sucursal_id: int, horario: HorarioSucursal) -> HorarioSucursal:
        db.add(horario)
        db.commit()
        db.refresh(horario)
        return horario

    def actualizar(self, db: Session, horario: HorarioSucursal, hora_apertura, hora_cierre) -> HorarioSucursal:
        if hora_apertura is not None:
            horario.hora_apertura = hora_apertura
        if hora_cierre is not None:
            horario.hora_cierre = hora_cierre
        db.commit()
        db.refresh(horario)
        return horario

    def eliminar(self, db: Session, horario: HorarioSucursal) -> None:
        db.delete(horario)
        db.commit()


class EmpleadoRepository(CRUDBase[Empleado, EmpleadoCrear, EmpleadoActualizar]):
    def __init__(self) -> None:
        super().__init__(Empleado)

    def obtener_por_usuario(self, db: Session, usuario_id: int) -> Empleado | None:
        return db.scalar(select(Empleado).where(Empleado.usuario_id == usuario_id))

    def reactivar(self, db: Session, empleado: Empleado, datos: EmpleadoCrear, commit: bool = True) -> Empleado:
        """Reusa la fila de un empleado dado de baja en vez de dejar un
        duplicado: `obtener_por_usuario` no filtra por `activo`, así que un
        usuario solo puede tener una fila de empleado en toda su historia."""
        empleado.activo = True
        empleado.sucursal_id = datos.sucursal_id
        empleado.cargo = datos.cargo
        empleado.ci = datos.ci
        empleado.fecha_ingreso = datos.fecha_ingreso
        confirmar(db, commit)
        db.refresh(empleado)
        return empleado

    def listar_por_sucursal(self, db: Session, sucursal_id: int) -> list[Empleado]:
        return list(
            db.scalars(
                select(Empleado).where(
                    Empleado.sucursal_id == sucursal_id, Empleado.activo.is_(True)
                )
            )
        )


# ---- Empresas, planes y suscripciones ----


class EmpresaRepository(CRUDBase[Empresa, EmpresaRegistrar, EmpresaActualizar]):
    """`empresa` es la raíz del aislamiento: no lleva filtro de empresa, así que
    estas consultas valen en cualquier sesión (superadministrador o empresa).
    Quien las expone decide quién las puede pedir."""

    def __init__(self) -> None:
        super().__init__(Empresa)

    def obtener_por_codigo(self, db: Session, codigo: str) -> Empresa | None:
        return db.scalar(select(Empresa).where(Empresa.codigo == codigo))

    def insertar(self, db: Session, nombre: str, codigo: str, logo_url: str | None, color_acento: str | None) -> Empresa:
        """Inserta la empresa sin confirmar (la transacción es de quien registra).
        El código ya viene normalizado; si choca, 409."""
        if self.obtener_por_codigo(db, codigo) is not None:
            raise ConflictoError("Ya existe una empresa con ese nombre")
        empresa = Empresa(nombre=nombre, codigo=codigo, logo_url=logo_url, color_acento=color_acento)
        db.add(empresa)
        db.flush()
        return empresa

    def listar_filtrado(
        self, db: Session, paginacion, q: str | None = None, activo: bool | None = None
    ) -> list[Empresa]:
        """Para el superadministrador: incluye las inactivas (`activo` filtra)."""
        consulta = select(Empresa)
        if q:
            patron = f"%{q.strip().lower()}%"
            consulta = consulta.where(
                func.lower(Empresa.nombre).like(patron) | func.lower(Empresa.codigo).like(patron)
            )
        if activo is not None:
            consulta = consulta.where(Empresa.activo.is_(activo))
        consulta = consulta.order_by(Empresa.id).offset(paginacion.offset).limit(paginacion.tamanio)
        return list(db.scalars(consulta))

    def tiene_suscripcion_activa(self, db: Session, empresa_id: int) -> bool:
        """Si la empresa opera hoy: suscripción `activa` y vigente por fecha (el
        mismo criterio de `listar_publicas`)."""
        from app.core.tiempo import hoy_utc

        consulta = select(Suscripcion.id).where(
            Suscripcion.empresa_id == empresa_id,
            Suscripcion.estado == "activa",
            Suscripcion.fecha_vencimiento >= hoy_utc(),
        )
        return db.scalar(sin_filtro(consulta.limit(1))) is not None

    def listar_publicas(self, db: Session, paginacion, q: str | None = None) -> list[Empresa]:
        """Las tiendas que se muestran al público: empresas activas con una
        suscripción activa y vigente por fecha. Ordenadas por nombre."""
        from app.core.tiempo import hoy_utc

        hoy = hoy_utc()
        con_suscripcion_activa = (
            select(Suscripcion.empresa_id)
            .where(Suscripcion.estado == "activa", Suscripcion.fecha_vencimiento >= hoy)
        )
        consulta = select(Empresa).where(Empresa.activo.is_(True), Empresa.id.in_(con_suscripcion_activa))
        if q:
            patron = f"%{q.strip().lower()}%"
            consulta = consulta.where(
                func.lower(Empresa.nombre).like(patron) | func.lower(Empresa.codigo).like(patron)
            )
        consulta = consulta.order_by(func.lower(Empresa.nombre), Empresa.id).offset(paginacion.offset).limit(paginacion.tamanio)
        # La suscripción se mira de TODAS las empresas (la lista es pública):
        # `sin_filtro` va en la consulta externa, que es la que el filtro revisa.
        return list(db.scalars(sin_filtro(consulta)))


class PlanRepository(CRUDBase[Plan, PlanCrear, PlanActualizar]):
    """`plan` es global. `listar` (heredado) solo trae los activos."""

    def __init__(self) -> None:
        super().__init__(Plan)

    def obtener_por_codigo(self, db: Session, codigo: str) -> Plan | None:
        """El plan con ese código, activo o no."""
        return db.scalar(select(Plan).where(Plan.codigo == codigo))

    def en_uso(self, db: Session, plan_id: int) -> bool:
        """Si alguna suscripción NO cancelada (de cualquier empresa) usa el plan."""
        consulta = select(func.count(Suscripcion.id)).where(
            Suscripcion.plan_id == plan_id, Suscripcion.estado != "cancelada"
        )
        return (db.scalar(sin_filtro(consulta)) or 0) > 0

    def listar_todos(self, db: Session, paginacion) -> list[Plan]:
        """Para el superadministrador: incluye los planes inactivos."""
        consulta = select(Plan).order_by(Plan.id).offset(paginacion.offset).limit(paginacion.tamanio)
        return list(db.scalars(consulta))

    def listar_publicos(self, db: Session) -> list[Plan]:
        """Los planes activos para la portada pública, del más chico al más grande."""
        consulta = select(Plan).where(Plan.activo.is_(True)).order_by(Plan.max_sucursales, Plan.id)
        return list(db.scalars(consulta))

    def por_ids(self, db: Session, ids) -> dict[int, Plan]:
        ids = set(ids)
        if not ids:
            return {}
        return {plan.id: plan for plan in db.scalars(select(Plan).where(Plan.id.in_(ids)))}


class SuscripcionRepository(CRUDBaseSinActivo[Suscripcion, SuscripcionAsignar, SuscripcionEstadoActualizar]):
    """Consultas del SUPERADMINISTRADOR sobre las suscripciones de todas las
    empresas (`sin_filtro`, permitido para esta tabla). Solo se usa desde una
    sesión sin empresa. Para operar sobre UNA empresa se entra con
    `core.tenant.en_empresa` y se usan las políticas, que sí filtran."""

    def __init__(self) -> None:
        super().__init__(Suscripcion)

    def _aplicar_alcance(self, consulta):
        return sin_filtro(consulta)

    def listar_filtrado(
        self, db: Session, paginacion, empresa_id: int | None = None, estado: str | None = None
    ) -> list[Suscripcion]:
        """`estado` es el EFECTIVO: `vencida` incluye a las activas cuya fecha ya
        pasó (aunque la tarea no las haya persistido) y `activa` solo a las
        vigentes por fecha."""
        from app.core.tiempo import hoy_utc

        hoy = hoy_utc()
        consulta = self._aplicar_alcance(select(Suscripcion))
        if empresa_id is not None:
            consulta = consulta.where(Suscripcion.empresa_id == empresa_id)
        if estado == "activa":
            consulta = consulta.where(Suscripcion.estado == "activa", Suscripcion.fecha_vencimiento >= hoy)
        elif estado == "vencida":
            consulta = consulta.where(
                (Suscripcion.estado == "vencida")
                | ((Suscripcion.estado == "activa") & (Suscripcion.fecha_vencimiento < hoy))
            )
        elif estado is not None:
            consulta = consulta.where(Suscripcion.estado == estado)
        consulta = consulta.order_by(Suscripcion.id).offset(paginacion.offset).limit(paginacion.tamanio)
        return list(db.scalars(consulta))

    def vigentes_de(self, db: Session, empresa_ids) -> dict[int, tuple[Suscripcion, Plan]]:
        """La suscripción NO cancelada (con su plan) de cada empresa, en un solo
        SELECT, para los listados del superadministrador."""
        ids = set(empresa_ids)
        if not ids:
            return {}
        consulta = self._aplicar_alcance(
            select(Suscripcion, Plan)
            .join(Plan, Plan.id == Suscripcion.plan_id)
            .where(Suscripcion.empresa_id.in_(ids), Suscripcion.estado != "cancelada")
        )
        return {s.empresa_id: (s, p) for s, p in db.execute(consulta)}

    def insertar(
        self,
        db: Session,
        empresa_id: int,
        plan_id: int,
        fecha_inicio,
        fecha_vencimiento,
        estado: str = "activa",
        es_prueba: bool = False,
    ) -> Suscripcion:
        """Inserta una suscripción sin confirmar. El `empresa_id` va explícito:
        la sesión del superadministrador no tiene empresa (o ya está en la
        misma). Un segundo vigente lo rechaza el índice parcial (IntegrityError
        al volcar)."""
        suscripcion = Suscripcion(
            empresa_id=empresa_id,
            plan_id=plan_id,
            estado=estado,
            fecha_inicio=fecha_inicio,
            fecha_vencimiento=fecha_vencimiento,
            es_prueba=es_prueba,
        )
        db.add(suscripcion)
        db.flush()
        return suscripcion

    def empresa_de_suscripcion(self, db: Session, suscripcion_id: int) -> int:
        """El `empresa_id` de la suscripción, o 404."""
        empresa_id = db.scalar(sin_filtro(select(Suscripcion.empresa_id).where(Suscripcion.id == suscripcion_id)))
        if empresa_id is None:
            raise NoEncontradoError("Suscripción no encontrada")
        return empresa_id


class PedidoContratacionRepository:
    """Pedidos de contratación (compra o prueba gratuita de la portada pública). `pedido_contratacion` es una
    tabla GLOBAL (sin `empresa_id`): sus consultas valen en cualquier sesión, incluida la anónima."""

    def prueba_que_ocupa_el_correo(self, db: Session, correo: str) -> PedidoContratacion | None:
        """El pedido de prueba que hoy ocupa ese correo (los cancelados, vencidos y fallidos lo liberan), igual que
        el índice único parcial `ux_pedido_prueba_correo`."""
        return db.scalar(
            select(PedidoContratacion).where(
                PedidoContratacion.tipo == "prueba",
                func.lower(PedidoContratacion.admin_email) == correo.lower(),
                PedidoContratacion.estado.not_in(ESTADOS_PEDIDO_LIBERAN_CORREO),
            )
        )

    def insertar(self, db: Session, **campos) -> PedidoContratacion:
        """Inserta el pedido y vuelca (`flush`) sin confirmar: la transacción es de quien lo crea. Si otro pedido de
        prueba ocupa el correo, el índice único lanza `IntegrityError` aquí mismo."""
        pedido = PedidoContratacion(**campos)
        db.add(pedido)
        db.flush()
        return pedido

    def enlazar_empresa(self, db: Session, pedido_id: int, empresa_id: int) -> None:
        """Anota la empresa creada. UPDATE directo: la sesión pudo soltar el objeto al cambiar de empresa."""
        db.execute(
            update(PedidoContratacion)
            .where(PedidoContratacion.id == pedido_id)
            .values(empresa_creada_id=empresa_id)
            .execution_options(synchronize_session=False)
        )

    def obtener_de_pago(self, db: Session, token: str, bloquear: bool = False) -> PedidoContratacion | None:
        """El pedido de COMPRA con ese token (uno de prueba gratuita o un token inexistente es `None`: mismo 404).
        `bloquear=True` toma la fila con SELECT ... FOR UPDATE (solo PostgreSQL; SQLite lo omite): serializa dos
        capturas o una captura y una cancelación del mismo pedido, y relee la fila ya confirmada por quien esperaba."""
        consulta = select(PedidoContratacion).where(PedidoContratacion.token == token, PedidoContratacion.tipo == "pago")
        if bloquear:
            consulta = consulta.with_for_update().execution_options(populate_existing=True)
        return db.scalar(consulta)

    def actualizar(self, db: Session, pedido_id: int, **valores) -> None:
        """UPDATE directo, sin confirmar (la sesión pudo soltar el objeto al cambiar de empresa)."""
        db.execute(
            update(PedidoContratacion)
            .where(PedidoContratacion.id == pedido_id)
            .values(**valores)
            .execution_options(synchronize_session=False)
        )

    def vencer_vencidos(self, db: Session, ahora: dt.datetime) -> int:
        """`pendiente` -> `vencido` para los pedidos cuyo plazo (`expira_en`) ya pasó. Sin confirmar."""
        resultado = db.execute(
            update(PedidoContratacion)
            .where(
                PedidoContratacion.estado == "pendiente",
                PedidoContratacion.expira_en.is_not(None),
                PedidoContratacion.expira_en < ahora,
            )
            .values(estado="vencido")
            .execution_options(synchronize_session=False)
        )
        return resultado.rowcount

    def obtener_plan(self, db: Session, plan_id: int) -> Plan | None:
        """El plan del pedido (tabla global, activo o no: el pedido ya lo eligió)."""
        return db.get(Plan, plan_id)

    def obtener_empresa(self, db: Session, empresa_id: int) -> Empresa | None:
        """La empresa creada por el pedido (`empresa` es la raíz: no lleva filtro de empresa)."""
        return db.get(Empresa, empresa_id)


# ---- Bitácora ----


class BitacoraRepository:
    """Sin `activo` y sin filtro automático: la tabla admite `empresa_id` NULL y
    el superadministrador la lee entera, así que CADA consulta lleva su
    restricción de forma explícita (`empresa_id` de la empresa, o `plataforma=True`
    solo desde la ruta del superadministrador)."""

    def crear(self, db: Session, fila: Bitacora) -> Bitacora:
        db.add(fila)
        db.flush()
        return fila

    @staticmethod
    def _condiciones(filtros: FiltrosBitacora, empresa_id: int | None, plataforma: bool) -> list:
        if plataforma:
            if filtros.sin_empresa:
                condiciones = [Bitacora.empresa_id.is_(None)]
            elif filtros.empresa_id is not None:
                condiciones = [Bitacora.empresa_id == filtros.empresa_id]
            else:
                condiciones = []
        else:
            if empresa_id is None:  # defensa en profundidad: nunca una consulta sin restricción
                raise ValueError("La consulta de una empresa exige su empresa_id")
            condiciones = [Bitacora.empresa_id == empresa_id]
        # Fechas inclusivas: de las 00:00 del `desde` a las 00:00 del día siguiente al `hasta`.
        condiciones.append(Bitacora.creado_en >= dt.datetime.combine(filtros.desde, dt.time.min))
        condiciones.append(Bitacora.creado_en < dt.datetime.combine(filtros.hasta + dt.timedelta(days=1), dt.time.min))
        if filtros.entidad is not None:
            condiciones.append(Bitacora.entidad == filtros.entidad)
        if filtros.accion is not None:
            condiciones.append(Bitacora.accion == filtros.accion)
        if filtros.usuario_id is not None:
            condiciones.append(Bitacora.usuario_id == filtros.usuario_id)
        return condiciones

    def listar(
        self,
        db: Session,
        filtros: FiltrosBitacora,
        paginacion,
        *,
        empresa_id: int | None = None,
        plataforma: bool = False,
    ) -> tuple[list[Bitacora], int]:
        condiciones = self._condiciones(filtros, empresa_id, plataforma)
        total = db.scalar(select(func.count()).select_from(Bitacora).where(*condiciones)) or 0
        filas = db.scalars(
            select(Bitacora)
            .where(*condiciones)
            .order_by(Bitacora.creado_en.desc(), Bitacora.id.desc())
            .offset(paginacion.offset)
            .limit(paginacion.tamanio)
        )
        return list(filas), total

    def obtener(
        self, db: Session, bitacora_id: int, *, empresa_id: int | None = None, plataforma: bool = False
    ) -> Bitacora | None:
        consulta = select(Bitacora).where(Bitacora.id == bitacora_id)
        if not plataforma:
            if empresa_id is None:
                raise ValueError("La consulta de una empresa exige su empresa_id")
            consulta = consulta.where(Bitacora.empresa_id == empresa_id)
        return db.scalar(consulta)

    def actores(self, db: Session, usuario_ids) -> dict[int, tuple[str, int | None]]:
        """Nombre completo y empresa de cada usuario, en un solo SELECT. Va sin
        filtro de empresa (permitido para `Usuario`) porque el actor puede ser un
        superadministrador, que no tiene empresa."""
        ids = {i for i in usuario_ids if i is not None}
        if not ids:
            return {}
        filas = db.execute(
            sin_filtro(select(Usuario.id, Usuario.nombre, Usuario.apellido, Usuario.empresa_id).where(Usuario.id.in_(ids)))
        )
        return {fila.id: (f"{fila.nombre} {fila.apellido}", fila.empresa_id) for fila in filas}

    def purgar_anteriores_a(self, db: Session, limite: dt.datetime, lote: int = 5000) -> int:
        """Borra a lo sumo `lote` filas anteriores a `limite` (DELETE de SQL, que no
        pasa por la guardia de solo anexar) y devuelve cuántas. Quien llama repite
        hasta que devuelva 0, confirmando cada lote."""
        ids = list(
            db.scalars(
                select(Bitacora.id).where(Bitacora.creado_en < limite).order_by(Bitacora.id).limit(lote)
            )
        )
        if not ids:
            return 0
        db.execute(delete(Bitacora.__table__).where(Bitacora.__table__.c.id.in_(ids)))
        return len(ids)


# ---- Copias de seguridad (E22) ----


class CopiaSeguridadRepository:
    """Historial de copias de la empresa de la sesión (el filtro automático de `EmpresaMixin` aplica a todo). La fila
    `en_proceso` es el candado: el índice único parcial `ux_copia_en_proceso` deja una sola por empresa. Nada se borra:
    `activo` = False saca una copia del historial visible."""

    def crear_en_proceso(self, db: Session, usuario_id: int) -> CopiaSeguridad:
        """Inserta la fila candado. Si ya hay una en proceso lanza `IntegrityError` al volcar (lo traduce el caso de uso)."""
        # La hora la fija Python en UTC (no el `now()` de la base): `marcar_abandonadas` la compara con UTC y una
        # base con otro huso horario haría parecer abandonada a una copia recién creada.
        copia = CopiaSeguridad(
            usuario_id=usuario_id, estado="en_proceso", creado_en=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        )
        db.add(copia)
        db.flush()
        return copia

    def marcar_abandonadas(self, db: Session, creadas_antes_de: dt.datetime) -> int:
        """Una copia `en_proceso` de hace mucho es de un proceso que murió: se marca fallida para liberar el candado."""
        resultado = db.execute(
            update(CopiaSeguridad)
            .where(CopiaSeguridad.estado == "en_proceso", CopiaSeguridad.creado_en < creadas_antes_de)
            .values(estado="fallida", motivo_fallo="abandonada", terminado_en=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))
        )
        return resultado.rowcount or 0

    def cargar(self, db: Session, copia_id: int) -> CopiaSeguridad | None:
        return db.scalar(select(CopiaSeguridad).where(CopiaSeguridad.id == copia_id))

    def obtener(self, db: Session, copia_id: int) -> CopiaSeguridad | None:
        """Solo si sigue en el historial visible."""
        return db.scalar(select(CopiaSeguridad).where(CopiaSeguridad.id == copia_id, CopiaSeguridad.activo.is_(True)))

    def completar(
        self, db: Session, copia: CopiaSeguridad, *, tamano_bytes: int, tablas: dict[str, int], version_esquema: str | None, checksum: str
    ) -> CopiaSeguridad:
        copia.estado = "completada"
        copia.tamano_bytes = tamano_bytes
        copia.tablas_incluidas = tablas
        copia.version_esquema = version_esquema
        copia.checksum = checksum
        copia.motivo_fallo = None
        copia.terminado_en = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        db.flush()
        return copia

    def fallar(self, db: Session, copia: CopiaSeguridad, motivo: str) -> CopiaSeguridad:
        copia.estado = "fallida"
        copia.motivo_fallo = motivo[:60]
        copia.terminado_en = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        db.flush()
        return copia

    def listar(self, db: Session, paginacion) -> tuple[list[CopiaSeguridad], int]:
        """El historial visible, la más reciente primero."""
        visibles = CopiaSeguridad.activo.is_(True)
        total = db.scalar(select(func.count()).select_from(CopiaSeguridad).where(visibles)) or 0
        filas = db.scalars(
            select(CopiaSeguridad)
            .where(visibles)
            .order_by(CopiaSeguridad.creado_en.desc(), CopiaSeguridad.id.desc())
            .offset(paginacion.offset)
            .limit(paginacion.tamanio)
        )
        return list(filas), total

    def purgar_antiguas(self, db: Session, mantener: int) -> list[int]:
        """Deja en el historial visible las `mantener` más recientes que ya terminaron y marca el resto como no activas
        (sin borrar nada). Devuelve los ids que salieron."""
        ids = list(
            db.scalars(
                select(CopiaSeguridad.id)
                .where(CopiaSeguridad.activo.is_(True), CopiaSeguridad.estado != "en_proceso")
                .order_by(CopiaSeguridad.creado_en.desc(), CopiaSeguridad.id.desc())
                .offset(max(mantener, 0))
            )
        )
        if ids:
            db.execute(update(CopiaSeguridad).where(CopiaSeguridad.id.in_(ids)).values(activo=False))
        return ids

    def nombres_de_usuarios(self, db: Session, usuario_ids) -> dict[int, str]:
        """Quién pidió cada copia. Los usuarios son de la misma empresa: el filtro automático alcanza."""
        ids = {i for i in usuario_ids if i is not None}
        if not ids:
            return {}
        filas = db.execute(select(Usuario.id, Usuario.nombre, Usuario.apellido).where(Usuario.id.in_(ids)))
        return {fila.id: f"{fila.nombre} {fila.apellido}" for fila in filas}
