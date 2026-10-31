import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/network/providers.dart';
import '../../auth/state/auth_controller.dart';
import '../../tienda/state/tienda_controller.dart';
import '../models/evento.dart';

/// Registra eventos de navegación (vista, búsqueda, favorito) en
/// POST /api/v1/ia/eventos, que alimenta al recomendador.
///
/// `track()` nunca lanza ni bloquea a quien lo llama: dispara el envío
/// sin esperarlo (fire-and-forget) y cualquier error se traga acá adentro,
/// nunca llega a la UI.
///
/// Qué pasa con un evento que no se pudo enviar:
/// - sin conexión, timeout, 5xx, 408 o 429: queda encolado y se reintenta
///   con el próximo `track()`;
/// - cualquier otro 4xx (p. ej. 422): el backend rechaza ESE payload y
///   reintentarlo daría lo mismo, así que se descarta y se sigue con el
///   resto de la cola.
/// La cola tiene un tope: si se llena (mucho tiempo sin red), se descartan
/// los eventos más viejos.
class TrackingService {
  /// [codigoInvitado]: devuelve el código de la tienda elegida cuando NO hay sesión (se usa la ruta pública
  /// `/public/{codigo}/ia/eventos`) o null cuando hay sesión (la empresa sale del token).
  TrackingService(this._dio, {this._codigoInvitado});

  static const maxEventosEncolados = 100;

  final Dio _dio;
  final String? Function()? _codigoInvitado;
  final List<Evento> _cola = [];

  int get eventosEncolados => _cola.length;

  void track({required TipoEvento tipo, int? productoId, int? varianteId, String? texto}) {
    _cola.add(
      Evento(tipo: tipo, productoId: productoId, varianteId: varianteId, texto: texto, creadoEn: DateTime.now()),
    );
    if (_cola.length > maxEventosEncolados) {
      _cola.removeRange(0, _cola.length - maxEventosEncolados);
    }
    unawaited(_vaciarCola());
  }

  Future<void> _vaciarCola() async {
    // Copia porque _cola puede mutar mientras se recorre (otro track()
    // concurrente, o un elemento que se saca al confirmarse el envío).
    for (final evento in List<Evento>.from(_cola)) {
      try {
        final codigo = _codigoInvitado?.call();
        if (codigo == null) {
          await _dio.post<void>('/ia/eventos', data: evento.toJson());
        } else {
          await _dio.post<void>(
            '/public/$codigo/ia/eventos',
            data: evento.toJson(),
            options: Options(extra: {'publica': true}),
          );
        }
        _cola.remove(evento);
      } catch (error) {
        if (_esRechazoDefinitivo(error)) {
          _cola.remove(evento);
          continue;
        }
        return; // sin red o backend caído: se reintenta con el próximo track()
      }
    }
  }

  static bool _esRechazoDefinitivo(Object error) {
    if (error is! DioException) return false;
    final status = error.response?.statusCode;
    if (status == null) return false;
    return status >= 400 && status < 500 && status != 408 && status != 429;
  }
}

/// Observa la tienda y la sesión: al cambiar cualquiera se descarta la cola en RAM (tiene ids de producto de la otra
/// empresa o de otra persona).
final trackingServiceProvider = Provider<TrackingService>((ref) {
  final autenticado = ref.watch(authControllerProvider.select((s) => s.estaAutenticado));
  final codigo = ref.watch(tiendaCodigoProvider);
  return TrackingService(ref.watch(dioProvider), codigoInvitado: () => autenticado ? null : codigo);
});
