import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/theme/app_theme.dart';
import 'package:mobile/features/vendedor/presentation/aviso_vigencia.dart';
import 'package:mobile/features/vendedor/state/catalogo_local_providers.dart';
import 'package:mobile/features/vendedor/state/descarga_catalogo_service.dart';

import 'apoyo_catalogo_local.dart';

final _franja = find.byKey(const Key('aviso_vigencia'));

Color? _colorDe(WidgetTester tester, String fragmento) => tester.widget<Text>(find.textContaining(fragmento)).style?.color;

void main() {
  group('textoHace', () {
    test('menos de un minuto', () {
      expect(textoHace(Duration.zero), 'hace un momento');
      expect(textoHace(const Duration(seconds: 59)), 'hace un momento');
      expect(textoHace(const Duration(minutes: -3)), 'hace un momento');
    });

    test('minutos', () {
      expect(textoHace(const Duration(minutes: 1)), 'hace 1 min');
      expect(textoHace(const Duration(minutes: 20)), 'hace 20 min');
      expect(textoHace(const Duration(minutes: 59, seconds: 59)), 'hace 59 min');
    });

    test('horas (sin redondear hacia arriba)', () {
      expect(textoHace(const Duration(hours: 1)), 'hace 1 h');
      expect(textoHace(const Duration(hours: 3)), 'hace 3 h');
      expect(textoHace(const Duration(hours: 3, minutes: 59)), 'hace 3 h');
      expect(textoHace(const Duration(hours: 23, minutes: 59)), 'hace 23 h');
    });

    test('días, en singular y plural', () {
      expect(textoHace(const Duration(hours: 24)), 'hace 1 día');
      expect(textoHace(const Duration(hours: 47)), 'hace 1 día');
      expect(textoHace(const Duration(days: 2)), 'hace 2 días');
      expect(textoHace(const Duration(days: 10)), 'hace 10 días');
    });
  });

  test('fechaCortaLocal usa la hora local con dos dígitos', () {
    final utc = DateTime.utc(2026, 1, 5, 9, 7);
    expect(fechaCortaLocal(utc), fechaLocalEsperada(utc));
    expect(fechaCortaLocal(utc.toLocal()), fechaLocalEsperada(utc));
  });

  group('AvisoVigencia', () {
    testWidgets('con datos frescos y conexión no se ve', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirFranja(tester, db: db, hijo: const AvisoVigencia());

      expect(_franja, findsNothing);
      expect(find.textContaining('desactualizados'), findsNothing);
      expect(find.text('Actualizar'), findsNothing);
    });

    testWidgets('datos de 3 horas: aviso ámbar con la hora fijada y botón Actualizar', (tester) async {
      final descargado = instanteBase.subtract(const Duration(hours: 3));
      final db = await abrirBaseSembrada(tester, siembra: (b) => sembrarEscenarioBasico(b, descargadoEn: descargado));
      await abrirFranja(tester, db: db, hijo: const AvisoVigencia());

      final cuando = fechaLocalEsperada(descargado);
      expect(
        find.text('Datos de Centro actualizados el $cuando (hace 3 h). Pueden estar desactualizados.'),
        findsOneWidget,
      );
      expect(_colorDe(tester, 'Datos de Centro'), AppColors.advertencia);
      expect(find.widgetWithText(TextButton, 'Actualizar'), findsOneWidget);
    });

    testWidgets('datos de 30 horas: aviso en rojo', (tester) async {
      final descargado = instanteBase.subtract(const Duration(hours: 30));
      final db = await abrirBaseSembrada(tester, siembra: (b) => sembrarEscenarioBasico(b, descargadoEn: descargado));
      await abrirFranja(tester, db: db, hijo: const AvisoVigencia());

      expect(find.textContaining('(hace 1 día). Pueden estar desactualizados.'), findsOneWidget);
      expect(_colorDe(tester, 'Datos de Centro'), AppColors.error);
    });

    testWidgets('justo en el umbral (2 horas) ya avisa; con 1 h 59 min no', (tester) async {
      final db = await abrirBaseSembrada(
        tester,
        siembra: (b) => sembrarEscenarioBasico(b, descargadoEn: instanteBase.subtract(const Duration(hours: 1, minutes: 59))),
      );
      final e = await abrirFranja(tester, db: db, hijo: const AvisoVigencia());
      expect(_franja, findsNothing);

      e.reloj.actual = instanteBase.add(const Duration(minutes: 1));
      e.contenedor.read(descargaTerminadaProvider.notifier).state++;
      await asentar(tester);
      expect(find.textContaining('(hace 2 h). Pueden estar desactualizados.'), findsOneWidget);
    });

    testWidgets('sucursal nunca descargada: lo dice y ofrece actualizar', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: (b) => sembrarEscenarioBasico(b, descargaCentro: false));
      await abrirFranja(tester, db: db, hijo: const AvisoVigencia());

      expect(find.text('Aún no descargaste el catálogo de esta sucursal.'), findsOneWidget);
      expect(_colorDe(tester, 'Aún no descargaste'), AppColors.advertencia);
      expect(find.widgetWithText(TextButton, 'Actualizar'), findsOneWidget);
    });

    testWidgets('sin ninguna sucursal descargada (teléfono nuevo) también dice que falta descargar', (tester) async {
      final db = await abrirBaseSembrada(tester);
      await abrirFranja(tester, db: db, hijo: const AvisoVigencia());

      expect(find.text('Aún no descargaste el catálogo de esta sucursal.'), findsOneWidget);
    });

    testWidgets('sin conexión avisa aunque los datos estén frescos, sin botón', (tester) async {
      final descargado = instanteBase.subtract(const Duration(minutes: 30));
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      await abrirFranja(tester, db: db, hijo: const AvisoVigencia(), enLinea: false);

      expect(find.text('Sin conexión. Los datos se actualizaron el ${fechaLocalEsperada(descargado)} (hace 30 min).'), findsOneWidget);
      expect(find.text('Actualizar'), findsNothing);
    });

    testWidgets('sin conexión y con datos viejos: sigue el aviso de desactualizado y no hay botón', (tester) async {
      final db = await abrirBaseSembrada(
        tester,
        siembra: (b) => sembrarEscenarioBasico(b, descargadoEn: instanteBase.subtract(const Duration(hours: 3))),
      );
      await abrirFranja(tester, db: db, hijo: const AvisoVigencia(), enLinea: false);

      expect(find.textContaining('Pueden estar desactualizados.'), findsOneWidget);
      expect(find.text('Actualizar'), findsNothing);
    });

    testWidgets('el aviso aparece al perder la conexión y desaparece al volver (datos frescos)', (tester) async {
      final db = await abrirBaseSembrada(tester, siembra: sembrarEscenarioBasico);
      final e = await abrirFranja(tester, db: db, hijo: const AvisoVigencia());
      expect(_franja, findsNothing);

      e.conectividad.emitir(false);
      await asentar(tester, rondas: 3);
      expect(_franja, findsOneWidget);

      e.conectividad.emitir(true);
      await asentar(tester, rondas: 3);
      expect(_franja, findsNothing);
    });

    testWidgets('Actualizar pide la descarga de la sucursal activa', (tester) async {
      final db = await abrirBaseSembrada(
        tester,
        siembra: (b) => sembrarEscenarioBasico(b, descargadoEn: instanteBase.subtract(const Duration(hours: 3))),
      );
      final e = await abrirFranja(tester, db: db, hijo: const AvisoVigencia());

      await tester.tap(find.widgetWithText(TextButton, 'Actualizar'));
      await asentar(tester);

      expect(e.servicio.llamadas, 1);
      expect(e.servicio.pedidos.single.sucursalId, 1);
      expect(e.servicio.pedidos.single.usuarioId, 7);
    });

    testWidgets('mientras actualiza muestra el progreso y quita el botón', (tester) async {
      final db = await abrirBaseSembrada(
        tester,
        siembra: (b) => sembrarEscenarioBasico(b, descargadoEn: instanteBase.subtract(const Duration(hours: 3))),
      );
      final e = await abrirFranja(tester, db: db, hijo: const AvisoVigencia());
      e.servicio.puerta = Completer<void>();

      await tester.tap(find.widgetWithText(TextButton, 'Actualizar'));
      await tester.pump();
      await tester.pump();

      expect(find.text('Actualizando datos…'), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.text('Actualizar'), findsNothing);

      e.servicio.puerta!.complete();
      await asentar(tester);
      expect(find.text('Actualizando datos…'), findsNothing);
    });

    testWidgets('al terminar bien la descarga, el aviso se va (datos recién bajados)', (tester) async {
      final db = await abrirBaseSembrada(
        tester,
        siembra: (b) => sembrarEscenarioBasico(b, descargadoEn: instanteBase.subtract(const Duration(hours: 3))),
      );
      final servicio = ServicioDescargaFalso();
      servicio.alDescargar = () async {
        await db.update('descarga', {'descargado_en': '2026-10-31T11:59:00Z'}, where: 'sucursal_id = 1');
      };
      await abrirFranja(tester, db: db, hijo: const AvisoVigencia(), servicio: servicio);
      expect(_franja, findsOneWidget);

      await tester.tap(find.widgetWithText(TextButton, 'Actualizar'));
      await asentar(tester, rondas: 20);

      expect(_franja, findsNothing);
    });

    testWidgets('si la descarga falla muestra el mensaje en rojo y sigue el aviso', (tester) async {
      final db = await abrirBaseSembrada(
        tester,
        siembra: (b) => sembrarEscenarioBasico(b, descargadoEn: instanteBase.subtract(const Duration(hours: 3))),
      );
      final servicio = ServicioDescargaFalso(
        resultado: const ResultadoDescarga.fallida(mensaje: 'No se pudo actualizar; sigues viendo los datos del 31/10/2026 09:00', hayDatosAnteriores: true),
      );
      await abrirFranja(tester, db: db, hijo: const AvisoVigencia(), servicio: servicio);

      await tester.tap(find.widgetWithText(TextButton, 'Actualizar'));
      await asentar(tester);

      expect(find.textContaining('No se pudo actualizar; sigues viendo'), findsOneWidget);
      expect(_colorDe(tester, 'No se pudo actualizar'), AppColors.error);
      expect(find.textContaining('Pueden estar desactualizados.'), findsOneWidget);
      expect(find.widgetWithText(TextButton, 'Actualizar'), findsOneWidget);
    });

    testWidgets('si la descarga se pospone muestra el motivo en ámbar', (tester) async {
      final db = await abrirBaseSembrada(
        tester,
        siembra: (b) => sembrarEscenarioBasico(b, descargadoEn: instanteBase.subtract(const Duration(hours: 3))),
      );
      final servicio = ServicioDescargaFalso(resultado: const ResultadoDescarga.pospuesta(mensajeOperacionesEnviadas));
      await abrirFranja(tester, db: db, hijo: const AvisoVigencia(), servicio: servicio);

      await tester.tap(find.widgetWithText(TextButton, 'Actualizar'));
      await asentar(tester);

      expect(find.text(mensajeOperacionesEnviadas), findsOneWidget);
      expect(_colorDe(tester, 'Hay ventas o reservas'), AppColors.advertencia);
    });

    testWidgets('con una sucursal distinta de la primera usa el nombre de la activa', (tester) async {
      final descargado = instanteBase.subtract(const Duration(hours: 3));
      final db = await abrirBaseSembrada(
        tester,
        siembra: (b) async {
          await sembrarEscenarioBasico(b, descargadoEn: descargado, descargaNorte: true);
          await b.insert('meta', {'clave': 'sucursal_activa:1:7', 'valor': '2'});
        },
      );
      await abrirFranja(tester, db: db, hijo: const AvisoVigencia());

      expect(find.textContaining('Datos de Norte actualizados el'), findsOneWidget);
    });
  });
}
