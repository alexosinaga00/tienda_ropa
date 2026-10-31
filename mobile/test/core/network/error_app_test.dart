import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';

DioException _conRespuesta(int estado, {Object? cuerpo}) {
  final opciones = RequestOptions(path: '/prueba');
  return DioException(
    requestOptions: opciones,
    type: DioExceptionType.badResponse,
    response: Response(requestOptions: opciones, statusCode: estado, data: cuerpo),
  );
}

DioException _sinRespuesta(DioExceptionType tipo, {Object? error}) {
  return DioException(requestOptions: RequestOptions(path: '/prueba'), type: tipo, error: error);
}

const _mensajePlan = 'Tu plan no incluye esta función. Consulta con el administrador de tu empresa.';
const _mensajeSuscripcion = 'La suscripción de esta tienda no está activa. Contacta al administrador de la tienda.';
const _mensajeLimite = 'Tu empresa alcanzó el límite de su plan.';
const _mensajeSinConexion = 'Sin conexión. Revisa tu internet e intenta de nuevo.';
const _mensajeInesperado = 'Ocurrió un error inesperado. Intenta de nuevo.';

void main() {
  group('ErrorApp.desde - códigos funcionales', () {
    test('detail en texto con un código conocido: plan no incluye la función', () {
      final error = ErrorApp.desde(_conRespuesta(403, cuerpo: {'detail': 'plan_no_incluye_funcionalidad'}));

      expect(error.tipo, TipoErrorApp.planNoIncluyeFuncionalidad);
      expect(error.codigo, codigoPlanNoIncluye);
      expect(error.estado, 403);
      expect(error.mensaje, _mensajePlan);
      expect(error.detalle, 'plan_no_incluye_funcionalidad');
      expect(error.esFuncional, isTrue);
    });

    test('detail en texto con suscripcion_no_activa', () {
      final error = ErrorApp.desde(_conRespuesta(403, cuerpo: {'detail': 'suscripcion_no_activa'}));

      expect(error.tipo, TipoErrorApp.suscripcionNoActiva);
      expect(error.codigo, codigoSuscripcionNoActiva);
      expect(error.mensaje, _mensajeSuscripcion);
      expect(error.esFuncional, isTrue);
    });

    test('detail como mapa {codigo, mensaje}: manda el código y el mensaje fijo de la app', () {
      final error = ErrorApp.desde(
        _conRespuesta(
          409,
          cuerpo: {'detail': 'limite', 'codigo': 'limite_plan_excedido', 'mensaje': 'Tu plan permite 2 sucursales.'},
        ),
      );

      expect(error.tipo, TipoErrorApp.limitePlanExcedido);
      expect(error.codigo, codigoLimitePlan);
      expect(error.estado, 409);
      expect(error.mensaje, _mensajeLimite, reason: 'los funcionales usan siempre el mismo texto');
      expect(error.esFuncional, isTrue);
    });

    test('un código funcional manda aunque el estado HTTP sea otro', () {
      final error = ErrorApp.desde(_conRespuesta(400, cuerpo: {'codigo': 'plan_no_incluye_funcionalidad'}));

      expect(error.tipo, TipoErrorApp.planNoIncluyeFuncionalidad);
    });

    test('un código desconocido en el cuerpo no cambia el tipo por estado', () {
      final error = ErrorApp.desde(_conRespuesta(409, cuerpo: {'codigo': 'otra_cosa', 'mensaje': 'Ya existe'}));

      expect(error.tipo, TipoErrorApp.conflicto);
      expect(error.codigo, 'otra_cosa');
      expect(error.mensaje, 'Ya existe');
      expect(error.esFuncional, isFalse);
    });
  });

  group('ErrorApp.desde - por estado HTTP', () {
    test('403 sin código: prohibido, con el mensaje por defecto', () {
      final error = ErrorApp.desde(_conRespuesta(403, cuerpo: <String, dynamic>{}));

      expect(error.tipo, TipoErrorApp.prohibido);
      expect(error.mensaje, 'No tienes permiso para hacer esto.');
      expect(error.codigo, isNull);
      expect(error.esFuncional, isFalse);
    });

    test('403 sin código pero con detail: el mensaje es el del backend', () {
      final error = ErrorApp.desde(_conRespuesta(403, cuerpo: {'detail': 'Sin permiso para ver ventas'}));

      expect(error.tipo, TipoErrorApp.prohibido);
      expect(error.mensaje, 'Sin permiso para ver ventas');
    });

    test('409 con limite_plan_excedido: límite del plan', () {
      final error = ErrorApp.desde(_conRespuesta(409, cuerpo: {'detail': 'limite_plan_excedido'}));

      expect(error.tipo, TipoErrorApp.limitePlanExcedido);
      expect(error.mensaje, _mensajeLimite);
    });

    test('409 genérico: conflicto con el mensaje del backend', () {
      final error = ErrorApp.desde(_conRespuesta(409, cuerpo: {'detail': 'Solo quedan 2 unidades disponibles'}));

      expect(error.tipo, TipoErrorApp.conflicto);
      expect(error.estado, 409);
      expect(error.mensaje, 'Solo quedan 2 unidades disponibles');
      expect(error.detalle, 'Solo quedan 2 unidades disponibles');
    });

    test('409 sin detail: conflicto con el mensaje por defecto', () {
      final error = ErrorApp.desde(_conRespuesta(409));

      expect(error.tipo, TipoErrorApp.conflicto);
      expect(error.mensaje, 'La operación no se pudo completar. Intenta de nuevo.');
      expect(error.detalle, isNull);
    });

    test('401: no autorizado', () {
      final error = ErrorApp.desde(_conRespuesta(401, cuerpo: {'detail': 'Token inválido o expirado'}));

      expect(error.tipo, TipoErrorApp.noAutorizado);
      expect(error.estado, 401);
      expect(error.mensaje, 'Tu sesión venció. Inicia sesión de nuevo.');
    });

    test('404: no encontrado, con el mensaje del backend o el por defecto', () {
      final conDetalle = ErrorApp.desde(_conRespuesta(404, cuerpo: {'detail': 'Producto no encontrado'}));
      final sinDetalle = ErrorApp.desde(_conRespuesta(404));

      expect(conDetalle.tipo, TipoErrorApp.noEncontrado);
      expect(conDetalle.mensaje, 'Producto no encontrado');
      expect(sinDetalle.tipo, TipoErrorApp.noEncontrado);
      expect(sinDetalle.mensaje, 'No encontramos lo que buscabas.');
    });

    test('422: validación con mensaje fijo, sin mostrar la lista técnica de campos', () {
      final error = ErrorApp.desde(
        _conRespuesta(
          422,
          cuerpo: {
            'detail': [
              {'loc': ['body', 'email'], 'msg': 'field required'},
            ],
          },
        ),
      );

      expect(error.tipo, TipoErrorApp.validacion);
      expect(error.mensaje, 'Revisa los datos e intenta de nuevo.');
      expect(error.detalle, isNull, reason: 'detail no es texto: no se guarda');
    });

    test('422 con detail en texto también usa el mensaje fijo', () {
      final error = ErrorApp.desde(_conRespuesta(422, cuerpo: {'detail': 'campo inválido'}));

      expect(error.tipo, TipoErrorApp.validacion);
      expect(error.mensaje, 'Revisa los datos e intenta de nuevo.');
    });

    test('500 y 503: servidor', () {
      for (final estado in [500, 503]) {
        final error = ErrorApp.desde(_conRespuesta(estado, cuerpo: {'detail': 'traza interna'}));

        expect(error.tipo, TipoErrorApp.servidor);
        expect(error.estado, estado);
        expect(error.mensaje, 'El servidor no pudo responder. Intenta de nuevo en unos minutos.');
      }
    });

    test('otro 4xx sin tipo propio: desconocido con el mensaje del backend o el por defecto', () {
      final conDetalle = ErrorApp.desde(_conRespuesta(400, cuerpo: {'detail': 'Petición mal formada'}));
      final sinDetalle = ErrorApp.desde(_conRespuesta(418));

      expect(conDetalle.tipo, TipoErrorApp.desconocido);
      expect(conDetalle.mensaje, 'Petición mal formada');
      expect(sinDetalle.tipo, TipoErrorApp.desconocido);
      expect(sinDetalle.mensaje, _mensajeInesperado);
    });

    test('un cuerpo que no es un mapa no rompe la traducción', () {
      final error = ErrorApp.desde(_conRespuesta(500, cuerpo: '<html>Bad Gateway</html>'));

      expect(error.tipo, TipoErrorApp.servidor);
      expect(error.detalle, isNull);
    });
  });

  group('ErrorApp.desde - sin respuesta del servidor', () {
    test('timeout de conexión, envío o respuesta: sin conexión', () {
      for (final tipo in [
        DioExceptionType.connectionTimeout,
        DioExceptionType.sendTimeout,
        DioExceptionType.receiveTimeout,
      ]) {
        final error = ErrorApp.desde(_sinRespuesta(tipo));

        expect(error.tipo, TipoErrorApp.sinConexion, reason: '$tipo');
        expect(error.mensaje, _mensajeSinConexion);
        expect(error.estado, isNull);
      }
    });

    test('connectionError: sin conexión', () {
      final error = ErrorApp.desde(_sinRespuesta(DioExceptionType.connectionError));

      expect(error.tipo, TipoErrorApp.sinConexion);
      expect(error.mensaje, _mensajeSinConexion);
    });

    test('otro tipo de DioException sin respuesta: desconocido', () {
      for (final tipo in [DioExceptionType.cancel, DioExceptionType.badCertificate]) {
        final error = ErrorApp.desde(_sinRespuesta(tipo));

        expect(error.tipo, TipoErrorApp.desconocido, reason: '$tipo');
        expect(error.mensaje, _mensajeInesperado);
        expect(error.estado, isNull);
      }
    });
  });

  group('ErrorApp.desde - otras excepciones', () {
    test('un ErrorApp se devuelve tal cual', () {
      const original = ErrorApp(tipo: TipoErrorApp.conflicto, mensaje: 'x', estado: 409);

      expect(identical(ErrorApp.desde(original), original), isTrue);
    });

    test('una excepción que no es de Dio: desconocido con el mensaje genérico', () {
      final error = ErrorApp.desde(StateError('algo'));

      expect(error.tipo, TipoErrorApp.desconocido);
      expect(error.mensaje, _mensajeInesperado);
      expect(error.estado, isNull);
      expect(error.codigo, isNull);
    });

    test('esFuncional es falso para los tipos no funcionales', () {
      for (final tipo in [
        TipoErrorApp.sinConexion,
        TipoErrorApp.noAutorizado,
        TipoErrorApp.prohibido,
        TipoErrorApp.noEncontrado,
        TipoErrorApp.conflicto,
        TipoErrorApp.validacion,
        TipoErrorApp.servidor,
        TipoErrorApp.desconocido,
      ]) {
        expect(ErrorApp(tipo: tipo, mensaje: 'x').esFuncional, isFalse, reason: '$tipo');
      }
    });
  });
}
