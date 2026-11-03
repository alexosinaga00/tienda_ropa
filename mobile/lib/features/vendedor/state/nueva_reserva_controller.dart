import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/sync/cola_operaciones.dart';
import '../../../core/sync/lineas_operacion.dart';
import '../../../core/utils/reloj.dart';
import '../models/cliente_local.dart';
import '../models/producto_local.dart';
import '../models/variante_local.dart';
import 'carrito_operacion.dart';
import 'catalogo_local_providers.dart';
import 'sincronizacion_providers.dart';

export 'carrito_operacion.dart';

const textoFalloGuardarReserva = 'No pudimos guardar la reserva en el teléfono. Intenta de nuevo.';

/// El servidor admite hasta 300 caracteres de observación.
const maxObservacionReserva = 300;

final _formatoHoraReserva = RegExp(r'^([01]\d|2[0-3]):[0-5]\d$');

/// Lo que la pantalla "Nueva reserva" muestra y la persona va armando.
class NuevaReservaState {
  const NuevaReservaState({
    required this.operacionId,
    required this.hoy,
    this.sucursalId,
    this.lineas = const [],
    this.cliente,
    this.fechaVisita,
    this.horaDesde,
    this.horaHasta,
    this.observacion = '',
    this.registrando = false,
    this.error,
  });

  final String operacionId;

  /// El día de hoy en el teléfono (sin hora): la visita no puede ser antes.
  final DateTime hoy;
  final int? sucursalId;
  final List<LineaCarrito> lineas;

  /// OBLIGATORIO: un cliente del servidor.
  final ClienteLocal? cliente;
  final DateTime? fechaVisita;

  /// "HH:mm".
  final String? horaDesde;
  final String? horaHasta;
  final String observacion;
  final bool registrando;
  final String? error;

  int get cantidadPrendas => lineas.fold(0, (suma, l) => suma + l.cantidad);

  /// Qué falta o está mal, o null si ya se puede registrar. El horario de la sucursal NO se valida aquí: lo hace el servidor.
  String? get problema {
    if (lineas.isEmpty) return 'Agrega al menos una prenda.';
    if (cliente == null) return 'Elige el cliente de la reserva.';
    final fecha = fechaVisita;
    if (fecha == null) return 'Elige la fecha de la visita.';
    if (DateTime(fecha.year, fecha.month, fecha.day).isBefore(hoy)) {
      return 'La fecha de la visita no puede ser anterior a hoy.';
    }
    final desde = horaDesde;
    final hasta = horaHasta;
    if (desde == null || hasta == null) return 'Elige la hora de inicio y la de fin de la visita.';
    if (!_formatoHoraReserva.hasMatch(desde) || !_formatoHoraReserva.hasMatch(hasta)) {
      return 'Las horas de la visita deben tener el formato HH:mm.';
    }
    if (hasta.compareTo(desde) <= 0) return 'La hora de fin debe ser posterior a la hora de inicio.';
    if (observacion.trim().length > maxObservacionReserva) {
      return 'La observación no puede pasar de $maxObservacionReserva caracteres.';
    }
    if (sucursalId == null) return 'Elige una sucursal.';
    return null;
  }

  bool get puedeRegistrar => problema == null && !registrando;

  NuevaReservaState copiar({
    int? Function()? sucursalId,
    List<LineaCarrito>? lineas,
    ClienteLocal? Function()? cliente,
    DateTime? Function()? fechaVisita,
    String? Function()? horaDesde,
    String? Function()? horaHasta,
    String? observacion,
    bool? registrando,
    String? Function()? error,
  }) => NuevaReservaState(
    operacionId: operacionId,
    hoy: hoy,
    sucursalId: sucursalId != null ? sucursalId() : this.sucursalId,
    lineas: lineas ?? this.lineas,
    cliente: cliente != null ? cliente() : this.cliente,
    fechaVisita: fechaVisita != null ? fechaVisita() : this.fechaVisita,
    horaDesde: horaDesde != null ? horaDesde() : this.horaDesde,
    horaHasta: horaHasta != null ? horaHasta() : this.horaHasta,
    observacion: observacion ?? this.observacion,
    registrando: registrando ?? this.registrando,
    error: error != null ? error() : this.error,
  );
}

/// Arma una reserva (un cliente que está en tienda viene a ver unas prendas) y la guarda en la cola. NO sincroniza.
class NuevaReservaController extends StateNotifier<NuevaReservaState> {
  NuevaReservaController(this._ref, {required String operacionId, required DateTime hoy})
    : super(NuevaReservaState(operacionId: operacionId, hoy: hoy));

  final Ref _ref;

  Future<ResultadoRegistro>? _enCurso;
  bool _registrada = false;

  // ---- Edición ----

  void agregar(VarianteLocal variante, ProductoLocal producto, int cantidad) {
    if (_bloqueado) return;
    state = state.copiar(lineas: agregarLinea(state.lineas, variante, producto, cantidad), error: () => null);
  }

  void cambiarCantidad(int varianteId, int cantidad) {
    if (_bloqueado) return;
    state = state.copiar(lineas: cambiarCantidadLinea(state.lineas, varianteId, cantidad), error: () => null);
  }

