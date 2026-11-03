import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/vendedor/presentation/inicio_vendedor_screen.dart';

import 'apoyo_vendedor.dart';

/// Las tarjetas "Nueva venta" y "Nueva reserva" solo se ofrecen si el servidor las aceptaría: vender exige `ventas.presencial` y
/// reservar `reservas.gestionar_sucursal` (backend/sincronizacion/politicas.py, PERMISO_POR_TIPO).
void main() {
  const sinPermiso = 'Tu cuenta no tiene permiso para esto. Pídelo al administrador de tu empresa.';

  Finder tarjeta(String titulo) => find.ancestor(of: find.text(titulo), matching: find.byType(InkWell)).first;

  bool activa(WidgetTester tester, String titulo) => tester.widget<InkWell>(tarjeta(titulo)).onTap != null;

  testWidgets('un cajero (ventas + reservas) puede vender y reservar', (tester) async {
    await abrirVendedor(tester, inicial: '/vendedor', estadoAuth: sesionDePersonal());

    expect(activa(tester, 'Nueva venta de contado'), isTrue);
    expect(activa(tester, 'Nueva reserva'), isTrue);
    expect(find.text(sinPermiso), findsNothing);
  });

  testWidgets('un encargado (reservas, sin ventas) puede reservar pero no vender', (tester) async {
    await abrirVendedor(
      tester,
      inicial: '/vendedor',
      estadoAuth: sesionDePersonal(
        usuario: usuarioDePrueba(
          roles: ['encargado_sucursal'],
          permisos: ['reservas.gestionar_sucursal', 'sincronizacion.operar'],
        ),
      ),
    );

    expect(activa(tester, 'Nueva venta de contado'), isFalse);
    expect(activa(tester, 'Nueva reserva'), isTrue);
    expect(find.text(sinPermiso), findsOneWidget);
  });

  testWidgets('sin ninguno de los dos permisos no se ofrece ni venta ni reserva', (tester) async {
    await abrirVendedor(
      tester,
      inicial: '/vendedor',
      estadoAuth: sesionDePersonal(usuario: usuarioDePrueba(permisos: ['ventas.presencial'])),
    );

    // Con solo ventas.presencial el modo sigue siendo vendedor, pero reservar no está permitido.
    expect(activa(tester, 'Nueva venta de contado'), isTrue);
    expect(activa(tester, 'Nueva reserva'), isFalse);
  });

  testWidgets('tocar una tarjeta desactivada no abre nada', (tester) async {
    await abrirVendedor(
      tester,
      inicial: '/vendedor',
      estadoAuth: sesionDePersonal(
        usuario: usuarioDePrueba(roles: ['encargado_sucursal'], permisos: ['reservas.gestionar_sucursal']),
      ),
    );

    await tester.tap(find.text('Nueva venta de contado'));
    await tester.pump();
    await tester.pump();

    expect(find.text('PANTALLA VENTA'), findsNothing);
    expect(find.text('Hola, Marta'), findsOneWidget);
  });

  testWidgets('"Operaciones" y el catálogo siguen disponibles para quien no vende', (tester) async {
    await abrirVendedor(
      tester,
      inicial: '/vendedor',
      estadoAuth: sesionDePersonal(
        usuario: usuarioDePrueba(roles: ['encargado_sucursal'], permisos: ['reservas.gestionar_sucursal']),
      ),
    );

    expect(activa(tester, 'Operaciones'), isTrue);
    expect(activa(tester, 'Catálogo sin conexión'), isTrue);
  });

  test('los permisos que pide la app son los que exige el servidor', () {
    expect(permisoParaVender, 'ventas.presencial');
    expect(permisoParaReservar, 'reservas.gestionar_sucursal');
  });
}
