import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/sync/cola_operaciones.dart';
import 'package:mobile/core/sync/operacion_pendiente.dart';
import 'package:mobile/core/widgets/indicador_conexion.dart';
import 'package:mobile/features/vendedor/models/detalle_resultado_sync.dart';

import '../../helpers/cola_falsa.dart' show operacionDePrueba;
import '../../helpers/sincronizacion_api_falsa.dart';
import 'apoyo_pantallas_sync.dart';

String _ruta(int n, {bool nueva = false}) => '/vendedor/operaciones/${idOp(n)}${nueva ? '?nuevo=1' : ''}';

const _polera = LineaDetalle(
  varianteId: 5,
  cantidad: 2,
  nombre: 'Polera Básica',
  talla: 'M',
  color: 'Negro',
  precioUnitarioCentavos: 7500,
);

/// Una cola con UNA operación y su detalle con nombres de prenda.
ColaDePantalla _cola(OperacionPendiente op, {List<LineaDetalle> lineas = const [_polera], String? cliente}) {
  final cola = ColaDePantalla();
  cola.sembrar(op);
  cola.retocarDetalle(op.operacionId, (base) => detalleCon(base, lineas: lineas, clienteNombre: cliente));
  return cola;
}

ElevatedButton _botonReintentar(WidgetTester tester) =>
    tester.widget<ElevatedButton>(find.widgetWithText(ElevatedButton, 'Reintentar ahora'));