  void quitar(int varianteId) {
    if (_bloqueado) return;
    state = state.copiar(lineas: quitarLinea(state.lineas, varianteId), error: () => null);
  }

  void elegirCliente(ClienteLocal cliente) {
    if (_bloqueado) return;
    state = state.copiar(cliente: () => cliente, error: () => null);
  }

  void quitarCliente() {
    if (_bloqueado) return;
    state = state.copiar(cliente: () => null, error: () => null);
  }

  /// Solo cuenta el día: la hora se descarta.
  void elegirFecha(DateTime fecha) {
    if (_bloqueado) return;
    final dia = DateTime(fecha.year, fecha.month, fecha.day);
    state = state.copiar(fechaVisita: () => dia, error: () => null);
  }

  /// "HH:mm".
  void elegirHoraDesde(String hora) {
    if (_bloqueado) return;
    state = state.copiar(horaDesde: () => hora, error: () => null);
  }

  void elegirHoraHasta(String hora) {
    if (_bloqueado) return;
    state = state.copiar(horaHasta: () => hora, error: () => null);
  }

  void cambiarObservacion(String texto) {
    if (_bloqueado) return;
    state = state.copiar(observacion: texto, error: () => null);
  }

  /// Cambiar de sucursal VACÍA las prendas: la existencia depende de la sucursal (la pantalla avisa antes).
  void elegirSucursal(int sucursalId) {
    if (_bloqueado || state.sucursalId == sucursalId) return;
    state = state.copiar(sucursalId: () => sucursalId, lineas: const [], error: () => null);
  }

  bool get _bloqueado => _registrada || state.registrando;

  // ---- Registro ----

  /// Valida y guarda. Un segundo toque mientras se guarda recibe el MISMO resultado; uno después de guardada devuelve
  /// `registrada` con el mismo id. Con prendas que piden más de lo que se estima que queda devuelve las advertencias SIN
  /// registrar; la persona decide y vuelve a llamar con [permitirSinStock] en `true`.
  Future<ResultadoRegistro> registrar({bool permitirSinStock = false}) {
    final enCurso = _enCurso;
    if (enCurso != null) return enCurso;
    final trabajo = _registrar(permitirSinStock);
    _enCurso = trabajo;
    return trabajo.whenComplete(() => _enCurso = null);
  }

  Future<ResultadoRegistro> _registrar(bool permitirSinStock) async {
    if (_registrada) return ResultadoRegistro.registrada(state.operacionId);
    final problema = state.problema;
    if (problema != null) return _fallar(problema);

    final inicial = state;
    final sucursalId = inicial.sucursalId!;
    state = state.copiar(registrando: true, error: () => null);
    try {
      if (!permitirSinStock) {
        final avisos = await advertenciasDeStock(_ref, sucursalId: sucursalId, lineas: inicial.lineas);
        if (!mounted) return const ResultadoRegistro.error('Se cerró la pantalla antes de registrar.');
        if (avisos.isNotEmpty) {
          state = state.copiar(registrando: false);
          return ResultadoRegistro.advertencias(avisos);
        }
      }

      final empresaId = _ref.read(empresaLocalIdProvider);
      final usuarioId = _ref.read(usuarioLocalIdProvider);
      if (empresaId == null || usuarioId == null) {
        return _fallar('Tu sesión no está disponible. Vuelve a entrar.');
      }
      final cola = await _ref.read(colaOperacionesProvider.future);
      final observacion = inicial.observacion.trim();
      final reserva = NuevaReserva(
        operacionId: inicial.operacionId,
        empresaId: empresaId,
        sucursalId: sucursalId,
        usuarioId: usuarioId,
        fechaOperacion: _ref.read(relojProvider).ahora(),
        clienteMinimoId: inicial.cliente!.id,
        fechaVisita: inicial.fechaVisita!,
        horaDesde: inicial.horaDesde!,
        horaHasta: inicial.horaHasta!,
        observacion: observacion.isEmpty ? null : observacion,
        lineas: [for (final l in inicial.lineas) LineaReserva(varianteId: l.varianteId, cantidad: l.cantidad)],
      );
      final resultado = await guardarEnCola(
        cola,
        inicial.operacionId,
        () => cola.registrarReserva(reserva),
        textoFalloInesperado: textoFalloGuardarReserva,
      );
      if (resultado is RegistroExitoso) _registrada = true;
      if (!mounted) return resultado;
      state = state.copiar(registrando: false, error: () => resultado is RegistroConError ? resultado.mensaje : null);
      return resultado;
    } catch (_) {
      return _fallar(textoFalloGuardarReserva);
    }
  }

  ResultadoRegistro _fallar(String mensaje) {
    if (mounted) state = state.copiar(registrando: false, error: () => mensaje);
    return ResultadoRegistro.error(mensaje);
  }
}

/// Un controlador por apertura de la pantalla: el `operacionId` se genera AL CREARLO y se descarta al salir.
final nuevaReservaControllerProvider = StateNotifierProvider.autoDispose<NuevaReservaController, NuevaReservaState>((ref) {
  final ahora = ref.read(relojProvider).ahora().toLocal();
  return NuevaReservaController(
    ref,
    operacionId: ref.read(generadorUuidProvider).nuevo(),
    hoy: DateTime(ahora.year, ahora.month, ahora.day),
  );
});
