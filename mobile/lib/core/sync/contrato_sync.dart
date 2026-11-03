import 'dart:convert';

import '../../features/vendedor/models/paquete_sincronizacion.dart';
import '../utils/dinero.dart';
import 'lineas_operacion.dart';
import 'operacion_pendiente.dart';

/// El contrato JSON del lote (POST /api/v1/sincronizacion/lote), igual que el de la PWA. Montos como TEXTO decimal con 2
/// decimales ("75.00"); fechas con zona (UTC, "Z"). La empresa y el usuario NO viajan: el servidor los toma del token.
const versionContratoSync = '1.0';

/// El servidor admite hasta 50 por lote; el teléfono manda 20 para que una respuesta lenta no pierda tanto trabajo.
const tamanioLoteSync = 20;

// ---- Entrada ----------------------------------------------------------------------------

/// Una operación lista para enviar. Su [payload] es el sobre inmutable que se guardó al registrarla.
class OperacionEnvio {
  const OperacionEnvio({
    required this.operacionId,
    required this.tipo,
    required this.sucursalId,
    required this.fechaOperacion,
    required this.payload,
  });

  /// Arma el envío a partir de la fila guardada (el payload se manda tal cual, sin recalcular nada).
  factory OperacionEnvio.desde(OperacionPendiente operacion) => OperacionEnvio(
    operacionId: operacion.operacionId,
    tipo: operacion.tipo,
    sucursalId: operacion.sucursalId,
    fechaOperacion: operacion.fechaOperacion,
    payload: Map<String, dynamic>.from(jsonDecode(operacion.payload) as Map),
  );

  final String operacionId;
  final TipoOperacion tipo;
  final int sucursalId;
  final DateTime fechaOperacion;
  final Map<String, dynamic> payload;

  Map<String, dynamic> toJson() => {
    'operacion_id': operacionId,
    'tipo': tipo.nombre,
    'sucursal_id': sucursalId,
    'fecha_operacion': aIsoUtc(fechaOperacion),
    'payload': payload,
  };
}

class LoteEnvio {
  const LoteEnvio({required this.operaciones, this.dispositivo});

  /// Identifica el teléfono (para auditoría). No es un dato personal.
  final String? dispositivo;
  final List<OperacionEnvio> operaciones;

  Map<String, dynamic> toJson() => {
    'version_contrato': versionContratoSync,
    if (dispositivo != null) 'dispositivo': dispositivo,
    'operaciones': [for (final o in operaciones) o.toJson()],
  };
}

/// El payload de una venta de contado. El cliente va por su id del SERVIDOR (sin conexión no se crean clientes).
/// El pago es siempre efectivo y el monto recibido cubre el total.
Map<String, dynamic> payloadVentaContado({
  int? clienteServidorId,
  required List<LineaVenta> lineas,
  required int totalCentavos,
}) => {
  'cliente_id': ?clienteServidorId,
  'lineas': [
    for (final l in lineas)
      {
        'variante_id': l.varianteId,
        'cantidad': l.cantidad,
        'precio_unitario': deCentavos(l.precioUnitarioCentavos),
        'descuento_unitario': deCentavos(l.descuentoUnitarioCentavos),
      },
  ],
  'total': deCentavos(totalCentavos),
  'pago': {'metodo': 'efectivo', 'monto_recibido': deCentavos(totalCentavos)},
};

/// El payload de una reserva: el cliente es OBLIGATORIO y va por su id del servidor.
Map<String, dynamic> payloadReserva({
  required int clienteServidorId,
  required DateTime fechaVisita,
  required String horaDesde,
  required String horaHasta,
  String? observacion,
  required List<LineaReserva> lineas,
}) => {
  'cliente_id': clienteServidorId,
  'fecha_visita': _soloFecha(fechaVisita),
  'hora_visita_desde': horaDesde,
  'hora_visita_hasta': horaHasta,
  if (observacion != null && observacion.trim().isNotEmpty) 'observacion': observacion.trim(),
  'lineas': [
    for (final l in lineas) {'variante_id': l.varianteId, 'cantidad': l.cantidad},
  ],
};

String _soloFecha(DateTime f) {
  String dos(int n) => n.toString().padLeft(2, '0');
  return '${f.year.toString().padLeft(4, '0')}-${dos(f.month)}-${dos(f.day)}';
}

// ---- Salida -----------------------------------------------------------------------------

/// Lo que el servidor dice de UNA operación. `errorTemporal` no se guarda: se reintenta con el mismo id.
enum EstadoResultadoSync {
  confirmada('confirmada'),
  rechazada('rechazada'),
  enConflicto('en_conflicto'),
  errorTemporal('error_temporal'),
  desconocido('');

  const EstadoResultadoSync(this.nombre);

  final String nombre;

  static EstadoResultadoSync desdeNombre(String? nombre) {
    for (final e in values) {
      if (e.nombre == nombre && nombre != null && nombre.isNotEmpty) return e;
    }
    return desconocido;
  }

  /// El estado local que le corresponde, o null si no cambia nada (error temporal o desconocido).
  EstadoOperacion? get aEstadoLocal => switch (this) {
    confirmada => EstadoOperacion.confirmada,
    rechazada => EstadoOperacion.rechazada,
    enConflicto => EstadoOperacion.enConflicto,
    errorTemporal || desconocido => null,
  };
}

