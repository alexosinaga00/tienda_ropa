"""CU-01 — Autenticar y registrar usuarios

Absorbe los antiguos CU-01 (Registrar cliente), CU-02 (Iniciar sesión) y
CU-35 (Recuperar contraseña).

Actor: Cliente, Administrador, Encargado de sucursal, Cajero, Proveedor.
Precondición: ninguna (accesible sin sesión) para el alta, el inicio de
sesión y la recuperación de contraseña; sesión propia para consultar o editar
el perfil. Para iniciar sesión, el usuario existe y está activo.
Postcondición: existe un usuario con rol cliente y su perfil (Cliente) en la
empresa de la tienda; se emiten access_token y refresh_token con los roles y
permisos vigentes y la empresa del usuario (claim `empresa_id`, null para el
superadministrador); si el email está registrado en esa empresa se emite un
token de recuperación de un solo uso y, al confirmarlo con una contraseña
nueva, el hash se actualiza.

Caso de uso COMPUESTO: agrupa el alta del cliente (y la gestión de su propio
perfil), el inicio de sesión (con el refresco del token), la recuperación de
contraseña y el registro del dispositivo que recibe las notificaciones push de
la sesión (`GestionarDispositivosPush`). Cada clase es un controlador del caso
de uso."""

import datetime as dt
import hmac
import logging
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auditoria import (
    ACCION_CONTRASENA_RESTABLECIDA,
    ACCION_LOGIN_EXITOSO,
    ACCION_LOGIN_FALLIDO,
    ACCION_QUITAR,
    ACCION_REGISTRAR,
    ENTIDAD_DISPOSITIVO_PUSH,
    ENTIDAD_SESION,
    ENTIDAD_USUARIO,
    ContextoAuditoria,
)
from app.core.config import get_settings
from app.core.exceptions import DemasiadosIntentosError, NoAutenticadoError
from app.core.correo import MensajeCorreo, enviar_correo_sin_romper, envio_configurado
from app.core.rate_limit import limitador_dispositivos_push, limitador_intentos, limitador_recuperacion
from app.core.tiempo import ahora_utc_naive
from app.core.tenant import fijar_empresa, fijar_empresa_de_usuario
from app.core.security import (
    crear_access_token,
    crear_refresh_token,
    crear_reset_token,
    decodificar_token,
    huella_de_password,
    usuario_id_de_payload,
    verificar_password,
)
from app.plataforma.models import Cliente, Usuario
from app.plataforma.politicas import (
    ROL_CLIENTE,
    construir_correo_recuperacion,
    enlace_de_recuperacion,
    es_solo_cliente,
    identidad_del_token_valida,
    normalizar_nombre_empresa,
    obtener_empresa,
    obtener_empresa_por_codigo,
    obtener_perfil_cliente,
    obtener_usuario_para_auth,
    permisos_de_usuario,
    registrar_bitacora,
    registrar_bitacora_de,
)
from app.plataforma.repository import ClienteRepository, DispositivoPushRepository, UsuarioRepository
from app.plataforma.schemas import (
    ClientePerfilActualizar,
    DispositivoPushQuitar,
    DispositivoPushRegistrar,
    LoginRequest,
    RegistroRequest,
    TokenRespuesta,
    UsuarioCrear,
)

logger = logging.getLogger(__name__)

# Hash bcrypt fijo (de un password que no le pertenece a nadie) para que
# ejecutar() siempre corra verificar_password() con costo real, exista o no
# el email: sin esto, el cortocircuito de `or` se salta bcrypt.checkpw()
# cuando el usuario no existe, y ese ida-y-vuelta más rápido deja adivinar
# por tiempo de respuesta qué emails están registrados.
_HASH_DUMMY = "$2b$12$d1ru1mgPSWsBsc/AHIyMHeWrDeAVeESRlnXjY52JXjnR/XOLoWB22"


# ---- Registrar cliente (antiguo CU-01: Registrar cliente) ----


