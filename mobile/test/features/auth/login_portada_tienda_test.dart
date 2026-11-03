import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/core/sesion/sesion_storage.dart';
import 'package:mobile/features/auth/presentation/login_screen.dart';
import 'package:mobile/features/tienda/models/tienda.dart';
import 'package:mobile/features/tienda/state/tienda_controller.dart';

import '../../helpers/sesion_storage_falso.dart';
import '../../helpers/token_storage_falso.dart';

/// Un controlador con la tienda ya elegida, sin tocar la red.
class _ControladorConTienda extends TiendaController {
  _ControladorConTienda(Tienda? tienda, SesionStorage storage)
    : super(storage: storage, repositorio: () => throw UnimplementedError(), alTiendaDesaparecida: () async {}) {
    cargadaFuture.then((_) {
      if (mounted) state = TiendaState(cargada: true, tienda: tienda);
    });
  }
}

Future<void> _abrirLogin(WidgetTester tester, Tienda? tienda) async {
  final storage = SesionStorageFalso();
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        sesionStorageProvider.overrideWithValue(storage),
        tokenStorageProvider.overrideWithValue(TokenStorageFalso()),
        tiendaControllerProvider.overrideWith((ref) => _ControladorConTienda(tienda, storage)),
      ],
      child: const MaterialApp(home: LoginScreen()),
    ),
  );
  await tester.pump();
  await tester.pump();
}

void main() {
  group('Portada del login', () {
    testWidgets('muestra el nombre de la tienda elegida', (tester) async {
      await _abrirLogin(tester, const Tienda(codigo: 'chaski-sport', nombre: 'Chaski Sport'));

      expect(find.text('Chaski Sport'), findsOneWidget);
      expect(find.text('FashionStore'), findsNothing);
    });

    testWidgets('sin tienda elegida queda la marca de la plataforma', (tester) async {
      await _abrirLogin(tester, null);

      expect(find.text('FashionStore'), findsOneWidget);
    });

    testWidgets('el resto de la portada no cambia', (tester) async {
      await _abrirLogin(tester, const Tienda(codigo: 'pampa-casual', nombre: 'Pampa Casual'));

      expect(find.text('PROBADOR VIRTUAL'), findsOneWidget);
      expect(find.text('Probátela antes de comprarla.'), findsOneWidget);
      expect(find.text('Ingresar'), findsOneWidget);
    });
  });
}
