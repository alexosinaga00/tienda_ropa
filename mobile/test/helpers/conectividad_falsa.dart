import 'dart:async';

import 'package:mobile/core/conectividad/conectividad_service.dart';

/// Doble de [ConectividadService] para tests: el estado se cambia a mano con [emitir]. Como el real, solo emite cuando el
/// valor cambia.
class ConectividadFalsa implements ConectividadService {
  ConectividadFalsa({bool enLinea = true}) : _actual = enLinea;

  final StreamController<bool> _controlador = StreamController<bool>.broadcast();
  bool _actual;

  /// Cuántas veces se pidió [verificarAhora].
  int verificaciones = 0;

  @override
  Stream<bool> get enLinea => _controlador.stream;

  @override
  bool get actual => _actual;

  @override
  Future<bool> verificarAhora() async {
    verificaciones++;
    return _actual;
  }

  /// Cambia el estado de la conexión y avisa a quien escucha (no hace nada si no cambió).
  void emitir(bool valor) {
    if (valor == _actual) return;
    _actual = valor;
    _controlador.add(valor);
  }

  Future<void> cerrar() => _controlador.close();
}
