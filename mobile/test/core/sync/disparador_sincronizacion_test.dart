import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/core/sync/disparador_sincronizacion.dart';
import 'package:mobile/core/sync/motor_sincronizacion.dart';
import 'package:mobile/core/sync/operacion_pendiente.dart';
import 'package:mobile/core/utils/reloj.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';
import 'package:mobile/features/vendedor/state/sincronizacion_providers.dart';

import '../../features/vendedor/apoyo_vendedor.dart';
import '../../helpers/cola_falsa.dart';
import '../../helpers/conectividad_falsa.dart';
import '../../helpers/sincronizacion_api_falsa.dart';

/// Un mundo con el disparador montado, un motor REAL sobre la cola y la API de mentira, y una conexión controlable.
class _Mundo {
  _Mundo({required this.estadoAuth, bool enLinea = true, List<OperacionPendiente> operaciones = const []})
    : conectividad = ConectividadFalsa(enLinea: enLinea),
      cola = ColaFalsa(operaciones),
      api = SincronizacionApiFalsa(),
      conteo = StreamController<Map<EstadoOperacion, int>>.broadcast();

  final AuthState estadoAuth;
  final ConectividadFalsa conectividad;
  final ColaFalsa cola;
  final SincronizacionApiFalsa api;
  final StreamController<Map<EstadoOperacion, int>> conteo;

  Future<void> montar(WidgetTester tester) async {
    final motor = MotorSincronizacion(
      cola: cola,
      api: api,
      reloj: const RelojSistema(),
      conectividad: conectividad,
      dispositivoId: () async => 'dispositivo-de-prueba',
    );
    addTearDown(() async {
      motor.dispose();
      await conteo.close();
      await conectividad.cerrar();
    });
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authControllerProvider.overrideWith((ref) => AuthControllerFalso(ref, estadoAuth)),
          conectividadServiceProvider.overrideWithValue(conectividad),
          motorSincronizacionProvider.overrideWith((ref) async => motor),
          conteoOperacionesProvider.overrideWith((ref) => conteo.stream),
        ],
        child: MaterialApp(
          scaffoldMessengerKey: mensajeroGlobal,
          home: const Scaffold(
            body: DisparadorSincronizacion(
              esperaConexion: Duration(seconds: 3),
              intervalo: Duration(seconds: 60),
              child: Text('PANTALLA'),
            ),
          ),
        ),
      ),
    );
    await tester.pump();
  }

  /// Anuncia cuántas hay en cada estado (lo que emitiría la cola real tras un cambio).
  Future<void> contar(WidgetTester tester, {int registradas = 0}) async {
    conteo.add({for (final e in EstadoOperacion.values) e: e == EstadoOperacion.registrada ? registradas : 0});
    await tester.pump();
    await tester.pump();
  }
}

OperacionPendiente _op(String id) {
  final u = sesionDePersonal().usuario!;
  return operacionDePrueba(id, empresaId: u.empresaId!, usuarioId: u.id);
}

const _id = '11111111-1111-4111-8111-111111111111';