class RegistrarCliente:
    def __init__(self) -> None:
        self._usuarios = UsuarioRepository()
        self._clientes = ClienteRepository()

    def registrar(self, db: Session, datos: RegistroRequest) -> Usuario:
        # Usuario + rol + perfil de cliente son UNA unidad de trabajo: un solo
        # commit al final. Si falta el rol "cliente" (o cualquier paso falla)
        # se revierte todo, sin dejar un usuario huérfano sin perfil ni rol.
        try:
            usuario = self._usuarios.crear(
                db,
                UsuarioCrear(
                    nombre=datos.nombre,
                    apellido=datos.apellido,
                    email=datos.email,
                    telefono=datos.telefono,
                    password=datos.password,
                ),
                commit=False,
            )
            self._usuarios.asignar_roles(db, usuario, [ROL_CLIENTE], commit=False)
            self._clientes.crear_o_actualizar_perfil(db, usuario.id, datos.ci_nit, commit=False)
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(usuario)
        return usuario

    def obtener_perfil(self, db: Session, usuario_id: int) -> Cliente:
        return obtener_perfil_cliente(db, usuario_id)

    def actualizar_perfil(
        self, db: Session, usuario_id: int, datos: ClientePerfilActualizar
    ) -> Cliente:
        return self._clientes.actualizar_perfil(db, usuario_id, datos)


# ---- Iniciar sesión (antiguo CU-02: Iniciar sesión) ----

# Clave del bloqueo de las credenciales de plataforma (sin empresa). Lleva un
# asterisco, que un nombre normalizado nunca contiene.
_CLAVE_PLATAFORMA = "*plataforma*"


def _usuario_de_empresa_por_correo(db: Session, usuarios: UsuarioRepository, empresa: str, email: str) -> Usuario | None:
    """El usuario de esa empresa (por nombre o código) con ese correo, o None
    si la empresa no existe, está inactiva o el correo no es suyo. Deja la
    sesión trabajando en esa empresa solo si existe y está activa."""
    return _buscar_en_empresa(db, usuarios, empresa, email)[1]


def _buscar_en_empresa(
    db: Session, usuarios: UsuarioRepository, empresa: str, email: str
) -> tuple[bool, Usuario | None]:
    """(la empresa existe y está activa, el usuario con ese correo en ella). El
    primer valor deja distinguir "empresa inexistente" de "correo ajeno" en la
    bitácora sin cambiar lo que ve quien llama al endpoint."""
    codigo = normalizar_nombre_empresa(empresa)
    if not codigo:
        return False, None
    registro = obtener_empresa_por_codigo(db, codigo)
    if registro is None or not registro.activo:
        return False, None
    fijar_empresa(db, registro.id)
    return True, usuarios.obtener_por_email(db, email)


