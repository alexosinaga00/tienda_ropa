import 'dart:async';
import 'dart:typed_data';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:dio/dio.dart';
// ignore: depend_on_referenced_packages
import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';

/// Servidor falso de `/health`: cuenta las peticiones y responde con [status], falla con [error] o se cuelga.
class _Servidor implements HttpClientAdapter {
  int status = 200;
  Object? error;
  bool colgar = false;
  Completer<int>? pendiente;
  final List<RequestOptions> peticiones = [];

  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async {
    peticiones.add(options);
    if (colgar) return Completer<ResponseBody>().future;
    if (pendiente != null) {
      final codigo = await pendiente!.future;
      return ResponseBody.fromString('{}', codigo);
    }
    if (error != null) throw error!;
    return ResponseBody.fromString('{}', status);
  }

  @override
  void close({bool force = false}) {}
}

/// Todo lo necesario para armar un [ConectividadReal] controlado desde la prueba.
class _Banco {
  _Banco({
    this.redes = const [ConnectivityResult.wifi],
    Duration debounce = const Duration(milliseconds: 30),
    Duration timeout = const Duration(milliseconds: 150),
  }) {
    servicio = ConectividadReal(
      cambios: () => cambios.stream,
      lector: () async => redes,
      dio: Dio()..httpClientAdapter = servidor,
      urlHealth: 'http://test/health',
      debounce: debounce,
      timeout: timeout,
    );
    servicio.enLinea.listen(eventos.add);
  }

  final cambios = StreamController<List<ConnectivityResult>>.broadcast();
  final servidor = _Servidor();
  final eventos = <bool>[];
  List<ConnectivityResult> redes;
  late final ConectividadReal servicio;

  /// Cambia la red del "sistema" y avisa del cambio.
  void cambiarRed(List<ConnectivityResult> nuevas) {
    redes = nuevas;
    cambios.add(nuevas);
  }

  void cerrar() {
    servicio.dispose();
    cambios.close();
  }
}

Future<void> _esperar([int ms = 250]) => Future<void>.delayed(Duration(milliseconds: ms));

