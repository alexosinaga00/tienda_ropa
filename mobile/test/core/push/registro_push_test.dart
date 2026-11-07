import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/push/dispositivos_push_repository.dart';
import 'package:mobile/core/push/registro_push.dart';

import '../../helpers/api_client_falso.dart';
import '../../helpers/push_falso.dart';

const _sinRed = ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Sin conexión.');

/// Una baja que nunca termina (el servidor no contesta): para comprobar que cerrar sesión no se cuelga.
class _RepositorioColgado extends DispositivosPushRepository {
  _RepositorioColgado(super.api);

  @override
  Future<void> baja(String token) => Completer<void>().future;
}

/// El servicio, el almacén y el servidor falsos. Las respuestas del servidor se entregan en orden y la última se repite.
class _Mundo {
  _Mundo({
    bool permiso = true,
    bool concedeAlPedir = true,
    String? token = 'TOKEN-A',
    String? pendiente,
    List<Object?> altas = const [null],
    List<Object?> bajas = const [null],
  }) : servicio = ServicioPushFalso(permiso: permiso, concedeAlPedir: concedeAlPedir, token: token),
       almacen = AlmacenPushFalso(pendiente: pendiente) {
    for (final respuesta in altas) {
      api.responder('POST', '/dispositivos-push', respuesta);
    }
    for (final respuesta in bajas) {
      api.responder('POST', '/dispositivos-push/baja', respuesta);
    }
    registro = RegistroPush(
      servicio: servicio,
      repositorio: DispositivosPushRepository(() => api),
      almacen: almacen,
      esperaBaja: const Duration(milliseconds: 50),
    );
  }

  final ServicioPushFalso servicio;
  final AlmacenPushFalso almacen;
  final ApiClientFalso api = ApiClientFalso();
  late final RegistroPush registro;

  List<LlamadaApi> get altas => api.de('POST', '/dispositivos-push');
  List<LlamadaApi> get bajas => api.de('POST', '/dispositivos-push/baja');
}

