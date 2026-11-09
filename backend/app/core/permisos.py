"""Códigos de permiso (`permiso.codigo`) que el código consulta. Solo
constantes: no importa de ningún paquete. Los seeds (scripts/seed_seguridad.py)
siguen siendo la fuente de qué códigos existen en la base."""

# ---- plataforma ----
# Rol global del administrador de la plataforma: solo lo tienen usuarios sin
# empresa (`usuario.empresa_id` NULL), y ellos no pueden tener otro.
ROL_SUPERADMINISTRADOR = "superadministrador"
# Rol del administrador de cada empresa. Una empresa puede tener varios, pero
# siempre al menos uno activo (D36).
ROL_ADMINISTRADOR = "administrador"
PERMISO_USUARIOS = "usuarios.gestionar"
PERMISO_ROLES = "roles.gestionar"
# Acceso a los endpoints de organización (ciudades, sucursales, empleados).
PERMISO_ORGANIZACION = "organizacion.gestionar"
# Quién opera todas las sucursales y no solo la suya. Hoy comparte el código
# con PERMISO_ORGANIZACION (no hace falta correr seeds), pero es otra
# decisión: con multitenant pasa a "alcance dentro de la empresa" y puede
# separarse. Por eso son dos constantes y no una.
PERMISO_ALCANCE_GLOBAL = "organizacion.gestionar"
# Multitenant: PERMISO_PLATAFORMA es solo del superadministrador (empresas,
# planes y suscripciones de toda la plataforma); PERMISO_EMPRESA lo tiene el
# administrador de cada empresa para gestionar la suya.
PERMISO_PLATAFORMA = "plataforma.gestionar"
PERMISO_EMPRESA = "empresa.gestionar"
# Consultar la bitácora de auditoría de la propia empresa (administrador).
PERMISO_BITACORA_VER = "bitacora.ver"
# Crear y descargar la copia de seguridad de la propia empresa (solo el administrador; plan con `copias_seguridad`).
PERMISO_COPIAS = "copias.gestionar"

# ---- sincronizacion ----
# Enviar operaciones hechas sin conexión y consultar las propias.
PERMISO_SINCRONIZAR = "sincronizacion.operar"
# Ver las operaciones de toda la empresa (o de la sucursal propia) y su payload.
PERMISO_SINCRONIZACION_SUPERVISAR = "sincronizacion.supervisar"
# Resolver una operación en conflicto: forzarla (con ajuste de inventario) o rechazarla.
PERMISO_SINCRONIZACION_RESOLVER = "sincronizacion.resolver"

# ---- catalogo ----
PERMISO_CATALOGO = "catalogo.gestionar"
PERMISO_CATALOGO_VER = "catalogo.ver"
PERMISO_INVENTARIO_VER = "inventario.ver"
PERMISO_INVENTARIO_GESTIONAR = "inventario.gestionar"
PERMISO_ABASTECIMIENTO = "abastecimiento.gestionar"
PERMISO_PROBADOR = "probador.gestionar"

# ---- comercial ----
PERMISO_RESERVAS_CREAR = "reservas.crear"
PERMISO_STAFF_RESERVAS = "reservas.gestionar_sucursal"
PERMISO_VENTAS_DIGITAL = "ventas.digital"
PERMISO_VENTAS_PRESENCIAL = "ventas.presencial"
PERMISO_STAFF_VENTAS = "ventas.gestionar_sucursal"
PERMISO_VENTAS_GESTIONAR = "ventas.gestionar"
PERMISO_PAGOS = "pagos.gestionar"
# Supervisar la caja: ver los turnos y sus cierres (el esperado incluido), cerrar el turno de otra persona y completar el
# conteo de uno cerrado automáticamente. Lo tienen el encargado de sucursal y el administrador. Abrir y cerrar el propio
# turno usa PERMISO_VENTAS_PRESENCIAL.
PERMISO_CAJA_SUPERVISAR = "caja.supervisar"
PERMISO_ENTREGAS = "entregas.gestionar"

# ---- inteligencia ----
PERMISO_REPORTES_VER = "reportes.ver"