class RecursoSync {
  const RecursoSync({required this.tipo, required this.id, required this.codigo, this.totalCentavos});

  /// 'venta' o 'reserva'.
  final String tipo;
  final int id;

  /// El código legible (nº de venta o de reserva) que se le puede dictar al cliente.
  final String codigo;
  final int? totalCentavos;
}

/// "El precio actual era otro": se respetó el que se cobró (D17).
class AvisoPrecioSync {
  const AvisoPrecioSync({required this.varianteId, required this.precioOperacionCentavos, required this.precioActualCentavos});

  final int varianteId;
  final int precioOperacionCentavos;
  final int precioActualCentavos;
}

class FaltanteSync {
  const FaltanteSync({required this.varianteId, required this.solicitado, required this.disponible});

  final int varianteId;
  final int solicitado;
  final int disponible;
}

/// Cómo cerró un encargado un conflicto desde la web (E08).
class ResolucionSync {
  const ResolucionSync({required this.accion, this.motivo});

  /// 'forzar' o 'rechazar'.
  final String accion;
  final String? motivo;
}

/// El resultado de una operación. Sirve para la respuesta del lote y para la consulta de una sola operación
/// (`GET /sincronizacion/operaciones/{id}`), que trae los mismos campos.
class ResultadoOperacionSync {
  const ResultadoOperacionSync({
    required this.operacionId,
    required this.estado,
    this.motivo,
    this.mensaje,
    this.duplicada = false,
    this.procesadaEn,
    this.recurso,
    this.cambioCentavos,
    this.avisos = const [],
    this.faltantes = const [],
    this.resolucion,
  });

  /// Tolerante: campos que faltan quedan en null y un campo nuevo se ignora.
  factory ResultadoOperacionSync.fromJson(Map<String, dynamic> json) {
    int? centavos(Object? v) {
      if (v == null) return null;
      try {
        return aCentavos(v);
      } on FormatException {
        return null;
      }
    }

    List<T> lista<T>(Object? v, T Function(Map<String, dynamic>) f) =>
        v is List ? [for (final e in v) if (e is Map) f(Map<String, dynamic>.from(e))] : <T>[];

    final recurso = json['recurso'];
    final resolucion = json['resolucion'];
    return ResultadoOperacionSync(
      operacionId: (json['operacion_id'] as String? ?? '').toLowerCase(),
      estado: EstadoResultadoSync.desdeNombre(json['estado'] as String?),
      motivo: json['motivo'] as String?,
      mensaje: json['mensaje'] as String?,
      duplicada: json['duplicada'] == true,
      procesadaEn: leerFechaUtc(json['procesada_en']),
      recurso: recurso is Map
          ? RecursoSync(
              tipo: recurso['tipo'] as String? ?? '',
              id: (recurso['id'] as num?)?.toInt() ?? 0,
              codigo: recurso['codigo'] as String? ?? '',
              totalCentavos: centavos(recurso['total']),
            )
          : null,
      cambioCentavos: centavos(json['cambio']),
      avisos: lista(
        json['avisos'],
        (a) => AvisoPrecioSync(
          varianteId: (a['variante_id'] as num?)?.toInt() ?? 0,
          precioOperacionCentavos: centavos(a['precio_operacion']) ?? 0,
          precioActualCentavos: centavos(a['precio_actual']) ?? 0,
        ),
      ),
      faltantes: lista(
        json['faltantes'],
        (f) => FaltanteSync(
          varianteId: (f['variante_id'] as num?)?.toInt() ?? 0,
          solicitado: (f['solicitado'] as num?)?.toInt() ?? 0,
          disponible: (f['disponible'] as num?)?.toInt() ?? 0,
        ),
      ),
      resolucion: resolucion is Map
          ? ResolucionSync(accion: resolucion['accion'] as String? ?? '', motivo: resolucion['motivo'] as String?)
          : null,
    );
  }

  final String operacionId;
  final EstadoResultadoSync estado;

  /// El CÓDIGO estable del motivo (`stock_insuficiente`, `variante_inactiva`...): ver `motivos_sync.dart`.
  final String? motivo;

  /// El texto del servidor, solo como respaldo para un código que la app no conoce.
  final String? mensaje;
  final bool duplicada;

  /// La hora del SERVIDOR en que procesó la operación.
  final DateTime? procesadaEn;
  final RecursoSync? recurso;
  final int? cambioCentavos;
  final List<AvisoPrecioSync> avisos;
  final List<FaltanteSync> faltantes;
  final ResolucionSync? resolucion;
}

class RespuestaLote {
  const RespuestaLote({required this.versionContrato, required this.resultados, this.procesadoEn});

  /// Lanza un `ErrorApp` ("Actualiza la app para sincronizar.") si el servidor habla un contrato más nuevo.
  factory RespuestaLote.fromJson(Map<String, dynamic> json) {
    verificarVersionContrato(json['version_contrato']);
    final resultados = json['resultados'];
    return RespuestaLote(
      versionContrato: '${json['version_contrato'] ?? versionContratoSync}',
      procesadoEn: leerFechaUtc(json['procesado_en']),
      resultados: resultados is List
          ? [for (final r in resultados) if (r is Map) ResultadoOperacionSync.fromJson(Map<String, dynamic>.from(r))]
          : const [],
    );
  }

  final String versionContrato;
  final DateTime? procesadoEn;
  final List<ResultadoOperacionSync> resultados;
}
