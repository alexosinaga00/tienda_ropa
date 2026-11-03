import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';

DioException _sinRespuesta(DioExceptionType tipo, {Object? error}) {
  return DioException(requestOptions: RequestOptions(path: '/sincronizacion/lote'), type: tipo, error: error);
}

DioException _conRespuesta(int estado, {Object? cuerpo}) {
  final opciones = RequestOptions(path: '/sincronizacion/lote');
  return DioException(
    requestOptions: opciones,
    type: DioExceptionType.badResponse,
    response: Response(requestOptions: opciones, statusCode: estado, data: cuerpo),
  );
}

void main() {
  group('ErrorApp.posiblementeRecibido: la petición pudo haber llegado al servidor', () {
    test('por defecto es false', () {
      const e = ErrorApp(tipo: TipoErrorApp.desconocido, mensaje: 'x');
      expect(e.posiblementeRecibido, isFalse);
    });

    test('connectionError: seguro que no llegó', () {
      final e = ErrorApp.desde(_sinRespuesta(DioExceptionType.connectionError));
      expect(e.tipo, TipoErrorApp.sinConexion);
      expect(e.posiblementeRecibido, isFalse);
    });

    test('connectionTimeout: seguro que no llegó (no se pudo conectar)', () {
      final e = ErrorApp.desde(_sinRespuesta(DioExceptionType.connectionTimeout));
      expect(e.tipo, TipoErrorApp.sinConexion);
      expect(e.posiblementeRecibido, isFalse);
    });

    test('sendTimeout: pudo haber llegado', () {
      final e = ErrorApp.desde(_sinRespuesta(DioExceptionType.sendTimeout));
      expect(e.tipo, TipoErrorApp.sinConexion);
      expect(e.posiblementeRecibido, isTrue);
    });

    test('receiveTimeout: pudo haber llegado (el servidor tardó en responder)', () {
      final e = ErrorApp.desde(_sinRespuesta(DioExceptionType.receiveTimeout));
      expect(e.tipo, TipoErrorApp.sinConexion);
      expect(e.posiblementeRecibido, isTrue);
    });

    test('una caída a mitad de camino (SocketException tras conectar) también pudo haber llegado', () {
      final e = ErrorApp.desde(_sinRespuesta(DioExceptionType.unknown, error: const SocketException('Connection reset')));
      expect(e.tipo, TipoErrorApp.sinConexion);
      expect(e.posiblementeRecibido, isTrue);
    });

    test('con respuesta HTTP el servidor sí contestó: posiblementeRecibido = false', () {
      for (final estado in [400, 401, 403, 404, 409, 422, 429, 500, 503]) {
        final e = ErrorApp.desde(_conRespuesta(estado));
        expect(e.estado, estado);
        expect(e.posiblementeRecibido, isFalse, reason: 'estado=$estado');
      }
    });

    test('un error que no es de red (cancelado) no marca posiblementeRecibido', () {
      final e = ErrorApp.desde(_sinRespuesta(DioExceptionType.cancel));
      expect(e.tipo, TipoErrorApp.desconocido);
      expect(e.posiblementeRecibido, isFalse);
    });

    test('una excepción que no es de Dio tampoco', () {
      final e = ErrorApp.desde(StateError('x'));
      expect(e.posiblementeRecibido, isFalse);
    });

    test('un ErrorApp se devuelve tal cual, conservando la bandera', () {
      const original = ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'x', posiblementeRecibido: true);
      final e = ErrorApp.desde(original);
      expect(identical(e, original), isTrue);
      expect(e.posiblementeRecibido, isTrue);
    });

    test('el mensaje de sin conexión es el mismo con o sin la bandera', () {
      final a = ErrorApp.desde(_sinRespuesta(DioExceptionType.connectionError));
      final b = ErrorApp.desde(_sinRespuesta(DioExceptionType.receiveTimeout));
      expect(a.mensaje, b.mensaje);
    });
  });
}