void main() {
  group('textoDelResumen', () {
    ResumenSync resumen({int confirmadas = 0, int rechazadas = 0, int enConflicto = 0, bool intentado = true}) => ResumenSync(
      confirmadas: confirmadas,
      rechazadas: rechazadas,
      enConflicto: enConflicto,
      enviadas: confirmadas + rechazadas + enConflicto,
      intentado: intentado,
    );

    test('una confirmada y varias confirmadas', () {
      expect(textoDelResumen(resumen(confirmadas: 1)), '1 operación sincronizada');
      expect(textoDelResumen(resumen(confirmadas: 3)), '3 operaciones sincronizadas');
    });

    test('lo que necesita atención manda sobre lo confirmado', () {
      expect(textoDelResumen(resumen(confirmadas: 2, rechazadas: 1)), '1 operación necesita atención');
      expect(textoDelResumen(resumen(enConflicto: 1, rechazadas: 1)), '2 operaciones necesitan atención');
    });

    test('sin cambios o sin haber intentado no hay nada que decir', () {
      expect(textoDelResumen(resumen(confirmadas: 2, intentado: false)), isNull);
      expect(textoDelResumen(resumen()), isNull);
    });
  });

  group('DisparadorSincronizacion', () {
    testWidgets('al volver la conexión espera 3 s y sincroniza una vez', (tester) async {
      final m = _Mundo(estadoAuth: sesionDePersonal(), enLinea: false, operaciones: [_op(_id)]);
      await m.montar(tester);

      m.conectividad.emitir(true);
      await tester.pump();
      await tester.pump(const Duration(seconds: 2));
      expect(m.api.lotes, isEmpty, reason: 'todavía no pasaron los 3 s');

      await tester.pump(const Duration(seconds: 2));
      await tester.pump();
      expect(m.api.lotes, hasLength(1));
      expect(m.cola.fila(_id).estado, EstadoOperacion.confirmada);
    });

    testWidgets('si la conexión cae y vuelve varias veces seguidas no hace peticiones repetidas', (tester) async {
      final m = _Mundo(estadoAuth: sesionDePersonal(), enLinea: false, operaciones: [_op(_id)]);
      await m.montar(tester);

      m.conectividad.emitir(true);
      await tester.pump(const Duration(seconds: 1));
      m.conectividad.emitir(false);
      await tester.pump();
      m.conectividad.emitir(true);
      await tester.pump(const Duration(seconds: 4));
      await tester.pump();

      expect(m.api.lotes, hasLength(1));
    });

    testWidgets('al registrar una operación nueva sincroniza', (tester) async {
      final m = _Mundo(estadoAuth: sesionDePersonal(), operaciones: [_op(_id)]);
      await m.montar(tester);
      await m.contar(tester, registradas: 0);
      expect(m.api.lotes, isEmpty);

      await m.contar(tester, registradas: 1);
      await tester.pump();

      expect(m.api.lotes, hasLength(1));
    });

    testWidgets('una cantidad que baja (se confirmó una) no dispara otra sincronización', (tester) async {
      final m = _Mundo(estadoAuth: sesionDePersonal());
      await m.montar(tester);
      await m.contar(tester, registradas: 2);
      final antes = m.api.lotes.length;

      await m.contar(tester, registradas: 1);
      await tester.pump();

      expect(m.api.lotes.length, antes);
    });

    testWidgets('el temporizador de 60 s reintenta solo si hay pendientes', (tester) async {
      final m = _Mundo(estadoAuth: sesionDePersonal(), operaciones: [_op(_id)]);
      await m.montar(tester);
      // Sin saber de pendientes (la cola aún no emitió nada) no dispara.
      await tester.pump(const Duration(seconds: 61));
      expect(m.api.lotes, isEmpty);

      await m.contar(tester, registradas: 1); // dispara por "registro"
      final despuesDelRegistro = m.api.lotes.length;
      m.cola.sembrar(_op('22222222-2222-4222-8222-222222222222'));
      await tester.pump(const Duration(seconds: 61));
      await tester.pump();

      expect(m.api.lotes.length, greaterThan(despuesDelRegistro));
    });

    testWidgets('el temporizador no hace nada si no hay pendientes', (tester) async {
      final m = _Mundo(estadoAuth: sesionDePersonal());
      await m.montar(tester);
      await m.contar(tester, registradas: 0);

      await tester.pump(const Duration(seconds: 125));

      expect(m.api.lotes, isEmpty);
    });

    testWidgets('al volver la app al primer plano sincroniza', (tester) async {
      final m = _Mundo(estadoAuth: sesionDePersonal(), operaciones: [_op(_id)]);
      await m.montar(tester);

      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump();
      await tester.pump();

      expect(m.api.lotes, hasLength(1));
    });

    testWidgets('sin sesión no dispara nada', (tester) async {
      final m = _Mundo(
        estadoAuth: const AuthState(estado: EstadoSesion.noAutenticado),
        enLinea: false,
        operaciones: [_op(_id)],
      );
      await m.montar(tester);

      m.conectividad.emitir(true);
      await tester.pump(const Duration(seconds: 4));
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await m.contar(tester, registradas: 1);
      await tester.pump(const Duration(seconds: 70));

      expect(m.api.lotes, isEmpty);
    });

    testWidgets('un cliente con sesión tampoco dispara nada (la sincronización es del personal)', (tester) async {
      final m = _Mundo(
        estadoAuth: AuthState(estado: EstadoSesion.autenticado, usuario: usuarioDePrueba(roles: ['cliente'], permisos: [])),
        enLinea: false,
        operaciones: [_op(_id)],
      );
      await m.montar(tester);

      m.conectividad.emitir(true);
      await tester.pump(const Duration(seconds: 4));
      await m.contar(tester, registradas: 1);

      expect(m.api.lotes, isEmpty);
    });

    testWidgets('tras sincronizar avisa con un SnackBar', (tester) async {
      final m = _Mundo(estadoAuth: sesionDePersonal(), enLinea: false, operaciones: [_op(_id), _op('33333333-3333-4333-8333-333333333333')]);
      await m.montar(tester);

      m.conectividad.emitir(true);
      await tester.pump(const Duration(seconds: 4));
      await tester.pump();
      await tester.pump();

      expect(find.text('2 operaciones sincronizadas'), findsOneWidget);
    });

    testWidgets('un error del servidor no tumba la app y la cola se conserva', (tester) async {
      final m = _Mundo(estadoAuth: sesionDePersonal(), operaciones: [_op(_id)]);
      m.api.porDefecto = (lote) => throw StateError('el servidor explotó');
      await m.montar(tester);

      await m.contar(tester, registradas: 1);
      await tester.pump();

      expect(tester.takeException(), isNull);
      expect(m.cola.todas, hasLength(1));
    });
  });
}
