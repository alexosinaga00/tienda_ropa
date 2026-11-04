import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/features/compras/models/solicitud_cambio.dart';
import 'package:mobile/features/compras/state/compras_providers.dart';

/// Lo que el detalle de una compra pagada necesita de la sección "Cambiar talla o color": las solicitudes de la
/// compra, las tallas que se ofrecen y la conexión. Sin esto la sección llamaría a la red de verdad.
List<Override> solicitudesCambioFalsas(
  int ventaId, {
  List<SolicitudCambio> solicitudes = const [],
  Map<int, List<OpcionCambio>> opciones = const {},
  bool enLinea = true,
}) => [
  misSolicitudesCambioProvider(ventaId).overrideWith((ref) async => solicitudes),
  opcionesCambioProvider(ventaId).overrideWith((ref) async => opciones),
  comprasConCambioPendienteProvider.overrideWith((ref) async => <int>{}),
  enLineaProvider.overrideWith((ref) => Stream.value(enLinea)),
];