class IniciarSesion:
    """Incluye también refrescar el token (mismo flujo de autenticación, no un
    CU aparte del catálogo)."""

    def __init__(self) -> None:
        self._usuarios = UsuarioRepository()

    def _emitir_tokens(self, db: Session, usuario: Usuario) -> TokenRespuesta:
        roles = [r.nombre for r in usuario.roles]
        permisos = permisos_de_usuario(db, usuario.id)
        return TokenRespuesta(
            access_token=crear_access_token(usuario.id, roles, permisos, empresa_id=usuario.empresa_id),
            refresh_token=crear_refresh_token(usuario.id, empresa_id=usuario.empresa_id),
        )

    def ejecutar(
        self, db: Session, datos: LoginRequest, contexto: ContextoAuditoria | None = None
    ) -> TokenRespuesta:
        # La clave del bloqueo no depende de que la cuenta exista: bloquear no
        # revela nada. Una empresa que normaliza a vacío cuenta como cualquier
        # otro intento fallido.
        codigo = None if datos.empresa is None else normalizar_nombre_empresa(datos.empresa)
        clave = f"{_CLAVE_PLATAFORMA if codigo is None else codigo}|{datos.email}"
        reintentar_en = limitador_intentos.bloqueado(clave)
        if reintentar_en is not None:
            # Un bloqueo no es un intento nuevo: no deja fila (el intento que lo
            # provocó ya la dejó).
            raise DemasiadosIntentosError(reintentar_en)

        empresa_valida = True
        if datos.empresa is None:
            # Sin empresa: solo un superadministrador entra por aquí; un
            # usuario de empresa NUNCA, aunque su clave sea correcta.
            usuario = self._usuarios.obtener_de_plataforma_por_email(db, datos.email)
        else:
            empresa_valida, usuario = _buscar_en_empresa(db, self._usuarios, datos.empresa, datos.email)

        # bcrypt SIEMPRE, con el mismo costo exista o no el usuario: sin esto el
        # tiempo de respuesta delataría qué empresas y correos existen.
        hash_a_verificar = usuario.password_hash if usuario is not None else _HASH_DUMMY
        password_valida = verificar_password(datos.password, hash_a_verificar)
        if usuario is None or not usuario.activo or not password_valida:
            limitador_intentos.registrar_fallo(clave)
            self._anotar_fallo(db, contexto, usuario, empresa_valida)
            raise NoAutenticadoError("Credenciales inválidas")

        limitador_intentos.limpiar(clave)
        # Desde acá la sesión trabaja en la empresa del usuario (o en modo
        # plataforma, si es superadministrador).
        fijar_empresa_de_usuario(db, usuario)
        tokens = self._emitir_tokens(db, usuario)
        usuario.ultimo_acceso = dt.datetime.now(dt.timezone.utc)
        if contexto is not None:
            registrar_bitacora(db, usuario.id, ENTIDAD_SESION, usuario.id, ACCION_LOGIN_EXITOSO, {}, contexto.ip)
        db.commit()
        return tokens

    @staticmethod
    def _anotar_fallo(
        db: Session, contexto: ContextoAuditoria | None, usuario: Usuario | None, empresa_valida: bool
    ) -> None:
        """Deja la fila del intento fallido y la CONFIRMA en el acto: el
        endpoint responde 401 y `get_db` revertiría cualquier cosa pendiente. Es
        el único evento de la bitácora que se confirma solo. Nunca guarda el
        correo ni la contraseña: solo el motivo."""
        if contexto is None:
            return
        if not empresa_valida:
            motivo = "empresa_inexistente"
        elif usuario is not None and not usuario.activo:
            motivo = "usuario_inactivo"
        else:
            motivo = "credenciales"
        usuario_id = usuario.id if usuario is not None else None
        registrar_bitacora(
            db, usuario_id, ENTIDAD_SESION, usuario_id, ACCION_LOGIN_FALLIDO, {"motivo": motivo}, contexto.ip
        )
        db.commit()

    def refrescar(self, db: Session, refresh_token: str) -> TokenRespuesta:
        payload = decodificar_token(refresh_token, tipo="refresh")
        usuario_id = usuario_id_de_payload(payload)
        if usuario_id is None:
            raise NoAutenticadoError("Token inválido")

        usuario = obtener_usuario_para_auth(db, usuario_id)
        if usuario is None:
            raise NoAutenticadoError("Usuario inválido")
        if not identidad_del_token_valida(db, payload, usuario):
            raise NoAutenticadoError("Token inválido")

        fijar_empresa_de_usuario(db, usuario)
        return self._emitir_tokens(db, usuario)


# ---- Recuperar contraseña (antiguo CU-35: Recuperar contraseña) ----