void main() {
  group('raizDeApi', () {
    test('quita el sufijo /api/v1', () {
      expect(raizDeApi('https://backend.up.railway.app/api/v1'), 'https://backend.up.railway.app');
    });

    test('quita barras finales y también el sufijo', () {
      expect(raizDeApi('http://10.0.2.2:8000/api/v1/'), 'http://10.0.2.2:8000');
    });

    test('si no hay sufijo deja la URL como está', () {
      expect(raizDeApi('http://servidor:8000'), 'http://servidor:8000');
    });
  });

  group('ConectividadReal', () {
    test('actual arranca en true (optimista) hasta la primera verificación', () {
      final b = _Banco();
      expect(b.servicio.actual, isTrue);
      b.cerrar();
    });

    test('con red y /health 200 se mantiene en línea sin emitir nada', () async {
      final b = _Banco();
      await _esperar(100);
      expect(b.servicio.actual, isTrue);
      expect(b.eventos, isEmpty);
      expect(b.servidor.peticiones, hasLength(1));
      expect(b.servidor.peticiones.single.uri.toString(), 'http://test/health');
      b.cerrar();
    });

    test('sin interfaz de red al iniciar: false y NO pide /health', () async {
      final b = _Banco(redes: [ConnectivityResult.none]);
      await _esperar(100);
      expect(b.servicio.actual, isFalse);
      expect(b.eventos, [false]);
      expect(b.servidor.peticiones, isEmpty);
      b.cerrar();
    });

    test('un cambio a "sin red" confirma sin pedir /health', () async {
      final b = _Banco();
      await _esperar(100);
      b.cambiarRed([ConnectivityResult.none]);
      await _esperar();
      expect(b.eventos, [false]);
      expect(b.servidor.peticiones, hasLength(1)); // solo la del inicio
      b.cerrar();
    });

    test('hay interfaz pero /health responde 500: false', () async {
      final b = _Banco();
      b.servidor.status = 500;
      await b.servicio.verificarAhora();
      await _esperar(10);
      expect(b.servicio.actual, isFalse);
      expect(b.eventos, [false]);
      b.cerrar();
    });

    test('hay interfaz pero /health no responde a tiempo: false', () async {
      final b = _Banco();
      await _esperar(50);
      b.servidor.colgar = true;
      final resultado = await b.servicio.verificarAhora();
      expect(resultado, isFalse);
      expect(b.servicio.actual, isFalse);
      b.cerrar();
    });

    test('hay interfaz pero la conexión falla: false', () async {
      final b = _Banco();
      await _esperar(50);
      b.servidor.error = DioException(
        requestOptions: RequestOptions(path: '/health'),
        type: DioExceptionType.connectionError,
      );
      expect(await b.servicio.verificarAhora(), isFalse);
      b.cerrar();
    });

    test('verificarAhora devuelve true y actualiza el estado cuando /health responde 200', () async {
      final b = _Banco();
      b.servidor.status = 503;
      expect(await b.servicio.verificarAhora(), isFalse);
      b.servidor.status = 200;
      expect(await b.servicio.verificarAhora(), isTrue);
      expect(b.servicio.actual, isTrue);
      await _esperar(10);
      expect(b.eventos, [false, true]);
      b.cerrar();
    });

    test('al recuperar la red emite true UNA sola vez aunque haya varios eventos seguidos', () async {
      final b = _Banco(redes: [ConnectivityResult.none]);
      await _esperar(100);
      expect(b.eventos, [false]);
      final antes = b.servidor.peticiones.length;

      b.cambiarRed([ConnectivityResult.mobile]);
      await _esperar(10);
      b.cambiarRed([ConnectivityResult.wifi]);
      await _esperar(10);
      b.cambiarRed([ConnectivityResult.wifi, ConnectivityResult.vpn]);
      await _esperar(300);

      expect(b.eventos, [false, true]);
      expect(b.servidor.peticiones.length - antes, 1, reason: 'el debounce junta los eventos en una verificación');
      b.cerrar();
    });

    test('no repite el mismo valor seguido', () async {
      final b = _Banco();
      await _esperar(100);
      b.cambiarRed([ConnectivityResult.none]);
      await _esperar();
      b.cambiarRed([ConnectivityResult.none]);
      await _esperar();
      b.cambiarRed([ConnectivityResult.none]);
      await _esperar();
      expect(b.eventos, [false]);
      b.cerrar();
    });

    test('usa el último evento de la ráfaga: si termina sin red, queda sin conexión', () async {
      final b = _Banco();
      await _esperar(100);
      b.cambiarRed([ConnectivityResult.wifi]);
      b.cambiarRed([ConnectivityResult.none]);
      await _esperar();
      expect(b.eventos, [false]);
      b.cerrar();
    });

    test('informarFalloDeRed marca sin conexión de inmediato y no repite', () async {
      final b = _Banco();
      await _esperar(100);
      b.servicio.informarFalloDeRed();
      expect(b.servicio.actual, isFalse);
      b.servicio.informarFalloDeRed();
      await _esperar(10);
      expect(b.eventos, [false]);
      b.cerrar();
    });

    test('informarRespuestaOk marca en línea de inmediato', () async {
      final b = _Banco(redes: [ConnectivityResult.none]);
      await _esperar(100);
      expect(b.servicio.actual, isFalse);
      b.servicio.informarRespuestaOk();
      expect(b.servicio.actual, isTrue);
      await _esperar(10);
      expect(b.eventos, [false, true]);
      b.cerrar();
    });

    test('un aviso manual no es pisado por una verificación que venía en vuelo', () async {
      final b = _Banco();
      await _esperar(100);
      b.servidor.pendiente = Completer<int>();
      final enVuelo = b.servicio.verificarAhora();
      await _esperar(20);
      b.servicio.informarFalloDeRed();
      b.servidor.pendiente!.complete(200); // la respuesta vieja llega tarde
      await enVuelo;
      expect(b.servicio.actual, isFalse);
      expect(b.eventos, [false]);
      b.cerrar();
    });

    test('dispose cierra el stream y los eventos posteriores no emiten', () async {
      final b = _Banco();
      await _esperar(100);
      var cerrado = false;
      b.servicio.enLinea.listen((_) {}, onDone: () => cerrado = true);
      b.servicio.dispose();
      await _esperar(20);
      expect(cerrado, isTrue);
      b.servicio.informarFalloDeRed();
      b.cambiarRed([ConnectivityResult.none]);
      await _esperar();
      expect(b.eventos, isEmpty);
      // Llamarlo dos veces no falla.
      b.servicio.dispose();
      b.cambios.close();
    });

    test('con el debounce por defecto (1 s) varios cambios seguidos hacen una sola verificación', () {
      fakeAsync((async) {
        final cambios = StreamController<List<ConnectivityResult>>.broadcast();
        final servidor = _Servidor();
        var redes = [ConnectivityResult.wifi];
        final eventos = <bool>[];
        final servicio = ConectividadReal(
          cambios: () => cambios.stream,
          lector: () async => redes,
          dio: Dio()..httpClientAdapter = servidor,
          urlHealth: 'http://test/health',
        );
        servicio.enLinea.listen(eventos.add);
        async.elapse(const Duration(milliseconds: 10));
        async.flushMicrotasks();
        final alIniciar = servidor.peticiones.length;

        servidor.status = 500;
        cambios.add([ConnectivityResult.mobile]);
        async.elapse(const Duration(milliseconds: 600));
        cambios.add([ConnectivityResult.wifi]);
        async.elapse(const Duration(milliseconds: 600));
        // Pasaron 1,2 s desde el primer evento pero solo 0,6 s desde el último: aún no verifica.
        expect(servidor.peticiones.length, alIniciar);

        async.elapse(const Duration(milliseconds: 600));
        async.flushMicrotasks();
        expect(servidor.peticiones.length - alIniciar, 1);
        expect(eventos, [false]);

        servicio.dispose();
        cambios.close();
      });
    });
  });
}
