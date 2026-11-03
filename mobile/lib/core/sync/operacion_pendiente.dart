/// Los estados de una operación hecha sin conexión (D13). El nombre de cable es el que guarda la base y el que usa el servidor.
///
/// Transiciones válidas: registrada → enviada → {confirmada, rechazada, en_conflicto}; enviada → registrada (si nunca llegó al
/// servidor); en_conflicto → {confirmada, rechazada} (lo resuelve un encargado). Desde confirmada o rechazada NUNCA se vuelve.
enum EstadoOperacion {
  registrada('registrada'),
  enviada('enviada'),
  confirmada('confirmada'),
  rechazada('rechazada'),
  enConflicto('en_conflicto');

  const EstadoOperacion(this.nombre);

  final String nombre;

  static EstadoOperacion? desdeNombre(String? nombre) {
    for (final estado in values) {
      if (estado.nombre == nombre) return estado;
    }
    return null;
  }

  /// confirmada y rechazada son finales.
  bool get esFinal => this == confirmada || this == rechazada;

  /// Las que aún hay que enviar (o reenviar: una 'enviada' pudo no llegar).
  bool get seEnvia => this == registrada || this == enviada;

  /// Las que todavía requieren algo de la persona o del servidor: no terminaron.
  bool get estaPendiente => !esFinal;

  bool puedePasarA(EstadoOperacion destino) => switch (this) {
    registrada => destino == enviada,
    enviada => destino == registrada || destino == confirmada || destino == rechazada || destino == enConflicto,
    enConflicto => destino == confirmada || destino == rechazada,
    confirmada || rechazada => false,
  };
}

enum TipoOperacion {
  ventaContado('venta_contado'),
  reserva('reserva');

  const TipoOperacion(this.nombre);

  final String nombre;

  static TipoOperacion? desdeNombre(String? nombre) {
    for (final tipo in values) {
      if (tipo.nombre == nombre) return tipo;
    }
    return null;
  }
}

/// Una fila de `operacion_pendiente`: la operación tal como se guardó y se va a enviar.
class OperacionPendiente {
  const OperacionPendiente({
    required this.operacionId,
    required this.empresaId,
    required this.sucursalId,
    required this.usuarioId,
    required this.tipo,
    required this.estado,
    required this.payload,
    required this.versionContrato,
    required this.intentos,
    required this.fechaOperacion,
    required this.creadaEn,
    this.ultimoError,
    this.proximoReintentoEn,
    this.resueltaEn,
  });

  /// UUID v4 generado en el teléfono: es la llave de idempotencia (D12).
  final String operacionId;
  final int empresaId;
  final int sucursalId;
  final int usuarioId;
  final TipoOperacion tipo;
  final EstadoOperacion estado;

  /// El sobre JSON que se envía, ya armado e inmutable: reenviarlo es idéntico.
  final String payload;
  final int versionContrato;
  final int intentos;
  final String? ultimoError;
  final DateTime? proximoReintentoEn;

  /// Cuándo OCURRIÓ la operación (hora del teléfono, UTC): el servidor las procesa en este orden (D14).
  final DateTime fechaOperacion;
  final DateTime creadaEn;

  /// Cuándo la confirmó o rechazó el SERVIDOR (su hora, no la del teléfono).
  final DateTime? resueltaEn;

  /// Los primeros 8 caracteres: lo que se muestra y se dicta por teléfono.
  String get codigoCorto => operacionId.length <= 8 ? operacionId : operacionId.substring(0, 8);
}

/// Una fila de `resultado_sync`: una respuesta del servidor a una operación (cada reenvío agrega una).
class ResultadoLocal {
  const ResultadoLocal({
    required this.operacionId,
    required this.recibidoEn,
    required this.estadoResultado,
    this.codigoMotivo,
    this.motivo,
    this.entidadServidorId,
    this.detalleJson,
  });

  final String operacionId;
  final DateTime recibidoEn;
  final String estadoResultado;
  final String? codigoMotivo;
  final String? motivo;
  final int? entidadServidorId;
  final String? detalleJson;
}