class RecuperarContrasena:
    def __init__(self) -> None:
        self._usuarios = UsuarioRepository()

    def solicitar(
        self,
        db: Session,
        empresa: str | None,
        email: str,
        programar_envio: Callable[[Callable[[MensajeCorreo], object], MensajeCorreo], object] | None = None,
    ) -> str | None:
        """Genera un token de recuperación si el email existe en esa empresa y le manda el enlace por correo (Brevo).

        El correo NO sale dentro de la petición: `programar_envio(funcion, mensaje)` lo deja para después de
        responder (el router pasa `BackgroundTasks.add_task`), así la respuesta tarda igual exista o no el correo y
        no se puede adivinar por el tiempo. Sin `programar_envio` se envía en el acto. Un fallo del envío no cambia
        nada para quien llama (queda una línea en el log sin el correo ni el token).

        El token también se devuelve para que el router lo incluya en la respuesta SOLO en entorno local (ver
        `RecuperarRespuesta.token_dev`) y se deja en el log local para pruebas manuales. La respuesta al cliente es
        siempre genérica (ver router) para no revelar si la empresa o el email existen. Sin empresa
        (superadministrador) no se emite token: su contraseña solo se cambia con
        scripts/crear_superadmin.py --restablecer.

        Límite por cuenta (`recuperar_max_solicitudes` por `recuperar_ventana_segundos`): cuenta TODAS las
        solicitudes, exista o no la cuenta; pasado el máximo no hay token ni correo y la respuesta es la misma.
        """
        if empresa is None:
            return None
        usuario = _usuario_de_empresa_por_correo(db, self._usuarios, empresa, email)

        clave = f"{normalizar_nombre_empresa(empresa)}|{email}"
        if limitador_recuperacion.bloqueado(clave) is not None:
            return None
        limitador_recuperacion.registrar_fallo(clave)  # cuenta la solicitud (aquí "fallo" = intento a limitar)

        if usuario is None or not usuario.activo:
            return None

        token = crear_reset_token(usuario.id, empresa_id=usuario.empresa_id, password_hash=usuario.password_hash)
        if get_settings().environment == "local":  # mismo criterio que token_dev en el router
            logger.info("Token de recuperación para %s: %s", email, token)

        registro = obtener_empresa(db, usuario.empresa_id) if usuario.empresa_id is not None else None
        if registro is not None and envio_configurado():
            mensaje = construir_correo_recuperacion(
                para_email=usuario.email,
                nombre=usuario.nombre,
                nombre_empresa=registro.nombre,
                enlace=enlace_de_recuperacion(registro.codigo, token, es_cliente=es_solo_cliente(usuario)),
            )
            if programar_envio is None:
                enviar_correo_sin_romper(mensaje)
            else:
                programar_envio(enviar_correo_sin_romper, mensaje)
        return token

    def confirmar(self, db: Session, token: str, password: str, contexto: ContextoAuditoria | None = None) -> None:
        payload = decodificar_token(token, tipo="reset")
        usuario_id = usuario_id_de_payload(payload)
        usuario = obtener_usuario_para_auth(db, usuario_id) if usuario_id is not None else None
        # El superadministrador (sin empresa) no recupera su clave por aquí.
        if usuario is None or usuario.empresa_id is None or not identidad_del_token_valida(db, payload, usuario):
            raise NoAutenticadoError("Token inválido")
        # Un solo uso: el token lleva la huella del hash vigente, y al cambiar
        # la contraseña el hash cambia.
        huella = payload.get("ph")
        if not isinstance(huella, str) or not hmac.compare_digest(huella, huella_de_password(usuario.password_hash)):
            raise NoAutenticadoError("Token inválido")

        fijar_empresa_de_usuario(db, usuario)
        self._usuarios.actualizar_password(db, usuario, password, commit=False)
        if contexto is not None:  # el actor es el propio usuario: el contexto es anónimo (solo trae la IP)
            registrar_bitacora(
                db, usuario.id, ENTIDAD_USUARIO, usuario.id, ACCION_CONTRASENA_RESTABLECIDA, {}, contexto.ip
            )
        db.commit()


# ---- Dispositivos de notificaciones push (parte de la sesión del usuario en la app) ----