void main() {
  group('alta del token', () {
    test('al iniciar sesión envía el token y la plataforma android', () async {
      final m = _Mundo();

      await m.registro.alIniciarSesion();

      expect(m.altas, hasLength(1));
      expect(m.altas.single.cuerpo, {'token': 'TOKEN-A', 'plataforma': 'android'});
      expect(m.registro.registrado, isTrue);
      expect(m.almacen.registrado, 'TOKEN-A', reason: 'se recuerda para poder darlo de baja después');
    });

    test('sin permiso y sin pedirlo no registra nada y no pregunta', () async {
      final m = _Mundo(permiso: false);

      await m.registro.alIniciarSesion();

      expect(m.altas, isEmpty);
      expect(m.servicio.permisosPedidos, 0);
    });

    test('pidiendo el permiso: si lo conceden, registra', () async {
      final m = _Mundo(permiso: false);

      await m.registro.alIniciarSesion(pedirPermiso: true);

      expect(m.servicio.permisosPedidos, 1);
      expect(m.altas, hasLength(1));
    });

    test('permiso denegado: no registra, no lanza y nada queda bloqueado', () async {
      final m = _Mundo(permiso: false, concedeAlPedir: false);

      await m.registro.alIniciarSesion(pedirPermiso: true);

      expect(m.servicio.permisosPedidos, 1);
      expect(m.altas, isEmpty);
      expect(m.registro.registrado, isFalse);
    });

    test('con el permiso ya concedido no vuelve a pedirlo', () async {
      final m = _Mundo();

      await m.registro.alIniciarSesion(pedirPermiso: true);

      expect(m.servicio.permisosPedidos, 0);
    });

    test('sin token (Firebase no lo da) no registra', () async {
      final m = _Mundo(token: null);

      await m.registro.alIniciarSesion();

      expect(m.altas, isEmpty);
    });

    test('un fallo dentro de Firebase no se propaga', () async {
      final m = _Mundo();
      m.servicio.fallaAlObtenerToken = true;

      await m.registro.alIniciarSesion();

      expect(m.altas, isEmpty);
    });

    test('si el servidor no responde, no lanza y se reintenta al volver la conexión', () async {
      final m = _Mundo(altas: [_sinRed, null]);

      await m.registro.alIniciarSesion();
      expect(m.registro.registrado, isFalse);

      await m.registro.alVolverConexion();
      expect(m.registro.registrado, isTrue);
      expect(m.altas, hasLength(2));
    });

    test('al volver la conexión, si ya estaba registrado no repite el alta', () async {
      final m = _Mundo();
      await m.registro.alIniciarSesion();

      await m.registro.alVolverConexion();

      expect(m.altas, hasLength(1));
    });

    test('al entrar a notificaciones pide el permiso si falta y registra', () async {
      final m = _Mundo(permiso: false);

      await m.registro.alEntrarANotificaciones();

      expect(m.servicio.permisosPedidos, 1);
      expect(m.altas, hasLength(1));
    });

    test('al entrar a notificaciones ya registrado no hace nada', () async {
      final m = _Mundo();
      await m.registro.alIniciarSesion();

      await m.registro.alEntrarANotificaciones();

      expect(m.altas, hasLength(1));
    });
  });

  group('token que cambia', () {
    test('reenvía el token nuevo', () async {
      final m = _Mundo();
      await m.registro.alIniciarSesion();

      await m.registro.alRefrescarToken('TOKEN-B');

      expect(m.altas.map((l) => (l.cuerpo! as Map)['token']), ['TOKEN-A', 'TOKEN-B']);
      expect(m.almacen.registrado, 'TOKEN-B');
    });

    test('un fallo de red al reenviar no lanza', () async {
      final m = _Mundo(altas: [null, _sinRed]);
      await m.registro.alIniciarSesion();

      await m.registro.alRefrescarToken('TOKEN-B');

      expect(m.altas, hasLength(2));
    });
  });

  group('baja al cerrar sesión', () {
    test('con red avisa al servidor y no deja nada pendiente', () async {
      final m = _Mundo();
      await m.registro.alIniciarSesion();

      await m.registro.alCerrarSesion();

      expect(m.bajas, hasLength(1));
      expect(m.bajas.single.cuerpo, {'token': 'TOKEN-A'});
      expect(m.almacen.pendiente, isNull);
      expect(m.almacen.registrado, isNull);
      expect(m.registro.registrado, isFalse);
    });

    test('sin red no bloquea el cierre y deja la baja pendiente', () async {
      final m = _Mundo(bajas: [_sinRed]);
      await m.registro.alIniciarSesion();

      await m.registro.alCerrarSesion();

      expect(m.almacen.pendiente, 'TOKEN-A');
      expect(m.almacen.registrado, isNull);
    });

    test('si el servidor no contesta, tras la espera máxima deja la baja pendiente', () async {
      final m = _Mundo();
      final registro = RegistroPush(
        servicio: m.servicio,
        repositorio: _RepositorioColgado(() => m.api),
        almacen: m.almacen,
        esperaBaja: const Duration(milliseconds: 30),
      );
      await registro.alIniciarSesion();

      await registro.alCerrarSesion();

      expect(m.almacen.pendiente, 'TOKEN-A');
    });

    test('con la sesión vencida ni lo intenta (pedirla dispararía otro cierre) y queda pendiente', () async {
      final m = _Mundo();
      await m.registro.alIniciarSesion();

      await m.registro.alCerrarSesion(intentarBaja: false);

      expect(m.bajas, isEmpty);
      expect(m.almacen.pendiente, 'TOKEN-A');
    });

    test('si nunca se registró nada no hay baja', () async {
      final m = _Mundo(permiso: false);
      await m.registro.alIniciarSesion();

      await m.registro.alCerrarSesion();

      expect(m.bajas, isEmpty);
      expect(m.almacen.pendiente, isNull);
    });

    test('usa el token guardado si la app se reinició antes de cerrar la sesión', () async {
      final m = _Mundo();
      m.almacen.registrado = 'TOKEN-VIEJO';

      await m.registro.alCerrarSesion();

      expect(m.bajas.single.cuerpo, {'token': 'TOKEN-VIEJO'});
    });
  });

  group('baja pendiente', () {
    test('el mismo token en el siguiente inicio de sesión: se olvida la baja y no se duplica', () async {
      final m = _Mundo(pendiente: 'TOKEN-A');

      await m.registro.alIniciarSesion();

      expect(m.bajas, isEmpty, reason: 'la baja desactivaría el alta recién hecha');
      expect(m.altas, hasLength(1));
      expect(m.almacen.pendiente, isNull);
    });

    test('otro token: se pide su baja, se limpia y luego se hace el alta', () async {
      final m = _Mundo(pendiente: 'TOKEN-VIEJO');

      await m.registro.alIniciarSesion();

      expect(m.bajas.single.cuerpo, {'token': 'TOKEN-VIEJO'});
      expect(m.almacen.pendiente, isNull);
      expect(m.altas, hasLength(1));
    });

    test('otro token y sin red para la baja: se conserva para la próxima y el alta sigue', () async {
      final m = _Mundo(pendiente: 'TOKEN-VIEJO', bajas: [_sinRed]);

      await m.registro.alIniciarSesion();

      expect(m.almacen.pendiente, 'TOKEN-VIEJO');
      expect(m.altas, hasLength(1));
    });

    test('cerrar sin red y volver a entrar: una sola baja intentada, sin duplicados', () async {
      final m = _Mundo(bajas: [_sinRed]);
      await m.registro.alIniciarSesion();
      await m.registro.alCerrarSesion();
      expect(m.almacen.pendiente, 'TOKEN-A');

      await m.registro.alIniciarSesion();

      expect(m.almacen.pendiente, isNull);
      expect(m.bajas, hasLength(1), reason: 'solo el intento fallido del cierre');
      expect(m.altas, hasLength(2));
    });
  });
}
