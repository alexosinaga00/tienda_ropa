/// Qué le pasa a una operación y qué hacer, en lenguaje de vendedor. UN solo archivo: la pantalla de resultado y la lista de
/// pendientes leen de aquí. Los códigos son los que manda el servidor en el campo `motivo` (backend/sincronizacion/politicas.py).
class MotivoSync {
  const MotivoSync({required this.titulo, required this.quePaso, required this.queHacer});

  final String titulo;
  final String quePaso;
  final String queHacer;
}

const _contactaAdministrador = 'Contacta al administrador de tu empresa. Esta operación no se ha perdido en tu teléfono.';

const _motivos = <String, MotivoSync>{
  'stock_insuficiente': MotivoSync(
    titulo: 'Falta stock',
    quePaso: 'El servidor no tenía stock suficiente de alguna prenda.',
    queHacer:
        'Avisa a tu encargado de sucursal: él revisará esta operación. Si el cliente ya se llevó la prenda, puede aprobarla.',
  ),
  'variante_inactiva': MotivoSync(
    titulo: 'Prenda dada de baja',
    quePaso: 'Una de las prendas ya no está en el catálogo.',
    queHacer: 'Avisa al encargado y actualiza tus datos con "Actualizar datos".',
  ),
  'variante_inexistente': MotivoSync(
    titulo: 'Prenda desconocida',
    quePaso: 'El servidor no conoce una de las prendas de esta operación.',
    queHacer: 'Actualiza tus datos con "Actualizar datos" y avisa al encargado.',
  ),
  'cliente_inexistente': MotivoSync(
    titulo: 'Cliente desconocido',
    quePaso: 'El servidor no encontró al cliente de esta operación.',
    queHacer: 'Actualiza tus datos y elige al cliente de nuevo. Si sigue igual, avisa al encargado.',
  ),
  'sucursal_no_autorizada': MotivoSync(
    titulo: 'Sucursal no autorizada',
    quePaso: 'No tienes autorización para operar en esa sucursal.',
    queHacer: 'Pide acceso al administrador de tu empresa.',
  ),
  'sucursal_inexistente': MotivoSync(
    titulo: 'Sucursal no encontrada',
    quePaso: 'El servidor no encontró la sucursal de esta operación.',
    queHacer: 'Actualiza tus datos con "Actualizar datos" y avisa al encargado.',
  ),
  'usuario_no_es_empleado': MotivoSync(
    titulo: 'Cuenta sin permiso',
    quePaso: 'Tu cuenta no es de personal de la sucursal.',
    queHacer: 'Pide acceso al administrador de tu empresa.',
  ),
  'suscripcion_no_activa': MotivoSync(
    titulo: 'Suscripción no activa',
    quePaso: 'La suscripción de tu empresa no está activa ahora.',
    queHacer: _contactaAdministrador,
  ),
  'plan_sin_operacion_offline': MotivoSync(
    titulo: 'Tu plan no incluye esta función',
    quePaso: 'El plan de tu empresa no permite operar sin conexión.',
    queHacer: _contactaAdministrador,
  ),
  'total_inconsistente': MotivoSync(
    titulo: 'El total no cuadra',
    quePaso: 'El total de la venta no coincide con la suma de sus prendas.',
    queHacer: 'Vuelve a registrar la venta y avisa a soporte con el código de la operación.',
  ),
  'total_invalido': MotivoSync(
    titulo: 'Total no válido',
    quePaso: 'El total de la venta no es válido.',
    queHacer: 'Vuelve a registrar la venta y avisa a soporte con el código de la operación.',
  ),
  'metodo_pago_no_permitido': MotivoSync(
    titulo: 'Forma de pago no permitida',
    quePaso: 'Sin conexión solo se aceptan ventas en efectivo.',
    queHacer: 'Cobra en efectivo o registra la venta cuando tengas conexión.',
  ),
  'monto_insuficiente': MotivoSync(
    titulo: 'Efectivo insuficiente',
    quePaso: 'El efectivo recibido no cubre el total.',
    queHacer: 'Vuelve a registrar la venta con el monto correcto.',
  ),
  'fecha_futura': MotivoSync(
    titulo: 'Fecha del teléfono incorrecta',
    quePaso: 'La fecha de esta operación es posterior a la hora del servidor.',
    queHacer: 'Revisa la fecha y la hora de tu teléfono y registra la operación de nuevo.',
  ),
  'reserva_fuera_de_horario': MotivoSync(
    titulo: 'Fuera de horario',
    quePaso: 'La visita está fuera del horario de la sucursal.',
    queHacer: 'Registra otra reserva dentro del horario de atención y avisa al cliente.',
  ),
  'reserva_vencida': MotivoSync(
    titulo: 'Reserva vencida',
    quePaso: 'La fecha de la visita ya pasó cuando el servidor la recibió.',
    queHacer: 'Registra una nueva reserva con una fecha vigente y avisa al cliente.',
  ),
  'permiso_denegado': MotivoSync(
    titulo: 'Sin permiso',
    quePaso: 'Tu cuenta no tiene permiso para este tipo de operación.',
    queHacer: 'Pide el permiso al administrador de tu empresa.',
  ),
  'operador_inactivo': MotivoSync(
    titulo: 'Cuenta inactiva',
    quePaso: 'La cuenta que registró esta operación ya no está activa.',
    queHacer: 'Avisa al administrador de tu empresa.',
  ),
  'rechazada_por_encargado': MotivoSync(
    titulo: 'Rechazada por el encargado',
    quePaso: 'Un encargado de sucursal revisó esta operación y la rechazó.',
    queHacer:
        'Habla con tu encargado para conocer el motivo. Si ya cobraste en tienda, la devolución del efectivo se hace fuera del sistema.',
  ),
  'regla_de_negocio': MotivoSync(
    titulo: 'No cumple una regla',
    quePaso: 'El servidor rechazó esta operación porque no cumple una regla de la empresa.',
    queHacer: 'Lee el detalle que muestra el servidor y consulta con tu encargado. Dile el código de la operación.',
  ),
  'payload_invalido': MotivoSync(
    titulo: 'Datos no válidos',
    quePaso: 'El servidor no entendió los datos de esta operación.',
    queHacer: 'Vuelve a registrar la operación y avisa a soporte con el código.',
  ),
  'tipo_no_soportado': MotivoSync(
    titulo: 'Operación no soportada',
    quePaso: 'El servidor no reconoce este tipo de operación.',
    queHacer: 'Actualiza la app. Si sigue igual, avisa a soporte con el código.',
  ),
};

const _desconocido = MotivoSync(
  titulo: 'Operación no aceptada',
  quePaso: 'El servidor no pudo aceptar esta operación.',
  queHacer: 'Consulta con tu encargado y dile el código de la operación.',
);

/// El texto para un código de motivo. Un código desconocido usa [mensajeServidor] como "qué pasó" (si lo hay) y el "qué hacer"
/// genérico.
MotivoSync motivoDe(String? codigo, {String? mensajeServidor}) {
  final conocido = codigo == null ? null : _motivos[codigo];
  if (conocido != null) return conocido;
  final texto = mensajeServidor?.trim();
  if (texto == null || texto.isEmpty) return _desconocido;
  return MotivoSync(titulo: _desconocido.titulo, quePaso: texto, queHacer: _desconocido.queHacer);
}

/// Los códigos que la app conoce (para las pruebas: que ninguno falte).
Iterable<String> get codigosDeMotivoConocidos => _motivos.keys;