class GestionarDispositivosPush:
    """Registrar y quitar el teléfono que recibe las notificaciones push (token de FCM) de la sesión de la app.

    Cualquier usuario autenticado gestiona SUS dispositivos; no hay permiso ni plan de por medio. Un token pertenece a
    UN usuario: si otro inicia sesión en el mismo teléfono, el registro se reasigna al nuevo. Ambas operaciones son
    idempotentes y la baja no revela nada (un token ajeno o inexistente responde igual que uno propio). Cada usuario
    conserva como máximo `push_max_dispositivos_por_usuario` dispositivos activos: al pasar, se desactiva el más antiguo.
    Por qué aquí y no en un CU nuevo: es parte de la sesión que CU-01 abre. El ENVÍO vive en
    `plataforma.politicas.crear_notificacion` (cada notificación nueva programa su push) y en `core/push.py`."""

    def __init__(self) -> None:
        self._dispositivos = DispositivoPushRepository()

    @staticmethod
    def _contar_peticion(usuario_id: int) -> None:
        clave = str(usuario_id)
        espera = limitador_dispositivos_push.bloqueado(clave)
        if espera is not None:
            raise DemasiadosIntentosError(espera, "Registraste dispositivos muchas veces. Intenta más tarde.")
        limitador_dispositivos_push.registrar_fallo(clave)  # cuenta cada alta y cada baja (no son "fallos")

    def registrar(
        self,
        db: Session,
        usuario_id: int,
        datos: DispositivoPushRegistrar,
        contexto: ContextoAuditoria | None = None,
    ) -> None:
        self._contar_peticion(usuario_id)
        ahora = ahora_utc_naive()
        dispositivo = self._dispositivos.obtener_por_token(db, datos.token)
        nuevo = False
        if dispositivo is None:
            try:
                with db.begin_nested():  # un alta simultánea del mismo token choca con el UNIQUE sin tumbar la sesión
                    dispositivo = self._dispositivos.crear(db, usuario_id, datos.token, datos.plataforma)
                nuevo = True
            except IntegrityError:
                dispositivo = self._dispositivos.obtener_por_token(db, datos.token)
                if dispositivo is None:
                    raise
        reasignado = reactivado = False
        if not nuevo:
            reasignado = dispositivo.usuario_id != usuario_id
            reactivado = not dispositivo.activo
            dispositivo.usuario_id = usuario_id
            dispositivo.activo = True
            dispositivo.plataforma = datos.plataforma
            dispositivo.actualizado_en = ahora  # último uso: ordena cuál es "el más antiguo"
        db.flush()  # sin esto la consulta del límite no vería el dispositivo reactivado o reasignado
        self._respetar_limite(db, usuario_id, conservar_id=dispositivo.id, ahora=ahora)
        if nuevo or reasignado or reactivado:  # repetir el alta de un token ya activo no deja huella
            registrar_bitacora_de(
                db,
                contexto,
                ENTIDAD_DISPOSITIVO_PUSH,
                dispositivo.id,
                ACCION_REGISTRAR,
                {"plataforma": datos.plataforma, "reasignado": reasignado, "reactivado": reactivado},
            )
        db.commit()

    def quitar(
        self,
        db: Session,
        usuario_id: int,
        datos: DispositivoPushQuitar,
        contexto: ContextoAuditoria | None = None,
    ) -> None:
        """Solo desactiva un token que sea del usuario actual y siga activo; en cualquier otro caso no hace nada."""
        self._contar_peticion(usuario_id)
        dispositivo = self._dispositivos.obtener_por_token(db, datos.token)
        if dispositivo is None or dispositivo.usuario_id != usuario_id or not dispositivo.activo:
            return
        dispositivo.activo = False
        dispositivo.actualizado_en = ahora_utc_naive()
        registrar_bitacora_de(db, contexto, ENTIDAD_DISPOSITIVO_PUSH, dispositivo.id, ACCION_QUITAR, {})
        db.commit()

    def _respetar_limite(self, db: Session, usuario_id: int, *, conservar_id: int, ahora: dt.datetime) -> None:
        maximo = max(get_settings().push_max_dispositivos_por_usuario, 1)
        activos = self._dispositivos.listar_activos(db, usuario_id)
        for sobrante in [d for d in activos if d.id != conservar_id][: max(len(activos) - maximo, 0)]:
            sobrante.activo = False  # el más antiguo (por último uso) primero
            sobrante.actualizado_en = ahora
