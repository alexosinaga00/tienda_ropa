import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/network/mensaje_error.dart';

DioException _error(DioExceptionType tipo, {int? estado, Object? cuerpo}) {
  final opciones = RequestOptions(path: '/prueba');
  return DioException(
    requestOptions: opciones,
    type: tipo,
    response: estado == null ? null : Response(requestOptions: opciones, statusCode: estado, data: cuerpo),
  );
}

void main() {
  group('esSinConexion', () {
    for (final tipo in [
      DioExceptionType.connectionError,
      DioExceptionType.connectionTimeout,
      DioExceptionType.sendTimeout,
      DioExceptionType.receiveTimeout,
    ]) {
      test('es verdadero para $tipo', () {
        expect(esSinConexion(_error(tipo)), isTrue);
      });
    }

    test('es falso para una respuesta del backend, una cancelación o un error que no es de Dio', () {
      expect(esSinConexion(_error(DioExceptionType.badResponse, estado: 500)), isFalse);
      expect(esSinConexion(_error(DioExceptionType.cancel)), isFalse);
      expect(esSinConexion(Exception('x')), isFalse);
    });
  });

  group('esNoEncontrado', () {
    test('es verdadero solo con un 404 del backend', () {
      expect(esNoEncontrado(_error(DioExceptionType.badResponse, estado: 404)), isTrue);
      expect(esNoEncontrado(_error(DioExceptionType.badResponse, estado: 409)), isFalse);
      expect(esNoEncontrado(_error(DioExceptionType.connectionError)), isFalse);
      expect(esNoEncontrado(Exception('404')), isFalse);
    });
  });

  group('esErrorDeServidor', () {
    test('es verdadero con 5xx y falso con otros estados o sin respuesta', () {
      expect(esErrorDeServidor(_error(DioExceptionType.badResponse, estado: 500)), isTrue);
      expect(esErrorDeServidor(_error(DioExceptionType.badResponse, estado: 503)), isTrue);
      expect(esErrorDeServidor(_error(DioExceptionType.badResponse, estado: 401)), isFalse);
      expect(esErrorDeServidor(_error(DioExceptionType.connectionError)), isFalse);
      expect(esErrorDeServidor(Exception('500')), isFalse);
    });
  });

  group('esConflicto y mensajeDeError', () {
    test('esConflicto reconoce el 409', () {
      expect(esConflicto(_error(DioExceptionType.badResponse, estado: 409)), isTrue);
      expect(esConflicto(_error(DioExceptionType.badResponse, estado: 404)), isFalse);
    });

    test('mensajeDeError usa el detail del backend y, si no hay, el mensaje por defecto', () {
      final conDetalle = _error(DioExceptionType.badResponse, estado: 400, cuerpo: {'detail': 'Solo quedan 2'});
      expect(mensajeDeError(conDetalle, 'por defecto'), 'Solo quedan 2');
      expect(mensajeDeError(_error(DioExceptionType.connectionError), 'por defecto'), 'por defecto');
      expect(mensajeDeError(Exception('x'), 'por defecto'), 'por defecto');
    });
  });

  group('mensajeDeError - códigos funcionales', () {
    const mensajePlan = 'Tu plan no incluye esta función. Consulta con el administrador de tu empresa.';
    const mensajeSuscripcion = 'La suscripción de esta tienda no está activa. Contacta al administrador de la tienda.';
    const mensajeLimite = 'Tu empresa alcanzó el límite de su plan.';

    test('un DioException con un código funcional da el texto amigable fijo', () {
      final plan = _error(
        DioExceptionType.badResponse,
        estado: 403,
        cuerpo: {'detail': 'plan_no_incluye_funcionalidad'},
      );
      final suscripcion = _error(
        DioExceptionType.badResponse,
        estado: 403,
        cuerpo: {'detail': 'suscripcion_no_activa'},
      );
      final limite = _error(
        DioExceptionType.badResponse,
        estado: 409,
        cuerpo: {'detail': 'x', 'codigo': 'limite_plan_excedido', 'mensaje': 'texto técnico'},
      );

      expect(mensajeDeError(plan, 'por defecto'), mensajePlan);
      expect(mensajeDeError(suscripcion, 'por defecto'), mensajeSuscripcion);
      expect(mensajeDeError(limite, 'por defecto'), mensajeLimite);
    });

    test('un ErrorApp funcional da su texto fijo', () {
      final error = ErrorApp.desde(_error(DioExceptionType.badResponse, estado: 403, cuerpo: {'detail': 'suscripcion_no_activa'}));

      expect(mensajeDeError(error, 'por defecto'), mensajeSuscripcion);
    });

    test('un ErrorApp no funcional usa su detalle y, si no tiene, el mensaje por defecto', () {
      final conDetalle = ErrorApp.desde(
        _error(DioExceptionType.badResponse, estado: 409, cuerpo: {'detail': 'Solo quedan 2'}),
      );
      final sinDetalle = ErrorApp.desde(_error(DioExceptionType.badResponse, estado: 500));
      final sinRed = ErrorApp.desde(_error(DioExceptionType.connectionError));

      expect(mensajeDeError(conDetalle, 'por defecto'), 'Solo quedan 2');
      expect(mensajeDeError(sinDetalle, 'por defecto'), 'por defecto');
      expect(mensajeDeError(sinRed, 'por defecto'), 'por defecto');
    });
  });

  group('helpers que aceptan ErrorApp', () {
    ErrorApp con(int estado, {Object? cuerpo}) =>
        ErrorApp.desde(_error(DioExceptionType.badResponse, estado: estado, cuerpo: cuerpo));

    test('esConflicto, esNoEncontrado y esErrorDeServidor miran el estado del ErrorApp', () {
      expect(esConflicto(con(409)), isTrue);
      expect(esConflicto(con(404)), isFalse);
      expect(esNoEncontrado(con(404)), isTrue);
      expect(esNoEncontrado(con(409)), isFalse);
      expect(esErrorDeServidor(con(500)), isTrue);
      expect(esErrorDeServidor(con(503)), isTrue);
      expect(esErrorDeServidor(con(401)), isFalse);
    });

    test('esSinConexion reconoce un ErrorApp sinConexion y no otro', () {
      expect(esSinConexion(ErrorApp.desde(_error(DioExceptionType.connectionTimeout))), isTrue);
      expect(esSinConexion(ErrorApp.desde(_error(DioExceptionType.connectionError))), isTrue);
      expect(esSinConexion(con(500)), isFalse);
      expect(esSinConexion(ErrorApp.desde(Exception('x'))), isFalse);
    });

    test('un ErrorApp sin estado no es conflicto, ni no encontrado, ni error de servidor', () {
      final sinRed = ErrorApp.desde(_error(DioExceptionType.connectionError));

      expect(esConflicto(sinRed), isFalse);
      expect(esNoEncontrado(sinRed), isFalse);
      expect(esErrorDeServidor(sinRed), isFalse);
    });

    test('esPlanNoIncluye, esSuscripcionNoActiva y esLimitePlan aceptan ErrorApp y DioException', () {
      final plan = _error(DioExceptionType.badResponse, estado: 403, cuerpo: {'detail': 'plan_no_incluye_funcionalidad'});
      final suscripcion = _error(DioExceptionType.badResponse, estado: 403, cuerpo: {'codigo': 'suscripcion_no_activa'});
      final limite = _error(DioExceptionType.badResponse, estado: 409, cuerpo: {'codigo': 'limite_plan_excedido'});

      for (final entrada in [plan, ErrorApp.desde(plan)]) {
        expect(esPlanNoIncluye(entrada), isTrue);
        expect(esSuscripcionNoActiva(entrada), isFalse);
        expect(esLimitePlan(entrada), isFalse);
      }
      for (final entrada in [suscripcion, ErrorApp.desde(suscripcion)]) {
        expect(esSuscripcionNoActiva(entrada), isTrue);
        expect(esPlanNoIncluye(entrada), isFalse);
      }
      for (final entrada in [limite, ErrorApp.desde(limite)]) {
        expect(esLimitePlan(entrada), isTrue);
        expect(esPlanNoIncluye(entrada), isFalse);
      }
    });

    test('los helpers funcionales son falsos para un 403/409 común y para una excepción cualquiera', () {
      final prohibido = _error(DioExceptionType.badResponse, estado: 403, cuerpo: {'detail': 'Sin permiso'});
      final conflicto = _error(DioExceptionType.badResponse, estado: 409, cuerpo: {'detail': 'Solo quedan 2'});

      expect(esPlanNoIncluye(prohibido), isFalse);
      expect(esSuscripcionNoActiva(prohibido), isFalse);
      expect(esLimitePlan(conflicto), isFalse);
      expect(esLimitePlan(Exception('x')), isFalse);
      expect(esPlanNoIncluye(Exception('x')), isFalse);
    });
  });
}
