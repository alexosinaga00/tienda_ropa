import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/utils/reloj.dart';
import '../config/cliente_offline_config.dart';
import '../data/metodo_pago_repository.dart';
import '../data/repositorio_cliente.dart';
import '../models/metodo_pago.dart';

/// Lo que el teléfono recuerda del método de pago para decidir SIN red: solo "tiene PayPal guardado" y el correo enmascarado
/// que devolvió el servidor (nunca un token de PayPal ni datos de tarjeta). Se actualiza cada vez que se consulta, guarda o
/// quita con conexión, y se borra al cerrar sesión. El estado es null mientras no se sabe nada.
class MetodoPagoController extends StateNotifier<MetodoPagoRecordado?> {
  MetodoPagoController(this._repositorio, this._api, this._reloj, {required bool activo}) : super(null) {
    if (activo) cargar();
  }

  final Future<RepositorioCliente?> Function() _repositorio;
  final MetodoPagoRepository _api;
  final Reloj _reloj;

  Future<RepositorioCliente?> _repo() async {
    try {
      return await _repositorio();
    } catch (e) {
      debugPrint('metodo_pago no se pudo abrir la base error=${e.runtimeType}');
      return null;
    }
  }

  /// Lee lo recordado. Nunca lanza.
  Future<void> cargar() async {
    final repo = await _repo();
    if (repo == null) {
      if (mounted) state = null;
      return;
    }
    try {
      final recordado = MetodoPagoRecordado.desdeTexto(await repo.leerMeta(metaMetodoPago));
      // Lo que el servidor acaba de decir (mientras se leía la base) vale más que lo guardado de antes.
      if (mounted && state == null) state = recordado;
    } catch (e) {
      debugPrint('metodo_pago no se pudo leer error=${e.runtimeType}');
    }
  }

  /// Recuerda el estado que acaba de dar el servidor. Nunca lanza.
  Future<void> recordar(MetodoPagoPaypal estado) async {
    final recordado = MetodoPagoRecordado.desde(estado, _reloj.ahora());
    if (mounted) state = recordado;
    final repo = await _repo();
    if (repo == null) return;
    try {
      await repo.guardarMeta(metaMetodoPago, recordado.aTexto());
    } catch (e) {
      debugPrint('metodo_pago no se pudo recordar error=${e.runtimeType}');
    }
  }

  /// Con conexión, pregunta al servidor y recuerda la respuesta. Si falla, queda lo que ya se recordaba y devuelve null.
  Future<MetodoPagoPaypal?> refrescar() async {
    try {
      final estado = await _api.estado();
      await recordar(estado);
      return estado;
    } catch (_) {
      return null;
    }
  }
}
