import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/core/sync/disparador_sincronizacion.dart' show mensajeroGlobal;
import 'package:mobile/core/utils/reloj.dart';
import 'package:mobile/features/catalogo/models/referencia.dart';
import 'package:mobile/features/catalogo/state/catalogo_providers.dart';
import 'package:mobile/features/cliente_offline/data/metodo_pago_repository.dart';
import 'package:mobile/features/cliente_offline/models/linea_carrito_local.dart';
import 'package:mobile/features/cliente_offline/models/metodo_pago.dart';
import 'package:mobile/features/cliente_offline/models/pedido_sin_conexion.dart';
import 'package:mobile/features/cliente_offline/presentation/disparador_cola_pedidos.dart';
import 'package:mobile/features/cliente_offline/state/cliente_offline_providers.dart';
import 'package:mobile/features/cliente_offline/state/metodo_pago_controller.dart';

import '../../helpers/api_client_falso.dart';
import '../../helpers/cliente_offline_apoyo.dart';

final _alcanceFalso = StateProvider<AlcanceCliente?>((ref) => null);

class _MetodoContado extends MetodoPagoController {
  _MetodoContado()
    : super(() async => null, MetodoPagoRepository(ApiClientFalso()), const RelojSistema(), activo: false);

  int refrescos = 0;

  @override
  Future<MetodoPagoPaypal?> refrescar() async {
    refrescos++;
    return null;
  }
}

class _Mundo {
  _Mundo(this.cola, this.red, this.metodo, this.contenedor);

  final ColaFalsa cola;
  final StreamController<bool> red;
  final _MetodoContado metodo;
  final ProviderContainer contenedor;
}

Future<_Mundo> _montar(WidgetTester tester, {AlcanceCliente? alcance, bool enLinea = true}) async {
  final cola = ColaFalsa();
  final red = StreamController<bool>();
  final metodo = _MetodoContado();
  final contenedor = ProviderContainer(
    overrides: [
      colaPedidosProvider.overrideWithValue(cola),
      alcanceClienteProvider.overrideWith((ref) => ref.watch(_alcanceFalso)),
      enLineaProvider.overrideWith((ref) {
        ref.onDispose(red.close);
        return (() async* {
          yield enLinea;
          yield* red.stream;
        })();
      }),
      metodoPagoLocalProvider.overrideWith((ref) => metodo),
      sucursalesRefProvider.overrideWith((ref) async => const <SucursalRef>[]),
      tallasRefProvider.overrideWith((ref) async => const <TallaRef>[]),
      coloresRefProvider.overrideWith((ref) async => const <ColorRef>[]),
    ],
  );
  addTearDown(contenedor.dispose);
  contenedor.read(_alcanceFalso.notifier).state = alcance;
  // La conexión ya es conocida cuando se arma la pantalla (la real también lo es casi siempre).
  contenedor.listen(enLineaProvider, (_, _) {});
  await tester.pump();
  await tester.pump();
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: contenedor,
      child: MaterialApp(
        scaffoldMessengerKey: mensajeroGlobal,
        home: const Scaffold(
          body: DisparadorColaPedidos(
            esperaConexion: Duration(milliseconds: 10),
            intervalo: Duration(milliseconds: 50),
            child: Text('HIJO'),
          ),
        ),
      ),
    ),
  );
  await tester.pump();
  return _Mundo(cola, red, metodo, contenedor);
}

void main() {
  testWidgets('muestra a su hijo', (tester) async {
    await _montar(tester);

    expect(find.text('HIJO'), findsOneWidget);
  });

  testWidgets('si la sesión ya estaba abierta, arranca la cola de esa persona y recuerda el PayPal', (tester) async {
    final m = await _montar(tester, alcance: alcanceAna);
    await tester.pump();

    expect(m.cola.alcances, [alcanceAna]);
    expect(m.metodo.refrescos, 1);
  });

  testWidgets('cuando entra o sale una persona, la cola cambia de dueña', (tester) async {
    final m = await _montar(tester);
    m.cola.alcances.clear();

    m.contenedor.read(_alcanceFalso.notifier).state = alcanceLuis;
    await tester.pump();
    m.contenedor.read(_alcanceFalso.notifier).state = null;
    await tester.pump();

    expect(m.cola.alcances, [alcanceLuis, null]);
  });

  testWidgets('sin red no recuerda nada del PayPal', (tester) async {
    final m = await _montar(tester, alcance: alcanceAna, enLinea: false);
    await tester.pump();

    expect(m.metodo.refrescos, 0);
  });

  testWidgets('al VOLVER la conexión, tras la espera, avisa a la cola', (tester) async {
    final m = await _montar(tester, alcance: alcanceAna, enLinea: false);
    expect(m.cola.volvioConexion, 0);

    m.red.add(true);
    await tester.pump();
    expect(m.cola.volvioConexion, 0, reason: 'primero espera a que la red se asiente');
    await tester.pump(const Duration(milliseconds: 20));

    expect(m.cola.volvioConexion, 1);
    expect(m.metodo.refrescos, 1, reason: 'con red de nuevo recuerda el PayPal');
  });

  testWidgets('empezar con conexión no cuenta como "volvió"', (tester) async {
    final m = await _montar(tester, alcance: alcanceAna);

    await tester.pump(const Duration(milliseconds: 30));

    expect(m.cola.volvioConexion, 0);
  });

  testWidgets('sin sesión de cliente, volver la red no hace nada', (tester) async {
    final m = await _montar(tester, enLinea: false);

    m.red.add(true);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 20));

    expect(m.cola.volvioConexion, 0);
  });

  testWidgets('el temporizador revisa la cola mientras haya sesión', (tester) async {
    final m = await _montar(tester, alcance: alcanceAna);

    await tester.pump(const Duration(milliseconds: 120));

    expect(m.cola.procesados, greaterThanOrEqualTo(2));
  });

  testWidgets('el temporizador no hace nada sin sesión de cliente', (tester) async {
    final m = await _montar(tester);

    await tester.pump(const Duration(milliseconds: 120));

    expect(m.cola.procesados, 0);
  });

  testWidgets('al volver la app al primer plano revisa la cola', (tester) async {
    final m = await _montar(tester, alcance: alcanceAna);
    final antes = m.cola.procesados;

    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();

    expect(m.cola.procesados, antes + 1);
  });

  group('aviso cuando un pedido se resuelve', () {
    testWidgets('cobrado: "Cobramos tu pedido V-0055 por Bs 398.00."', (tester) async {
      final m = await _montar(tester, alcance: alcanceAna);
      final cobrado = PedidoSinConexion.desdeFila({
        ...pedidoDePrueba(estado: EstadoPedidoLocal.cobrado).aFila(),
        'codigo_venta': 'V-0055',
        'venta_id': 55,
        'total_centavos': 39800,
      });

      m.cola.anunciarResuelto(cobrado);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.text('Cobramos tu pedido V-0055 por Bs 398.00.'), findsOneWidget);
      expect(find.text('Ver compra'), findsOneWidget);
    });

    testWidgets('rechazado: muestra el mensaje del servidor', (tester) async {
      final m = await _montar(tester, alcance: alcanceAna);
      final rechazado = PedidoSinConexion.desdeFila({
        ...pedidoDePrueba(estado: EstadoPedidoLocal.rechazado).aFila(),
        'mensaje': 'Ya no queda esa talla.',
      });

      m.cola.anunciarResuelto(rechazado);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.text('Ya no queda esa talla.'), findsOneWidget);
      expect(find.text('Ver'), findsOneWidget);
    });
  });
}
