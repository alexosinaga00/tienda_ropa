import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/sync/cola_operaciones.dart';
import 'package:mobile/core/sync/lineas_operacion.dart';
import 'package:mobile/core/sync/motor_sincronizacion.dart';
import 'package:mobile/core/sync/operacion_pendiente.dart';
import 'package:mobile/core/widgets/indicador_conexion.dart';
import 'package:mobile/features/vendedor/presentation/aviso_bloqueo_sync.dart';

import '../../helpers/cola_falsa.dart' show operacionDePrueba;
import '../../helpers/sincronizacion_api_falsa.dart';
import 'apoyo_pantallas_sync.dart';

Finder _fila(String titulo) => find.text(titulo);

ElevatedButton _boton(WidgetTester tester) => tester.widget<ElevatedButton>(find.byType(ElevatedButton));

void main() {
  group('OperacionesPendientesScreen - lista y filtros', () {
    testWidgets('la barra dice "Operaciones" y "Por atender" es el filtro de arranque', (tester) async {
      await abrirPantallasSync(tester, operaciones: [opDe(1)]);

      expect(find.descendant(of: find.byType(AppBar), matching: find.text('Operaciones')), findsOneWidget);
      expect(tester.widget<ChoiceChip>(find.widgetWithText(ChoiceChip, 'Por atender')).selected, isTrue);
      expect(tester.widget<ChoiceChip>(find.widgetWithText(ChoiceChip, 'Todas')).selected, isFalse);
      expect(tester.widget<ChoiceChip>(find.widgetWithText(ChoiceChip, 'Sincronizadas')).selected, isFalse);
    });

    testWidgets('"Por atender" muestra registradas, enviadas, rechazadas y en conflicto, y oculta las sincronizadas', (tester) async {
      await abrirPantallasSync(
        tester,
        operaciones: [
          opDe(1, estado: EstadoOperacion.registrada, totalCentavos: 1000),
          opDe(2, estado: EstadoOperacion.enviada, totalCentavos: 2000),
          opDe(3, estado: EstadoOperacion.rechazada, totalCentavos: 3000),
          opDe(4, estado: EstadoOperacion.enConflicto, totalCentavos: 4000),
          opDe(5, estado: EstadoOperacion.confirmada, totalCentavos: 5000),
        ],
      );

      expect(_fila('Venta de contado · Bs 10.00'), findsOneWidget);
      expect(_fila('Venta de contado · Bs 20.00'), findsOneWidget);
      expect(_fila('Venta de contado · Bs 30.00'), findsOneWidget);
      expect(_fila('Venta de contado · Bs 40.00'), findsOneWidget);
      expect(_fila('Venta de contado · Bs 50.00'), findsNothing);
    });

    testWidgets('"Todas" muestra las cinco y "Sincronizadas" solo la confirmada', (tester) async {
      await abrirPantallasSync(
        tester,
        operaciones: [
          opDe(1, estado: EstadoOperacion.registrada, totalCentavos: 1000),
          opDe(2, estado: EstadoOperacion.enviada, totalCentavos: 2000),
          opDe(3, estado: EstadoOperacion.rechazada, totalCentavos: 3000),
          opDe(4, estado: EstadoOperacion.enConflicto, totalCentavos: 4000),
          opDe(5, estado: EstadoOperacion.confirmada, totalCentavos: 5000),
        ],
      );

      await tester.tap(find.widgetWithText(ChoiceChip, 'Todas'));
      await asentarSync(tester);
      for (final bs in ['10.00', '20.00', '30.00', '40.00', '50.00']) {
        expect(_fila('Venta de contado · Bs $bs'), findsOneWidget, reason: 'Todas debe mostrar Bs $bs');
      }

      await tester.tap(find.widgetWithText(ChoiceChip, 'Sincronizadas'));
      await asentarSync(tester);
      expect(_fila('Venta de contado · Bs 50.00'), findsOneWidget);
      expect(_fila('Venta de contado · Bs 10.00'), findsNothing);
      expect(tester.widget<ChoiceChip>(find.widgetWithText(ChoiceChip, 'Sincronizadas')).selected, isTrue);

      await tester.tap(find.widgetWithText(ChoiceChip, 'Por atender'));
      await asentarSync(tester);
      expect(_fila('Venta de contado · Bs 50.00'), findsNothing);
      expect(_fila('Venta de contado · Bs 40.00'), findsOneWidget);
    });

    testWidgets('cada estado lleva su etiqueta con TEXTO (no solo color)', (tester) async {
      await abrirPantallasSync(
        tester,
        operaciones: [
          opDe(1, estado: EstadoOperacion.registrada),
          opDe(2, estado: EstadoOperacion.enviada),
          opDe(3, estado: EstadoOperacion.confirmada),
          opDe(4, estado: EstadoOperacion.rechazada),
          opDe(5, estado: EstadoOperacion.enConflicto),
        ],
      );
      await tester.tap(find.widgetWithText(ChoiceChip, 'Todas'));
      await asentarSync(tester);

      expect(find.text('Pendiente de envío'), findsOneWidget);
      expect(find.text('Enviando…'), findsOneWidget);
      expect(find.text('Sincronizada'), findsOneWidget);
      expect(find.text('Rechazada'), findsOneWidget);
      expect(find.text('En conflicto'), findsOneWidget);
    });

    testWidgets('la etiqueta de cada estado trae su ícono', (tester) async {
      await abrirPantallasSync(
        tester,
        operaciones: [
          opDe(1, estado: EstadoOperacion.registrada),
          opDe(2, estado: EstadoOperacion.rechazada),
          opDe(3, estado: EstadoOperacion.enConflicto),
        ],
      );

      expect(find.byIcon(Icons.schedule), findsOneWidget);
      expect(find.byIcon(Icons.cancel_outlined), findsOneWidget);
      expect(find.byIcon(Icons.warning_amber_rounded), findsOneWidget);
    });

    testWidgets('una venta se titula "Venta de contado · Bs N" con su total', (tester) async {
      await abrirPantallasSync(tester, operaciones: [opDe(1, totalCentavos: 15000)]);

      expect(find.text('Venta de contado · Bs 150.00'), findsOneWidget);
    });

    testWidgets('una reserva se titula "Reserva · cliente"', (tester) async {
      final cola = ColaDePantalla();
      final reserva = opDe(1, tipo: TipoOperacion.reserva);
      cola.sembrar(reserva);
      cola.retocarDetalle(reserva.operacionId, (base) => detalleCon(base, clienteNombre: 'María Pérez'));
      await abrirPantallasSync(tester, cola: cola);

      expect(find.text('Reserva · María Pérez'), findsOneWidget);
    });

    testWidgets('una reserva sin cliente conocido solo dice "Reserva"', (tester) async {
      await abrirPantallasSync(tester, operaciones: [opDe(1, tipo: TipoOperacion.reserva)]);

      expect(find.text('Reserva'), findsOneWidget);
    });

    testWidgets('la hora de una operación de hoy dice "hoy HH:mm" (hora local)', (tester) async {
      final fecha = DateTime.utc(2026, 10, 31, 11, 5);
      await abrirPantallasSync(tester, operaciones: [opDe(1, fecha: fecha)]);

      final esperado = mismoDiaLocal(fecha, ahoraDePrueba) ? textoHoyEsperado(fecha) : fechaCortaEsperada(fecha);
      expect(find.text(esperado), findsOneWidget);
    });

    testWidgets('la hora de otro día dice "dd/MM HH:mm" (hora local)', (tester) async {
      final fecha = DateTime.utc(2026, 10, 29, 14, 35);
      await abrirPantallasSync(tester, operaciones: [opDe(1, fecha: fecha)]);

      expect(find.text(fechaCortaEsperada(fecha)), findsOneWidget);
      expect(find.textContaining('hoy'), findsNothing);
    });

    testWidgets('con varias sucursales autorizadas cada fila dice la suya', (tester) async {
      await abrirPantallasSync(
        tester,
        sucursales: const [sucursalCentro, sucursalNorte],
        operaciones: [opDe(1, sucursalId: 2, fecha: DateTime.utc(2026, 10, 29, 14, 35))],
      );

      expect(find.text('Norte · ${fechaCortaEsperada(DateTime.utc(2026, 10, 29, 14, 35))}'), findsOneWidget);
    });

    testWidgets('con una sola sucursal no se repite su nombre', (tester) async {
      await abrirPantallasSync(tester, operaciones: [opDe(1, sucursalId: 1)]);

      expect(find.textContaining('Centro'), findsNothing);
    });

    testWidgets('una rechazada muestra el título de su motivo', (tester) async {
      final cola = ColaDePantalla();
      cola.sembrar(opDe(1, estado: EstadoOperacion.rechazada));
      cola.sembrarRespuesta(idOp(1), estado: 'rechazada', codigoMotivo: 'variante_inactiva');
      await abrirPantallasSync(tester, cola: cola);

      expect(find.text('Prenda dada de baja'), findsOneWidget);
    });

    testWidgets('una en conflicto muestra el título de su motivo', (tester) async {
      final cola = ColaDePantalla();
      cola.sembrar(opDe(1, estado: EstadoOperacion.enConflicto));
      cola.sembrarRespuesta(idOp(1), estado: 'en_conflicto', codigoMotivo: 'stock_insuficiente');
      await abrirPantallasSync(tester, cola: cola);

      expect(find.text('Falta stock'), findsOneWidget);
    });

    testWidgets('un motivo desconocido usa el título genérico', (tester) async {
      final cola = ColaDePantalla();
      cola.sembrar(opDe(1, estado: EstadoOperacion.rechazada));
      cola.sembrarRespuesta(idOp(1), estado: 'rechazada', codigoMotivo: 'algo_nuevo', motivo: 'Texto del servidor');
      await abrirPantallasSync(tester, cola: cola);

      expect(find.text('Operación no aceptada'), findsOneWidget);
    });

    testWidgets('una pendiente de envío no muestra línea de motivo', (tester) async {
      await abrirPantallasSync(tester, operaciones: [opDe(1, ultimoError: 'Sin respuesta del servidor')]);

      expect(find.text('Operación no aceptada'), findsNothing);
      expect(find.textContaining('Sin respuesta'), findsNothing);
    });
  });

  group('OperacionesPendientesScreen - resumen y vacío', () {
    testWidgets('el resumen cuenta por enviar, en conflicto y sincronizadas', (tester) async {
      await abrirPantallasSync(
        tester,
        operaciones: [
          opDe(1, estado: EstadoOperacion.registrada),
          opDe(2, estado: EstadoOperacion.enviada),
          opDe(3, estado: EstadoOperacion.enConflicto),
          opDe(4, estado: EstadoOperacion.confirmada),
          opDe(5, estado: EstadoOperacion.confirmada),
          opDe(6, estado: EstadoOperacion.confirmada),
        ],
      );

      expect(find.text('2 por enviar · 1 en conflicto · 3 sincronizadas'), findsOneWidget);
    });

    testWidgets('las rechazadas se suman al resumen cuando las hay', (tester) async {
      await abrirPantallasSync(
        tester,
        operaciones: [
          opDe(1, estado: EstadoOperacion.registrada),
          opDe(2, estado: EstadoOperacion.rechazada),
          opDe(3, estado: EstadoOperacion.confirmada),
        ],
      );

      expect(find.text('1 por enviar · 0 en conflicto · 1 rechazada · 1 sincronizada'), findsOneWidget);
    });

    testWidgets('sin operaciones el resumen está en cero', (tester) async {
      await abrirPantallasSync(tester);

      expect(find.text('0 por enviar · 0 en conflicto · 0 sincronizadas'), findsOneWidget);
    });

    testWidgets('estado vacío de "Por atender"', (tester) async {
      await abrirPantallasSync(tester, operaciones: [opDe(1, estado: EstadoOperacion.confirmada)]);

      expect(find.text('No tienes operaciones por atender'), findsOneWidget);
    });

    testWidgets('estado vacío de "Todas" y de "Sincronizadas"', (tester) async {
      await abrirPantallasSync(tester);

      await tester.tap(find.widgetWithText(ChoiceChip, 'Todas'));
      await asentarSync(tester);
      expect(find.text('Aún no registraste operaciones'), findsOneWidget);

      await tester.tap(find.widgetWithText(ChoiceChip, 'Sincronizadas'));
      await asentarSync(tester);
      expect(find.text('Aún no tienes operaciones sincronizadas'), findsOneWidget);
    });

    testWidgets('no muestra las operaciones de otro usuario ni de otra empresa', (tester) async {
      await abrirPantallasSync(
        tester,
        operaciones: [
          opDe(1, totalCentavos: 1000),
          operacionDePrueba(idOp(2), empresaId: empresaPrueba, usuarioId: 99),
          operacionDePrueba(idOp(3), empresaId: 99, usuarioId: usuarioPrueba),
        ],
      );

      expect(find.text('Venta de contado · Bs 10.00'), findsOneWidget);
      expect(find.textContaining('Venta de contado'), findsOneWidget);
    });
  });

  group('OperacionesPendientesScreen - paginación y refresco', () {
    testWidgets('carga de 30 en 30: la página siguiente llega al llegar al final', (tester) async {
      final fecha = DateTime.utc(2026, 10, 31, 6);
      await abrirPantallasSync(
        tester,
        operaciones: [for (var n = 1; n <= 35; n++) opDe(n, totalCentavos: n * 100, fecha: fecha.add(Duration(minutes: n)))],
      );

      // La más nueva (Bs 35.00) está arriba; la más vieja (Bs 1.00) cae en la segunda página.
      expect(find.text('Venta de contado · Bs 35.00'), findsOneWidget);
      expect(find.text('Venta de contado · Bs 1.00'), findsNothing);

      await tester.scrollUntilVisible(find.text('Venta de contado · Bs 1.00'), 400, scrollable: find.byType(Scrollable).first);
      await asentarSync(tester);

      expect(find.text('Venta de contado · Bs 1.00'), findsOneWidget);
    });

    testWidgets('con exactamente 30 no pide más ni muestra el indicador de carga', (tester) async {
      final fecha = DateTime.utc(2026, 10, 31, 6);
      await abrirPantallasSync(
        tester,
        operaciones: [for (var n = 1; n <= 30; n++) opDe(n, totalCentavos: n * 100, fecha: fecha.add(Duration(minutes: n)))],
      );
      await tester.scrollUntilVisible(find.text('Venta de contado · Bs 1.00'), 400, scrollable: find.byType(Scrollable).first);
      await asentarSync(tester);

      expect(find.text('Venta de contado · Bs 1.00'), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);
    });

    testWidgets('se refresca sola cuando una operación cambia de estado', (tester) async {
      final e = await abrirPantallasSync(tester, operaciones: [opDe(1)]);
      expect(find.text('Pendiente de envío'), findsOneWidget);

      await tester.runAsync(() => e.cola.cambiarEstado(idOp(1), EstadoOperacion.enviada));
      await asentarSync(tester);

      expect(find.text('Enviando…'), findsOneWidget);
      expect(find.text('Pendiente de envío'), findsNothing);
    });

    testWidgets('una operación registrada ahora aparece sin recargar', (tester) async {
      final e = await abrirPantallasSync(tester);
      expect(find.text('No tienes operaciones por atender'), findsOneWidget);

      await tester.runAsync(
        () => e.cola.registrarVenta(
          NuevaVenta(
            operacionId: idOp(9),
            empresaId: empresaPrueba,
            sucursalId: 1,
            usuarioId: usuarioPrueba,
            fechaOperacion: ahoraDePrueba,
            lineas: const [LineaVenta(varianteId: 5, cantidad: 2, precioUnitarioCentavos: 2500)],
            efectivoConfirmado: true,
          ),
        ),
      );
      await asentarSync(tester);

      expect(find.text('Venta de contado · Bs 50.00'), findsOneWidget);
      expect(find.text('No tienes operaciones por atender'), findsNothing);
      expect(find.text('1 por enviar · 0 en conflicto · 0 sincronizadas'), findsOneWidget);
    });

    testWidgets('al pasar a sincronizada sale de "Por atender"', (tester) async {
      final e = await abrirPantallasSync(tester, operaciones: [opDe(1, totalCentavos: 1000)]);

      await tester.runAsync(() => e.cola.cambiarEstado(idOp(1), EstadoOperacion.confirmada));
      await asentarSync(tester);

      expect(find.text('Venta de contado · Bs 10.00'), findsNothing);
      expect(find.text('No tienes operaciones por atender'), findsOneWidget);
    });

    testWidgets('tocar una fila abre el resultado de esa operación', (tester) async {
      await abrirPantallasSync(tester, operaciones: [opDe(1), opDe(2, totalCentavos: 9900, fecha: DateTime.utc(2026, 10, 31, 10))]);

      await tester.tap(find.text('Venta de contado · Bs 99.00'));
      await asentarSync(tester);

      expect(find.byKey(const Key('codigo_operacion')), findsOneWidget);
      expect(find.text(idOp(2).substring(0, 8)), findsOneWidget);
    });
  });

  group('OperacionesPendientesScreen - Sincronizar ahora', () {
    testWidgets('sin haber sincronizado dice "Aún no se ha sincronizado"', (tester) async {
      await abrirPantallasSync(tester);

      expect(find.text('Aún no se ha sincronizado'), findsOneWidget);
      expect(find.textContaining('Última sincronización'), findsNothing);
    });

    testWidgets('tocar el botón manda las pendientes y avisa "1 operación sincronizada"', (tester) async {
      final e = await abrirPantallasSync(tester, operaciones: [opDe(1)]);

      await tester.tap(find.text('Sincronizar ahora'));
      await asentarSync(tester);

      expect(e.api.peticiones, 1);
      expect(e.api.idsEnviados, [idOp(1)]);
      expect(find.text('1 operación sincronizada'), findsOneWidget);
      expect(e.cola.fila(idOp(1)).estado, EstadoOperacion.confirmada);
    });

    testWidgets('varias sincronizadas dicen "N operaciones sincronizadas"', (tester) async {
      await abrirPantallasSync(tester, operaciones: [opDe(1), opDe(2)]);

      await tester.tap(find.text('Sincronizar ahora'));
      await asentarSync(tester);

      expect(find.text('2 operaciones sincronizadas'), findsOneWidget);
    });

    testWidgets('el resumen y la lista se actualizan al terminar', (tester) async {
      await abrirPantallasSync(tester, operaciones: [opDe(1, totalCentavos: 1000)]);

      await tester.tap(find.text('Sincronizar ahora'));
      await asentarSync(tester);

      expect(find.text('0 por enviar · 0 en conflicto · 1 sincronizada'), findsOneWidget);
      expect(find.text('Venta de contado · Bs 10.00'), findsNothing);
    });

    testWidgets('sin nada por enviar dice "No hay nada por enviar"', (tester) async {
      final e = await abrirPantallasSync(tester);

      await tester.tap(find.text('Sincronizar ahora'));
      await asentarSync(tester);

      expect(e.api.peticiones, 0);
      expect(find.text('No hay nada por enviar'), findsOneWidget);
    });

    testWidgets('si el servidor rechaza, dice "1 necesita atención"', (tester) async {
      final api = SincronizacionApiFalsa()..programar(respuestaDeLote([resultadoRechazada(idOp(1))]));
      await abrirPantallasSync(tester, operaciones: [opDe(1)], api: api);

      await tester.tap(find.text('Sincronizar ahora'));
      await asentarSync(tester);

      expect(find.text('1 necesita atención'), findsOneWidget);
    });

    testWidgets('sincronizada, en conflicto y rechazada se cuentan juntas', (tester) async {
      final api = SincronizacionApiFalsa()
        ..programar(respuestaDeLote([resultadoConfirmada(idOp(1)), resultadoEnConflicto(idOp(2)), resultadoRechazada(idOp(3))]));
      await abrirPantallasSync(
        tester,
        operaciones: [
          opDe(1, fecha: DateTime.utc(2026, 10, 31, 8)),
          opDe(2, fecha: DateTime.utc(2026, 10, 31, 9)),
          opDe(3, fecha: DateTime.utc(2026, 10, 31, 10)),
        ],
        api: api,
      );

      await tester.tap(find.text('Sincronizar ahora'));
      await asentarSync(tester);

      expect(find.text('1 operación sincronizada · 2 necesitan atención'), findsOneWidget);
    });

    testWidgets('sin conexión avisa que se enviará cuando vuelva', (tester) async {
      final api = SincronizacionApiFalsa()
        ..programar(const ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Sin conexión.'));
      final e = await abrirPantallasSync(tester, operaciones: [opDe(1)], api: api, enLinea: false);

      await tester.tap(find.text('Sincronizar ahora'));
      await asentarSync(tester);

      expect(find.text('Sin conexión: se enviará cuando vuelva'), findsOneWidget);
      expect(e.cola.fila(idOp(1)).estado, EstadoOperacion.registrada);
    });

    testWidgets('con conexión pero un fallo del servidor avisa que se reintentará', (tester) async {
      final api = SincronizacionApiFalsa()
        ..programar(const ErrorApp(tipo: TipoErrorApp.servidor, mensaje: 'El servidor no pudo responder.', estado: 503));
      await abrirPantallasSync(tester, operaciones: [opDe(1)], api: api);

      await tester.tap(find.text('Sincronizar ahora'));
      await asentarSync(tester);

      expect(find.text('No se pudo enviar ahora. Se reintentará más tarde'), findsOneWidget);
    });

    testWidgets('mientras corre el botón está deshabilitado con un indicador, y se habilita al terminar', (tester) async {
      final api = SincronizacionApiFalsa();
      final compuerta = api.retener();
      await abrirPantallasSync(tester, operaciones: [opDe(1)], api: api);
      expect(_boton(tester).onPressed, isNotNull);

      await tester.tap(find.text('Sincronizar ahora'));
      await asentarSync(tester);

      expect(_boton(tester).onPressed, isNull);
      expect(find.text('Sincronizando…'), findsOneWidget);
      expect(find.text('Sincronizar ahora'), findsNothing);
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(api.peticiones, 1);

      compuerta.complete();
      await asentarSync(tester);

      expect(_boton(tester).onPressed, isNotNull);
      expect(find.text('Sincronizar ahora'), findsOneWidget);
      expect(find.text('Sincronizando…'), findsNothing);
      expect(find.text('1 operación sincronizada'), findsOneWidget);
      expect(api.peticiones, 1);
    });

    testWidgets('un disparo automático en curso también deshabilita el botón', (tester) async {
      final api = SincronizacionApiFalsa();
      final compuerta = api.retener();
      final e = await abrirPantallasSync(tester, operaciones: [opDe(1)], api: api);

      // Lo dispara el motor (por ejemplo, al recuperar la conexión), no el botón.
      unawaited(e.motor.sincronizar(empresaId: empresaPrueba, usuarioId: usuarioPrueba, disparador: Disparador.conexionRecuperada));
      await asentarSync(tester);
      expect(_boton(tester).onPressed, isNull);
      expect(find.text('Sincronizando…'), findsOneWidget);

      compuerta.complete();
      await asentarSync(tester);
      expect(_boton(tester).onPressed, isNotNull);
    });

    testWidgets('después de sincronizar muestra "Última sincronización: hace un momento" y luego "hace 5 min"', (tester) async {
      final e = await abrirPantallasSync(tester, operaciones: [opDe(1)]);

      await tester.tap(find.text('Sincronizar ahora'));
      await asentarSync(tester);
      expect(find.text('Última sincronización: hace un momento'), findsOneWidget);

      e.reloj.avanzar(const Duration(minutes: 5));
      e.motor.limpiarBloqueo(); // emite el estado del motor y la franja se vuelve a dibujar
      await asentarSync(tester);

      expect(find.text('Última sincronización: hace 5 min'), findsOneWidget);
    });

    testWidgets('el botón mide al menos 48 de alto y cada fila al menos 64', (tester) async {
      await abrirPantallasSync(tester, operaciones: [opDe(1)]);

      expect(tester.getSize(find.byType(ElevatedButton)).height, greaterThanOrEqualTo(48));
      final fila = find.ancestor(of: find.text('Venta de contado · Bs 75.00'), matching: find.byType(InkWell)).first;
      expect(tester.getSize(fila).height, greaterThanOrEqualTo(64));
    });
  });

  group('OperacionesPendientesScreen - bloqueo, conexión y texto', () {
    testWidgets('sin bloqueo no hay franja', (tester) async {
      await abrirPantallasSync(tester, operaciones: [opDe(1)]);

      expect(find.byType(AvisoBloqueoSync), findsOneWidget);
      expect(find.byKey(const Key('aviso_bloqueo_sync')), findsNothing);
    });

    testWidgets('un bloqueo del plan muestra su mensaje en la franja y en el aviso', (tester) async {
      final api = SincronizacionApiFalsa()
        ..programar(
          const ErrorApp(tipo: TipoErrorApp.planNoIncluyeFuncionalidad, mensaje: 'Tu plan no incluye esta función.', estado: 403),
        );
      await abrirPantallasSync(tester, operaciones: [opDe(1)], api: api);

      await tester.tap(find.text('Sincronizar ahora'));
      await asentarSync(tester);

      expect(find.byKey(const Key('aviso_bloqueo_sync')), findsOneWidget);
      // La franja y el SnackBar dicen lo mismo.
      expect(find.text('Tu plan no incluye esta función.'), findsNWidgets(2));
    });

    testWidgets('una suscripción no activa también se muestra', (tester) async {
      final api = SincronizacionApiFalsa()
        ..programar(const ErrorApp(tipo: TipoErrorApp.suscripcionNoActiva, mensaje: 'La suscripción no está activa.', estado: 403));
      await abrirPantallasSync(tester, operaciones: [opDe(1)], api: api);

      await tester.tap(find.text('Sincronizar ahora'));
      await asentarSync(tester);

      expect(find.byKey(const Key('aviso_bloqueo_sync')), findsOneWidget);
      expect(find.text('La suscripción no está activa.'), findsWidgets);
    });

    testWidgets('con la sesión vencida dice que vuelva a ingresar', (tester) async {
      final api = SincronizacionApiFalsa()
        ..programar(const ErrorApp(tipo: TipoErrorApp.noAutorizado, mensaje: 'Tu sesión venció.', estado: 401));
      final e = await abrirPantallasSync(tester, operaciones: [opDe(1)], api: api);

      await tester.tap(find.text('Sincronizar ahora'));
      await asentarSync(tester);

      expect(find.text('Tu sesión venció: vuelve a ingresar para enviar'), findsNWidgets(2));
      expect(e.cola.fila(idOp(1)).estado, EstadoOperacion.registrada);
    });

    testWidgets('una sincronización que sí funciona quita el bloqueo', (tester) async {
      final api = SincronizacionApiFalsa()
        ..programar(const ErrorApp(tipo: TipoErrorApp.suscripcionNoActiva, mensaje: 'No activa.', estado: 403));
      await abrirPantallasSync(tester, operaciones: [opDe(1)], api: api);
      await tester.tap(find.text('Sincronizar ahora'));
      await asentarSync(tester);
      expect(find.byKey(const Key('aviso_bloqueo_sync')), findsOneWidget);

      await tester.tap(find.text('Sincronizar ahora'));
      await asentarSync(tester);
      // El SnackBar anterior se retira con una animación antes de que salga el nuevo.
      await tester.pump(const Duration(seconds: 1));
      await tester.pump(const Duration(seconds: 1));

      expect(find.byKey(const Key('aviso_bloqueo_sync')), findsNothing);
      expect(find.text('1 operación sincronizada'), findsOneWidget);
    });

    testWidgets('sin conexión aparece el banner', (tester) async {
      await abrirPantallasSync(tester, enLinea: false);

      expect(find.text(textoSinConexion), findsOneWidget);
    });

    testWidgets('con conexión no hay banner', (tester) async {
      await abrirPantallasSync(tester);

      expect(find.text(textoSinConexion), findsNothing);
    });

    testWidgets('ningún texto usa voseo', (tester) async {
      final cola = ColaDePantalla();
      for (var n = 1; n <= 4; n++) {
        cola.sembrar(opDe(n, estado: EstadoOperacion.values[n]));
      }
      cola.sembrarRespuesta(idOp(3), estado: 'rechazada', codigoMotivo: 'rechazada_por_encargado');
      cola.sembrarRespuesta(idOp(4), estado: 'en_conflicto', codigoMotivo: 'stock_insuficiente');
      await abrirPantallasSync(tester, cola: cola);
      await tester.tap(find.widgetWithText(ChoiceChip, 'Todas'));
      await asentarSync(tester);

      expect(textosConVoseo(tester), isEmpty);
      expect(todosLosTextos(tester), isNotEmpty);
    });
  });
}
