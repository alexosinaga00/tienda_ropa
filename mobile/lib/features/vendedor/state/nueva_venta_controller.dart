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

const textoFalloGuardarVenta = 'No pudimos guardar la venta en el teléfono. Intenta de nuevo.';

/// Lo que la pantalla "Nueva venta" muestra y la persona va armando.
class NuevaVentaState {
  const NuevaVentaState({
    required this.operacionId,
    this.sucursalId,
    this.lineas = const [],
    this.cliente,
    this.efectivoConfirmado = false,
    this.registrando = false,
    this.error,
  });

  /// UUID generado al abrir la pantalla: un doble toque en "Registrar" intenta el MISMO id.
  final String operacionId;
  final int? sucursalId;
  final List<LineaCarrito> lineas;

  /// Opcional: una venta puede no tener cliente.
  final ClienteLocal? cliente;

  /// La persona dice que recibió el efectivo. NO es la aprobación del servidor.
  final bool efectivoConfirmado;
  final bool registrando;
  final String? error;

  int get totalCentavos => lineas.fold(0, (suma, l) => suma + l.subtotalCentavos);

  int get cantidadPrendas => lineas.fold(0, (suma, l) => suma + l.cantidad);

  /// Qué falta para poder registrar, o null si ya se puede.
  String? get problema {
    if (lineas.isEmpty) return 'Agrega al menos una prenda.';
    if (!efectivoConfirmado) return 'Confirma que recibiste el efectivo.';
    if (sucursalId == null) return 'Elige una sucursal.';
    return null;
  }

  bool get puedeRegistrar => problema == null && !registrando;

  NuevaVentaState copiar({
    int? Function()? sucursalId,
    List<LineaCarrito>? lineas,
    ClienteLocal? Function()? cliente,
    bool? efectivoConfirmado,
    bool? registrando,
    String? Function()? error,
  }) => NuevaVentaState(
    operacionId: operacionId,
    sucursalId: sucursalId != null ? sucursalId() : this.sucursalId,
    lineas: lineas ?? this.lineas,
    cliente: cliente != null ? cliente() : this.cliente,
    efectivoConfirmado: efectivoConfirmado ?? this.efectivoConfirmado,
    registrando: registrando ?? this.registrando,
    error: error != null ? error() : this.error,
  );
}

/// Arma una venta de contado en efectivo y la guarda en la cola. NO sincroniza: el disparador lo hace al ver la operación nueva.
class NuevaVentaController extends StateNotifier<NuevaVentaState> {
  NuevaVentaController(this._ref, {required String operacionId}) : super(NuevaVentaState(operacionId: operacionId));

  final Ref _ref;

  Future<ResultadoRegistro>? _enCurso;
  bool _registrada = false;

  // ---- Edición ----

  /// Agrega [cantidad] de [variante]; si ya estaba suma a su línea. El precio es el local de este momento y queda congelado.
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

  void confirmarEfectivo(bool valor) {
    if (_bloqueado) return;
    state = state.copiar(efectivoConfirmado: valor, error: () => null);
  }

  /// Cambiar de sucursal VACÍA las prendas: la existencia y los precios dependen de la sucursal (la pantalla avisa antes).
  void elegirSucursal(int sucursalId) {
    if (_bloqueado || state.sucursalId == sucursalId) return;
    state = state.copiar(sucursalId: () => sucursalId, lineas: const [], error: () => null);
  }

  /// Ya se registró o se está registrando: lo que se ve en pantalla no debe cambiar por debajo.
  bool get _bloqueado => _registrada || state.registrando;

  // ---- Registro ----

  /// Valida y guarda. Un segundo toque mientras se guarda recibe el MISMO resultado; uno después de guardada devuelve
  /// `registrada` con el mismo id (no duplica ni es un error).
  ///
  /// Si alguna prenda pide más de lo que se estima que queda, devuelve las advertencias SIN registrar; la persona decide y
  /// vuelve a llamar con [permitirSinStock] en `true`.
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
      final venta = NuevaVenta(
        operacionId: inicial.operacionId,
        empresaId: empresaId,
        sucursalId: sucursalId,
        usuarioId: usuarioId,
        fechaOperacion: _ref.read(relojProvider).ahora(),
        lineas: [
          for (final l in inicial.lineas)
            LineaVenta(
              varianteId: l.varianteId,
              cantidad: l.cantidad,
              precioUnitarioCentavos: l.precioUnitarioCentavos,
              descuentoUnitarioCentavos: l.descuentoUnitarioCentavos,
            ),
        ],
        clienteMinimoId: inicial.cliente?.id,
        efectivoConfirmado: inicial.efectivoConfirmado,
      );
      final resultado = await guardarEnCola(
        cola,
        inicial.operacionId,
        () => cola.registrarVenta(venta),
        textoFalloInesperado: textoFalloGuardarVenta,
      );
      if (resultado is RegistroExitoso) _registrada = true;
      if (!mounted) return resultado;
      state = state.copiar(registrando: false, error: () => resultado is RegistroConError ? resultado.mensaje : null);
      return resultado;
    } catch (_) {
      return _fallar(textoFalloGuardarVenta);
    }
  }

  ResultadoRegistro _fallar(String mensaje) {
    if (mounted) state = state.copiar(registrando: false, error: () => mensaje);
    return ResultadoRegistro.error(mensaje);
  }
}

/// Un controlador por apertura de la pantalla: el `operacionId` se genera AL CREARLO y se descarta al salir.
final nuevaVentaControllerProvider = StateNotifierProvider.autoDispose<NuevaVentaController, NuevaVentaState>(
  (ref) => NuevaVentaController(ref, operacionId: ref.read(generadorUuidProvider).nuevo()),
);
