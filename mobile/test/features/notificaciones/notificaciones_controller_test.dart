import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/notificaciones/state/notificaciones_controller.dart';

import 'apoyo_notificaciones.dart';

ProviderContainer _contenedor(RepositorioNotificacionesFalso repositorio, {bool autenticado = true}) {
  final contenedor = ProviderContainer(overrides: overridesNotificaciones(repositorio, autenticado: autenticado));
  addTearDown(contenedor.dispose);
  // Se mantiene vivo (como en la app, donde la campana lo escucha) para que reaccione al cambio de sesión.
  contenedor.listen(notificacionesProvider, (anterior, siguiente) {});
  return contenedor;
}

Future<void> _esperar() => Future<void>.delayed(Duration.zero);

void main() {
  group('NotificacionesController', () {
    test('con sesión carga la lista al crearse y cuenta las no leídas', () async {
      final repositorio = RepositorioNotificacionesFalso([
        notificacion(1),
        notificacion(2, leida: true),
        notificacion(3),
      ]);
      final contenedor = _contenedor(repositorio);
      expect(contenedor.read(notificacionesProvider).isLoading, isTrue);

      await _esperar();

      expect(contenedor.read(notificacionesProvider).value, hasLength(3));
      expect(contenedor.read(notificacionesNoLeidasProvider), 2);
    });

    test('sin sesión no consulta al backend y queda vacía', () async {
      final repositorio = RepositorioNotificacionesFalso([notificacion(1)]);
      final contenedor = _contenedor(repositorio, autenticado: false);

      await contenedor.read(notificacionesProvider.notifier).refrescar();
      await _esperar();

      expect(repositorio.consultas, 0);
      expect(contenedor.read(notificacionesProvider).value, isEmpty);
      expect(contenedor.read(notificacionesNoLeidasProvider), 0);
    });

    test('marcarLeida la marca al instante y avisa al backend', () async {
      final repositorio = RepositorioNotificacionesFalso([notificacion(1), notificacion(2)]);
      final contenedor = _contenedor(repositorio);
      await _esperar();

      final pendiente = contenedor.read(notificacionesProvider.notifier).marcarLeida(1);
      expect(contenedor.read(notificacionesNoLeidasProvider), 1); // antes de que responda el backend
      await pendiente;

      expect(repositorio.marcadas, [1]);
      expect(contenedor.read(notificacionesNoLeidasProvider), 1);
    });

    test('si el backend falla al marcar, la notificación vuelve a quedar sin leer', () async {
      final repositorio = RepositorioNotificacionesFalso([notificacion(1)]);
      final contenedor = _contenedor(repositorio);
      await _esperar();
      repositorio.fallaMarcar = true;

      await contenedor.read(notificacionesProvider.notifier).marcarLeida(1);

      expect(contenedor.read(notificacionesNoLeidasProvider), 1);
      expect(repositorio.marcadas, isEmpty);
    });

    test('marcarTodasLeidas deja el contador en cero y solo marca las pendientes', () async {
      final repositorio = RepositorioNotificacionesFalso([
        notificacion(1),
        notificacion(2, leida: true),
        notificacion(3),
      ]);
      final contenedor = _contenedor(repositorio);
      await _esperar();

      await contenedor.read(notificacionesProvider.notifier).marcarTodasLeidas();

      expect(contenedor.read(notificacionesNoLeidasProvider), 0);
      expect(repositorio.marcadas, unorderedEquals([1, 3]));
    });

    test('refrescar trae lo nuevo', () async {
      final repositorio = RepositorioNotificacionesFalso([notificacion(1)]);
      final contenedor = _contenedor(repositorio);
      await _esperar();

      repositorio.servidor = [notificacion(2), notificacion(1)];
      await contenedor.read(notificacionesProvider.notifier).refrescar();

      expect(contenedor.read(notificacionesProvider).value, hasLength(2));
      expect(contenedor.read(notificacionesNoLeidasProvider), 2);
    });

    test('un error de red al refrescar conserva la lista que ya había', () async {
      final repositorio = RepositorioNotificacionesFalso([notificacion(1), notificacion(2)]);
      final contenedor = _contenedor(repositorio);
      await _esperar();
      repositorio.fallaListar = true;

      await contenedor.read(notificacionesProvider.notifier).refrescar();

      expect(contenedor.read(notificacionesProvider).hasError, isFalse);
      expect(contenedor.read(notificacionesProvider).value, hasLength(2));
    });

    test('si la primera carga falla queda el error, y un nuevo intento lo recupera', () async {
      final repositorio = RepositorioNotificacionesFalso([notificacion(1)])..fallaListar = true;
      final contenedor = _contenedor(repositorio);
      await _esperar();
      expect(contenedor.read(notificacionesProvider).hasError, isTrue);
      expect(contenedor.read(notificacionesNoLeidasProvider), 0);

      repositorio.fallaListar = false;
      await contenedor.read(notificacionesProvider.notifier).refrescar();

      expect(contenedor.read(notificacionesProvider).value, hasLength(1));
    });

    test('al cerrar sesión se vacía, y el siguiente cliente empieza de cero', () async {
      final repositorio = RepositorioNotificacionesFalso([notificacion(1), notificacion(2)]);
      final contenedor = _contenedor(repositorio);
      await _esperar();
      expect(contenedor.read(notificacionesNoLeidasProvider), 2);
      final consultasAntes = repositorio.consultas;

      (contenedor.read(authControllerProvider.notifier) as AuthFalso).poner(false);
      await _esperar();

      expect(contenedor.read(notificacionesProvider).value, isEmpty);
      expect(contenedor.read(notificacionesNoLeidasProvider), 0);
      expect(repositorio.consultas, consultasAntes); // cerrar sesión no consulta nada
    });
  });
}
