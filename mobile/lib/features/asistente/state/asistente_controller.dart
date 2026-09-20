import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';

enum EstadoAsistente { cargando, listo, error }

/// En qué está el chat: conectando, listo o sin poder conectar.
///
/// Con la página cargada desde un texto, si Botpress no responde (sin red, CDN caído) el WebView no lo reporta como
/// error del documento, porque solo fallan los scripts. Por eso hay un plazo: si el chat no avisa que está listo a
/// tiempo, pasa a [EstadoAsistente.error]. Si el aviso llega tarde igual se acepta, es mejor que dejar el error.
class AsistenteController extends StateNotifier<EstadoAsistente> {
  AsistenteController({this.plazo = const Duration(seconds: 25)}) : super(EstadoAsistente.cargando) {
    _armarPlazo();
  }

  final Duration plazo;
  Timer? _temporizador;

  void _armarPlazo() {
    _temporizador?.cancel();
    _temporizador = Timer(plazo, () {
      if (mounted && state == EstadoAsistente.cargando) state = EstadoAsistente.error;
    });
  }

  void alListo() {
    if (!mounted) return;
    _temporizador?.cancel();
    state = EstadoAsistente.listo;
  }

  void alFallar() {
    if (!mounted) return;
    _temporizador?.cancel();
    state = EstadoAsistente.error;
  }

  void reintentar() {
    if (!mounted) return;
    state = EstadoAsistente.cargando;
    _armarPlazo();
  }

  @override
  void dispose() {
    _temporizador?.cancel();
    super.dispose();
  }
}

/// Uno por visita a la pantalla: al salir se descarta y entrar de nuevo empieza de cero.
final asistenteControllerProvider = StateNotifierProvider.autoDispose<AsistenteController, EstadoAsistente>(
  (ref) => AsistenteController(),
);