void main() {
  group('ResultadoSyncScreen - cabecera', () {
    testWidgets('muestra el estado en grande y el código corto', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: _cola(opDe(1)));

      expect(find.descendant(of: find.byType(AppBar), matching: find.text('Operación')), findsOneWidget);
      expect(find.text('Pendiente de envío'), findsOneWidget);
      expect(find.text('00000001'), findsOneWidget);
      expect(find.text('Venta de contado · ${fechaOHoy(DateTime.utc(2026, 10, 31, 9))}'), findsOneWidget);
    });

    testWidgets('copiar el código lo manda al portapapeles y avisa "Código copiado"', (tester) async {
      final copiado = capturarPortapapeles(tester);
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: _cola(opDe(1)));

      await tester.tap(find.byTooltip('Copiar código'));
      await asentarSync(tester);

      expect(copiado, ['00000001']);
      expect(find.text('Código copiado'), findsOneWidget);
    });

    testWidgets('el botón de copiar tiene área tocable de al menos 48', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: _cola(opDe(1)));

      final tamano = tester.getSize(find.byTooltip('Copiar código'));
      expect(tamano.width, greaterThanOrEqualTo(48));
      expect(tamano.height, greaterThanOrEqualTo(48));
    });

    testWidgets('una operación de otra fecha dice el día con "dd/MM HH:mm"', (tester) async {
      final fecha = DateTime.utc(2026, 10, 28, 15, 20);
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: _cola(opDe(1, fecha: fecha)));

      expect(find.text('Venta de contado · ${fechaCortaEsperada(fecha)}'), findsOneWidget);
    });
  });

  group('ResultadoSyncScreen - sincronizada', () {
    testWidgets('dice "Sincronizada" con el código de la venta y el cambio', (tester) async {
      final cola = _cola(opDe(1, estado: EstadoOperacion.confirmada, totalCentavos: 15000));
      cola.sembrarRespuesta(
        idOp(1),
        estado: 'confirmada',
        detalle: {
          'recurso': {'tipo': 'venta', 'id': 123, 'codigo': 'V-000123', 'total_centavos': 15000},
          'cambio_centavos': 2500,
        },
      );
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('Sincronizada'), findsOneWidget);
      expect(find.text('Venta V-000123'), findsOneWidget);
      expect(find.text('Cambio: Bs 25.00'), findsOneWidget);
      expect(find.text('Qué hacer'), findsNothing);
      expect(find.text('Reintentar ahora'), findsNothing);
    });

    testWidgets('sin cambio no muestra la línea de cambio', (tester) async {
      final cola = _cola(opDe(1, estado: EstadoOperacion.confirmada));
      cola.sembrarRespuesta(
        idOp(1),
        estado: 'confirmada',
        detalle: {
          'recurso': {'tipo': 'venta', 'id': 5, 'codigo': 'V-000005'},
          'cambio_centavos': 0,
        },
      );
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('Venta V-000005'), findsOneWidget);
      expect(find.textContaining('Cambio'), findsNothing);
    });

    testWidgets('una reserva confirmada dice "Reserva" con su código', (tester) async {
      final cola = _cola(opDe(1, estado: EstadoOperacion.confirmada, tipo: TipoOperacion.reserva));
      cola.sembrarRespuesta(
        idOp(1),
        estado: 'confirmada',
        detalle: {
          'recurso': {'tipo': 'reserva', 'id': 8, 'codigo': 'R-000008'},
        },
      );
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('Reserva R-000008'), findsOneWidget);
    });

    testWidgets('sin código de recurso dice que ya está en el servidor', (tester) async {
      final cola = _cola(opDe(1, estado: EstadoOperacion.confirmada));
      cola.sembrarRespuesta(idOp(1), estado: 'confirmada');
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('Tu operación ya está en el servidor.'), findsOneWidget);
    });

    testWidgets('un aviso de precio explica que se respetó el cobrado (D17)', (tester) async {
      final cola = _cola(opDe(1, estado: EstadoOperacion.confirmada));
      cola.sembrarRespuesta(
        idOp(1),
        estado: 'confirmada',
        detalle: {
          'recurso': {'tipo': 'venta', 'id': 5, 'codigo': 'V-000005'},
          'avisos': [
            {'variante_id': 5, 'precio_operacion_centavos': 7000, 'precio_actual_centavos': 7500},
          ],
        },
      );
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(
        find.text('El precio actual de Polera Básica es Bs 75.00; se respetó el que cobraste (Bs 70.00)'),
        findsOneWidget,
      );
    });
  });

  group('ResultadoSyncScreen - rechazada y en conflicto', () {
    testWidgets('una rechazada con motivo conocido explica qué pasó y qué hacer', (tester) async {
      final cola = _cola(opDe(1, estado: EstadoOperacion.rechazada));
      cola.sembrarRespuesta(idOp(1), estado: 'rechazada', codigoMotivo: 'variante_inactiva', motivo: 'Texto del servidor');
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('Rechazada'), findsOneWidget);
      expect(find.text('Prenda dada de baja'), findsOneWidget);
      expect(find.text('Qué pasó'), findsOneWidget);
      expect(find.text('Una de las prendas ya no está en el catálogo.'), findsOneWidget);
      expect(find.text('Qué hacer'), findsOneWidget);
      expect(find.text('Avisa al encargado y actualiza tus datos con "Actualizar datos".'), findsOneWidget);
      expect(find.text('Texto del servidor'), findsOneWidget);
    });

    testWidgets('un motivo desconocido usa el texto del servidor como "qué pasó"', (tester) async {
      final cola = _cola(opDe(1, estado: EstadoOperacion.rechazada));
      cola.sembrarRespuesta(idOp(1), estado: 'rechazada', codigoMotivo: 'algo_nuevo', motivo: 'El servidor dijo algo raro');
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('Operación no aceptada'), findsOneWidget);
      expect(find.text('El servidor dijo algo raro'), findsOneWidget);
      expect(find.text('Consulta con tu encargado y dile el código de la operación.'), findsOneWidget);
      expect(find.text('Detalle del servidor'), findsNothing);
    });

    testWidgets('una rechazada solo en el teléfono usa su último error', (tester) async {
      final cola = _cola(opDe(1, estado: EstadoOperacion.rechazada, ultimoError: 'El servidor no aceptó los datos (código 422).'));
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('El servidor no aceptó los datos (código 422).'), findsOneWidget);
    });

    testWidgets('la rechazada por un encargado muestra su motivo', (tester) async {
      final cola = _cola(opDe(1, estado: EstadoOperacion.rechazada));
      cola.sembrarRespuesta(
        idOp(1),
        estado: 'rechazada',
        codigoMotivo: 'rechazada_por_encargado',
        detalle: {
          'resolucion': {'accion': 'rechazar', 'motivo': 'El cliente se fue sin llevar la prenda'},
        },
      );
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('Rechazada por el encargado'), findsOneWidget);
      expect(find.text('Motivo del encargado'), findsOneWidget);
      expect(find.text('El cliente se fue sin llevar la prenda'), findsOneWidget);
    });

    testWidgets('una en conflicto lista lo que faltó con el nombre de la prenda', (tester) async {
      final cola = _cola(opDe(1, estado: EstadoOperacion.enConflicto));
      cola.sembrarRespuesta(
        idOp(1),
        estado: 'en_conflicto',
        codigoMotivo: 'stock_insuficiente',
        detalle: {
          'faltantes': [
            {'variante_id': 5, 'solicitado': 2, 'disponible': 0},
          ],
        },
      );
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('En conflicto'), findsOneWidget);
      expect(find.text('Falta stock'), findsOneWidget);
      expect(find.text('De Polera Básica pediste 2 y el servidor tiene 0'), findsOneWidget);
      expect(find.text('Un encargado debe resolverla; aquí se actualizará sola.'), findsOneWidget);
    });

    testWidgets('un faltante de una prenda que ya no está en el detalle dice "la prenda"', (tester) async {
      final cola = _cola(opDe(1, estado: EstadoOperacion.enConflicto));
      cola.sembrarRespuesta(
        idOp(1),
        estado: 'en_conflicto',
        codigoMotivo: 'stock_insuficiente',
        detalle: {
          'faltantes': [
            {'variante_id': 999, 'solicitado': 3, 'disponible': 1},
          ],
        },
      );
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('De la prenda pediste 3 y el servidor tiene 1'), findsOneWidget);
    });

    testWidgets('el motivo sale de la ÚLTIMA respuesta', (tester) async {
      final cola = _cola(opDe(1, estado: EstadoOperacion.rechazada));
      cola.sembrarRespuesta(idOp(1), estado: 'en_conflicto', codigoMotivo: 'stock_insuficiente');
      cola.sembrarRespuesta(idOp(1), estado: 'rechazada', codigoMotivo: 'rechazada_por_encargado');
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('Rechazada por el encargado'), findsOneWidget);
      expect(find.text('Falta stock'), findsNothing);
    });

    testWidgets('una rechazada no ofrece "Reintentar ahora"', (tester) async {
      final cola = _cola(opDe(1, estado: EstadoOperacion.rechazada));
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('Reintentar ahora'), findsNothing);
    });
  });

  group('ResultadoSyncScreen - pendiente de envío', () {
    testWidgets('una registrada dice que todavía no llegó, con su último error', (tester) async {
      final cola = _cola(opDe(1, ultimoError: 'Sin respuesta del servidor'));
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('Todavía no llegó al servidor. Se enviará cuando haya conexión.'), findsOneWidget);
      expect(find.text('Último intento: Sin respuesta del servidor'), findsOneWidget);
      expect(find.text('Reintentar ahora'), findsOneWidget);
    });

    testWidgets('sin error previo no muestra "Último intento"', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: _cola(opDe(1)));

      expect(find.textContaining('Último intento'), findsNothing);
    });

    testWidgets('una enviada también ofrece reintentar', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: _cola(opDe(1, estado: EstadoOperacion.enviada)));

      expect(find.text('Enviando…'), findsOneWidget);
      expect(find.text('Reintentar ahora'), findsOneWidget);
    });

    testWidgets('"Reintentar ahora" sincroniza, avisa y la pantalla se actualiza sola', (tester) async {
      final e = await abrirPantallasSync(tester, inicial: _ruta(1), cola: _cola(opDe(1)));

      await tester.tap(find.text('Reintentar ahora'));
      await asentarSync(tester);

      expect(e.api.idsEnviados, [idOp(1)]);
      expect(find.text('1 operación sincronizada'), findsOneWidget);
      expect(find.text('Sincronizada'), findsOneWidget);
      expect(find.text('Reintentar ahora'), findsNothing);
    });

    testWidgets('mientras reintenta el botón se deshabilita', (tester) async {
      final api = SincronizacionApiFalsa();
      final compuerta = api.retener();
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: _cola(opDe(1)), api: api);

      await tester.tap(find.text('Reintentar ahora'));
      await asentarSync(tester);

      expect(tester.widget<ElevatedButton>(find.byType(ElevatedButton)).onPressed, isNull);
      expect(find.text('Enviando…'), findsNWidgets(2)); // la etiqueta de estado y el botón
      expect(api.peticiones, 1);

      compuerta.complete();
      await asentarSync(tester);
      expect(find.text('Reintentar ahora'), findsNothing);
    });

    testWidgets('si el reintento falla por falta de conexión, la operación sigue pendiente', (tester) async {
      final api = SincronizacionApiFalsa()
        ..programar(const ErrorApp(tipo: TipoErrorApp.sinConexion, mensaje: 'Sin conexión.'));
      final e = await abrirPantallasSync(tester, inicial: _ruta(1), cola: _cola(opDe(1)), api: api, enLinea: false);

      await tester.tap(find.text('Reintentar ahora'));
      await asentarSync(tester);

      expect(find.text('Sin conexión: se enviará cuando vuelva'), findsOneWidget);
      expect(e.cola.fila(idOp(1)).estado, EstadoOperacion.registrada);
      expect(_botonReintentar(tester).onPressed, isNotNull);
    });

    testWidgets('si el plan lo bloquea, la franja de bloqueo aparece en esta pantalla', (tester) async {
      final api = SincronizacionApiFalsa()
        ..programar(
          const ErrorApp(tipo: TipoErrorApp.planNoIncluyeFuncionalidad, mensaje: 'Tu plan no incluye esta función.', estado: 403),
        );
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: _cola(opDe(1)), api: api);

      await tester.tap(find.text('Reintentar ahora'));
      await asentarSync(tester);

      expect(find.byKey(const Key('aviso_bloqueo_sync')), findsOneWidget);
    });

    testWidgets('el botón de reintentar mide al menos 48 de alto', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: _cola(opDe(1)));

      expect(tester.getSize(find.widgetWithText(ElevatedButton, 'Reintentar ahora')).height, greaterThanOrEqualTo(48));
    });
  });

  group('ResultadoSyncScreen - resumen e historial', () {
    testWidgets('una venta lista sus prendas con talla, color, cantidad, precio y total', (tester) async {
      final cola = _cola(opDe(1, totalCentavos: 15000));
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('Resumen'), findsOneWidget);
      expect(find.text('Polera Básica'), findsOneWidget);
      expect(find.text('Talla M · Negro'), findsOneWidget);
      expect(find.text('Cantidad: 2 · Bs 75.00 c/u'), findsOneWidget);
      expect(find.text('Total'), findsOneWidget);
      expect(find.text('Efectivo recibido'), findsOneWidget);
      // El total de la línea, el total de la venta y el efectivo recibido.
      expect(find.text('Bs 150.00'), findsNWidgets(3));
    });

    testWidgets('sin foto la prenda lleva un recuadro con su inicial (nunca una imagen de red)', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: _cola(opDe(1)));

      expect(find.byKey(const Key('miniatura_alterna')), findsOneWidget);
      expect(find.descendant(of: find.byKey(const Key('miniatura_alterna')), matching: find.text('P')), findsOneWidget);
      expect(find.byType(Image), findsNothing);
    });

    testWidgets('el cliente y la sucursal salen en el resumen', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: _cola(opDe(1), cliente: 'Ana Pérez'));

      expect(find.text('Cliente'), findsOneWidget);
      expect(find.text('Ana Pérez'), findsOneWidget);
      expect(find.text('Sucursal'), findsOneWidget);
      expect(find.text('Centro'), findsOneWidget);
    });

    testWidgets('una reserva muestra la visita, las horas y la observación, y no el total', (tester) async {
      final reserva = opDe(1, tipo: TipoOperacion.reserva);
      final cola = ColaDePantalla()..sembrar(reserva);
      cola.retocarDetalle(
        idOp(1),
        (base) => detalleCon(
          base,
          lineas: const [LineaDetalle(varianteId: 5, cantidad: 1, nombre: 'Camisa Lino', talla: 'S')],
          clienteNombre: 'María Pérez',
          fechaVisita: DateTime(2026, 11, 2),
          observacion: 'Viene con su hija',
        ),
      );
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('Reserva · ${textoFechaEsperadaDe(reserva)}'), findsOneWidget);
      expect(find.text('02/11/2026, de 10:00 a 11:00'), findsOneWidget);
      expect(find.text('Viene con su hija'), findsOneWidget);
      expect(find.text('María Pérez'), findsOneWidget);
      expect(find.text('Camisa Lino'), findsOneWidget);
      expect(find.text('Cantidad: 1'), findsOneWidget);
      expect(find.text('Total'), findsNothing);
      expect(find.text('Efectivo recibido'), findsNothing);
    });

    testWidgets('el historial muestra cuándo se registró y cada respuesta del servidor', (tester) async {
      final cola = _cola(opDe(1, estado: EstadoOperacion.confirmada));
      cola.sembrarRespuesta(idOp(1), estado: 'en_conflicto', codigoMotivo: 'stock_insuficiente', recibidoEn: DateTime.utc(2026, 10, 31, 10));
      cola.sembrarRespuesta(idOp(1), estado: 'confirmada', recibidoEn: DateTime.utc(2026, 10, 31, 11));
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('Historial'), findsOneWidget);
      expect(find.text('${fechaCortaEsperada(DateTime.utc(2026, 10, 31, 9))} · Registrada en tu teléfono'), findsOneWidget);
      expect(find.text('${fechaCortaEsperada(DateTime.utc(2026, 10, 31, 10))} · En conflicto'), findsOneWidget);
      expect(find.text('${fechaCortaEsperada(DateTime.utc(2026, 10, 31, 11))} · Sincronizada'), findsOneWidget);
    });
  });

  group('ResultadoSyncScreen - operación nueva', () {
    testWidgets('después de registrar una venta muestra la franja y los tres atajos', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(1, nueva: true), cola: _cola(opDe(1)));

      expect(find.text('Venta registrada en tu teléfono. Pendiente de envío.'), findsOneWidget);
      expect(find.widgetWithText(ElevatedButton, 'Nueva venta'), findsOneWidget);
      expect(find.widgetWithText(ElevatedButton, 'Nueva reserva'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Ver pendientes'), findsOneWidget);
    });

    testWidgets('después de registrar una reserva lo dice con "Reserva"', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(1, nueva: true), cola: _cola(opDe(1, tipo: TipoOperacion.reserva)));

      expect(find.text('Reserva registrada en tu teléfono. Pendiente de envío.'), findsOneWidget);
    });

    testWidgets('sin ser nueva no hay franja ni atajos', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: _cola(opDe(1)));

      expect(find.byKey(const Key('franja_nueva')), findsNothing);
      expect(find.text('Nueva venta'), findsNothing);
      expect(find.text('Ver pendientes'), findsNothing);
    });

    testWidgets('si ya se sincronizó, la franja no dice "Pendiente de envío"', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(1, nueva: true), cola: _cola(opDe(1, estado: EstadoOperacion.confirmada)));

      expect(find.text('Venta registrada en tu teléfono.'), findsOneWidget);
      expect(find.textContaining('Pendiente de envío'), findsNothing);
    });

    testWidgets('"Nueva venta" reemplaza esta pantalla por la de nueva venta', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(1, nueva: true), cola: _cola(opDe(1)));

      await tester.tap(find.text('Nueva venta'));
      await asentarSync(tester);

      expect(find.text('PANTALLA NUEVA VENTA'), findsOneWidget);
      expect(find.byKey(const Key('codigo_operacion')), findsNothing);
    });

    testWidgets('"Nueva reserva" abre la pantalla de nueva reserva', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(1, nueva: true), cola: _cola(opDe(1)));

      await tester.tap(find.text('Nueva reserva'));
      await asentarSync(tester);

      expect(find.text('PANTALLA NUEVA RESERVA'), findsOneWidget);
    });

    testWidgets('"Ver pendientes" abre la lista de operaciones', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(1, nueva: true), cola: _cola(opDe(1, totalCentavos: 4200)));

      await tester.tap(find.text('Ver pendientes'));
      await asentarSync(tester);

      expect(find.descendant(of: find.byType(AppBar), matching: find.text('Operaciones')), findsOneWidget);
      expect(find.text('Venta de contado · Bs 42.00'), findsOneWidget);
    });

    testWidgets('los atajos miden al menos 48 de alto', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(1, nueva: true), cola: _cola(opDe(1)));

      for (final boton in ['Nueva venta', 'Nueva reserva']) {
        expect(tester.getSize(find.widgetWithText(ElevatedButton, boton)).height, greaterThanOrEqualTo(48));
      }
      expect(tester.getSize(find.widgetWithText(OutlinedButton, 'Ver pendientes')).height, greaterThanOrEqualTo(48));
    });
  });

  group('ResultadoSyncScreen - no encontrada, refresco y texto', () {
    testWidgets('una operación que no existe dice que no la encuentra y ofrece volver', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(77), cola: _cola(opDe(1)));

      expect(find.text('No encontramos esta operación.'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Volver'), findsOneWidget);
      expect(find.byKey(const Key('codigo_operacion')), findsNothing);
    });

    testWidgets('"Volver" sin pantalla anterior lleva a la lista de operaciones', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(77), cola: _cola(opDe(1)));

      await tester.tap(find.text('Volver'));
      await asentarSync(tester);

      expect(find.descendant(of: find.byType(AppBar), matching: find.text('Operaciones')), findsOneWidget);
    });

    testWidgets('"Volver" con pantalla anterior regresa a ella', (tester) async {
      final e = await abrirPantallasSync(tester, cola: _cola(opDe(1, totalCentavos: 1000)));

      e.router.push(_ruta(77));
      await asentarSync(tester);
      expect(find.text('No encontramos esta operación.'), findsOneWidget);

      await tester.tap(find.text('Volver'));
      await asentarSync(tester);

      expect(find.text('No encontramos esta operación.'), findsNothing);
      expect(find.text('Venta de contado · Bs 10.00'), findsOneWidget);
    });

    testWidgets('la operación de otro usuario se ve como inexistente', (tester) async {
      final cola = ColaDePantalla()..sembrar(operacionDePrueba(idOp(1), empresaId: empresaPrueba, usuarioId: 99));
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('No encontramos esta operación.'), findsOneWidget);
    });

    testWidgets('la operación de otra empresa se ve como inexistente', (tester) async {
      final cola = ColaDePantalla()..sembrar(operacionDePrueba(idOp(1), empresaId: 99, usuarioId: usuarioPrueba));
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);

      expect(find.text('No encontramos esta operación.'), findsOneWidget);
    });

    testWidgets('se actualiza sola cuando el servidor responde', (tester) async {
      final cola = _cola(opDe(1));
      final e = await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);
      expect(find.text('Pendiente de envío'), findsOneWidget);

      cola.sembrarRespuesta(
        idOp(1),
        estado: 'confirmada',
        detalle: {
          'recurso': {'tipo': 'venta', 'id': 9, 'codigo': 'V-000009'},
        },
      );
      await tester.runAsync(() => e.cola.cambiarEstado(idOp(1), EstadoOperacion.confirmada));
      await asentarSync(tester);

      expect(find.text('Sincronizada'), findsOneWidget);
      expect(find.text('Venta V-000009'), findsOneWidget);
      expect(find.text('Pendiente de envío'), findsNothing);
      expect(find.text('Reintentar ahora'), findsNothing);
    });

    testWidgets('pasa de en conflicto a rechazada cuando un encargado la resuelve', (tester) async {
      final cola = _cola(opDe(1, estado: EstadoOperacion.enConflicto));
      cola.sembrarRespuesta(idOp(1), estado: 'en_conflicto', codigoMotivo: 'stock_insuficiente');
      final e = await abrirPantallasSync(tester, inicial: _ruta(1), cola: cola);
      expect(find.text('Un encargado debe resolverla; aquí se actualizará sola.'), findsOneWidget);

      cola.sembrarRespuesta(idOp(1), estado: 'rechazada', codigoMotivo: 'rechazada_por_encargado');
      await tester.runAsync(() => e.cola.cambiarEstado(idOp(1), EstadoOperacion.rechazada));
      await asentarSync(tester);

      expect(find.text('Rechazada por el encargado'), findsOneWidget);
      expect(find.text('Un encargado debe resolverla; aquí se actualizará sola.'), findsNothing);
    });

    testWidgets('sin conexión aparece el banner', (tester) async {
      await abrirPantallasSync(tester, inicial: _ruta(1), cola: _cola(opDe(1)), enLinea: false);

      expect(find.text(textoSinConexion), findsOneWidget);
    });

    testWidgets('ningún texto usa voseo', (tester) async {
      final cola = _cola(opDe(1, estado: EstadoOperacion.enConflicto));
      cola.sembrarRespuesta(
        idOp(1),
        estado: 'en_conflicto',
        codigoMotivo: 'stock_insuficiente',
        detalle: {
          'faltantes': [
            {'variante_id': 5, 'solicitado': 2, 'disponible': 0},
          ],
        },
      );
      await abrirPantallasSync(tester, inicial: _ruta(1, nueva: true), cola: cola);

      expect(textosConVoseo(tester), isEmpty);
      expect(todosLosTextos(tester), isNotEmpty);
    });
  });

  group('DetalleResultadoSync.desde', () {
    test('lee todas las partes del detalle guardado', () {
      final d = DetalleResultadoSync.desde(
        '{"recurso":{"tipo":"venta","id":7,"codigo":"V-000007","total_centavos":15000},"cambio_centavos":500,'
        '"duplicada":true,"avisos":[{"variante_id":5,"precio_operacion_centavos":7000,"precio_actual_centavos":7500}],'
        '"faltantes":[{"variante_id":6,"solicitado":3,"disponible":1}],"resolucion":{"accion":"rechazar","motivo":"No hay"}}',
      );

      expect(d.recursoTipo, 'venta');
      expect(d.recursoId, 7);
      expect(d.recursoCodigo, 'V-000007');
      expect(d.recursoTotalCentavos, 15000);
      expect(d.cambioCentavos, 500);
      expect(d.duplicada, isTrue);
      expect(d.avisos.single.precioOperacionCentavos, 7000);
      expect(d.avisos.single.precioActualCentavos, 7500);
      expect(d.faltantes.single.varianteId, 6);
      expect(d.faltantes.single.solicitado, 3);
      expect(d.faltantes.single.disponible, 1);
      expect(d.resolucionAccion, 'rechazar');
      expect(d.resolucionMotivo, 'No hay');
    });

    test('null, vacío o texto dañado dan un detalle vacío sin lanzar', () {
      for (final entrada in [null, '', '   ', '{no es json', '[1,2,3]', '"texto"', '7']) {
        final d = DetalleResultadoSync.desde(entrada);
        expect(d.recursoCodigo, isNull, reason: 'entrada: $entrada');
        expect(d.avisos, isEmpty);
        expect(d.faltantes, isEmpty);
      }
    });

    test('campos con el tipo equivocado se ignoran', () {
      final d = DetalleResultadoSync.desde(
        '{"recurso":"V-1","cambio_centavos":"500","avisos":[{"variante_id":"x"},3,{"variante_id":5}],'
        '"faltantes":{"variante_id":1},"resolucion":7}',
      );

      expect(d.recursoCodigo, isNull);
      expect(d.cambioCentavos, isNull);
      expect(d.avisos.single.varianteId, 5);
      expect(d.avisos.single.precioActualCentavos, isNull);
      expect(d.faltantes, isEmpty);
      expect(d.resolucionMotivo, isNull);
    });

    test('un texto en blanco se trata como ausente', () {
      final d = DetalleResultadoSync.desde('{"recurso":{"codigo":"  "},"resolucion":{"accion":"forzar","motivo":""}}');

      expect(d.recursoCodigo, isNull);
      expect(d.resolucionAccion, 'forzar');
      expect(d.resolucionMotivo, isNull);
    });
  });
}

/// "hoy 09:00" o "31/10 09:00": como se escribe la fecha de la operación de prueba.
String fechaOHoy(DateTime utc) => mismoDiaLocal(utc, ahoraDePrueba) ? textoHoyEsperado(utc) : fechaCortaEsperada(utc);

String textoFechaEsperadaDe(OperacionPendiente op) => fechaOHoy(op.fechaOperacion);
