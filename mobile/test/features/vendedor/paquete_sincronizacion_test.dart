import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/features/vendedor/models/paquete_sincronizacion.dart';

import 'apoyo_paquete.dart';

void main() {
  group('ManifiestoPaquete', () {
    test('lee el manifiesto real: empresa, sucursales con horarios, referencias y reglas', () {
      final m = ManifiestoPaquete.fromJson(jsonManifiesto());

      expect(m.versionContrato, '1.0');
      expect(m.generadoEn, DateTime.utc(2026, 10, 31, 10));
      expect(m.avisoDesactualizadoHoras, 12);
      expect(m.empresa.id, 1);
      expect(m.empresa.codigo, 'chaski');
      expect(m.sucursales.map((s) => s.id), [1, 2]);
      expect(m.sucursales.first.horarios, hasLength(2));
      expect(m.sucursales.first.horarios.first.horaApertura, '09:00');
      expect(m.categorias.single.nombre, 'Poleras');
      expect(m.tallas.map((t) => t.codigo), ['S', 'M', 'L', 'XL']);
      expect(m.colores.single.codigoHex, '#000000');
      expect(m.reglas.metodosPagoOffline, ['efectivo']);
      expect(m.reglas.plazoCambioHoras, 24);
    });

    test('es tolerante: sin referencia, sin reglas, sin horarios ni dirección', () {
      final m = ManifiestoPaquete.fromJson({
        'empresa': {'id': 4, 'codigo': 'andina', 'nombre': 'Andina'},
        'sucursales': [
          {'id': 9, 'nombre': 'Centro'},
        ],
      });

      expect(m.generadoEn, isNull);
      expect(m.avisoDesactualizadoHoras, isNull);
      expect(m.categorias, isEmpty);
      expect(m.tallas, isEmpty);
      expect(m.sucursales.single.horarios, isEmpty);
      expect(m.sucursales.single.direccion, '');
      expect(m.sucursales.single.esDeposito, isFalse);
      expect(m.reglas.metodosPagoOffline, ['efectivo']);
    });

    test('sin empresa la respuesta no se entiende', () {
      expect(() => ManifiestoPaquete.fromJson({'sucursales': <Object>[]}), throwsA(isA<ErrorApp>()));
    });

    test('una versión de contrato mayor pide actualizar la app', () {
      expect(
        () => ManifiestoPaquete.fromJson(jsonManifiesto(version: '2.0')),
        throwsA(isA<ErrorApp>().having((e) => e.mensaje, 'mensaje', 'Actualiza la app para sincronizar.')),
      );
      expect(() => ManifiestoPaquete.fromJson(jsonManifiesto(version: 2)), throwsA(isA<ErrorApp>()));
      expect(() => ManifiestoPaquete.fromJson(jsonManifiesto(version: '10.3')), throwsA(isA<ErrorApp>()));
    });

    test('la versión 1 (texto, con punto o número) y la ausente se aceptan', () {
      expect(ManifiestoPaquete.fromJson(jsonManifiesto(version: '1.0')).empresa.id, 1);
      expect(ManifiestoPaquete.fromJson(jsonManifiesto(version: '1.7')).empresa.id, 1);
      expect(ManifiestoPaquete.fromJson(jsonManifiesto(version: 1)).empresa.id, 1);
      expect(ManifiestoPaquete.fromJson(jsonManifiesto(version: null)).empresa.id, 1);
      expect(versionContratoSoportada, 1);
    });
  });

  group('PaginaCatalogo', () {
    test('lee productos y variantes del contrato real', () {
      final pagina = PaginaCatalogo.fromJson(
        jsonPaginaCatalogo(
          [
            jsonProducto(10, 'Polera Básica', imagen: 'https://img/10.jpg', variantes: [jsonVariante(100, barras: '7790001')]),
          ],
          total: 5,
          siguiente: 10,
        ),
      );

      expect(pagina.total, 5);
      expect(pagina.siguienteDesdeId, 10);
      expect(pagina.generadoEn, DateTime.utc(2026, 10, 31, 10, 0, 1));
      final p = pagina.items.single;
      expect(p.codigo, 'P10');
      expect(p.categoriaId, 1);
      expect(p.imagenPrincipal, 'https://img/10.jpg');
      expect(p.variantes.single.codigoBarras, '7790001');
      expect(p.variantes.single.sku, 'SKU-100');
    });

    test('los montos en texto pasan a centavos', () {
      final v = VariantePaquete.fromJson(jsonVariante(1, precio: '75.00', descuento: '7.50'));
      expect(v.precioCentavos, 7500);
      expect(v.descuentoCentavos, 750);
      expect(VariantePaquete.fromJson(jsonVariante(1, precio: '0.1', descuento: '0.2')).precioCentavos, 10);
      expect(VariantePaquete.fromJson(jsonVariante(1, precio: '100')).precioCentavos, 10000);
    });

    test('los montos numéricos también pasan a centavos', () {
      expect(VariantePaquete.fromJson(jsonVariante(1, precio: 75)).precioCentavos, 7500);
      expect(VariantePaquete.fromJson(jsonVariante(1, precio: 75.5, descuento: 10.25)).precioCentavos, 7550);
      expect(VariantePaquete.fromJson(jsonVariante(1, precio: 75.5, descuento: 10.25)).descuentoCentavos, 1025);
    });

    test('sin descuento vale 0, pero sin precio la respuesta no se entiende', () {
      expect(VariantePaquete.fromJson(jsonVariante(1, descuento: null)).descuentoCentavos, 0);
      expect(() => VariantePaquete.fromJson(jsonVariante(1, precio: null)), throwsA(isA<ErrorApp>()));
      expect(() => VariantePaquete.fromJson(jsonVariante(1, precio: 'abc')), throwsA(isA<ErrorApp>()));
      expect(() => VariantePaquete.fromJson(jsonVariante(1, precio: '-5.00')), throwsA(isA<ErrorApp>()));
    });

    test('campos opcionales ausentes: género, imagen, temporada y código de barras', () {
      final p = ProductoPaquete.fromJson({
        'id': 3,
        'codigo': 'P3',
        'nombre': 'Gorra',
        'categoria_id': 2,
        'variantes': [
          {'id': 31, 'talla_id': 1, 'color_id': 1, 'sku': 'G-1', 'codigo_barras': '', 'precio': '20.00'},
        ],
      });

      expect(p.genero, 'unisex');
      expect(p.imagenPrincipal, isNull);
      expect(p.temporadaId, isNull);
      expect(p.variantes.single.codigoBarras, isNull);
      expect(p.variantes.single.descuentoCentavos, 0);
    });

    test('una página sin items ni total es una página vacía', () {
      final pagina = PaginaCatalogo.fromJson({'version_contrato': '1.0'});
      expect(pagina.items, isEmpty);
      expect(pagina.total, 0);
      expect(pagina.siguienteDesdeId, isNull);
      expect(pagina.generadoEn, isNull);
    });

    test('una versión mayor falla aunque el resto esté bien', () {
      expect(() => PaginaCatalogo.fromJson(jsonPaginaCatalogo([], version: '3.0')), throwsA(isA<ErrorApp>()));
    });
  });

  group('PaginaStock', () {
    test('lee las existencias con sus fechas con Z', () {
      final pagina = PaginaStock.fromJson(
        jsonPaginaStock(2, [jsonItemStock(100, 5), jsonItemStock(101, 0)], incremental: true, siguiente: 101),
      );

      expect(pagina.sucursalId, 2);
      expect(pagina.incremental, isTrue);
      expect(pagina.siguienteDesdeVarianteId, 101);
      expect(pagina.generadoEn, DateTime.utc(2026, 10, 31, 10, 0, 2));
      expect(pagina.items.first.cantidadDisponible, 5);
      expect(pagina.items.first.actualizadoEn, DateTime.utc(2026, 10, 31, 9, 30));
    });

    test('una cantidad en texto o decimal se entiende; la ausente vale 0', () {
      expect(ItemStockPaquete.fromJson({'variante_id': 1, 'cantidad_disponible': '4'}).cantidadDisponible, 4);
      expect(ItemStockPaquete.fromJson({'variante_id': 1, 'cantidad_disponible': 3.0}).cantidadDisponible, 3);
      expect(ItemStockPaquete.fromJson({'variante_id': 1}).cantidadDisponible, 0);
    });

    test('sin generado_en no se puede calcular el próximo delta: no se entiende', () {
      expect(() => PaginaStock.fromJson({'sucursal_id': 1, 'items': <Object>[]}), throwsA(isA<ErrorApp>()));
    });

    test('una versión mayor falla', () {
      expect(() => PaginaStock.fromJson(jsonPaginaStock(1, [], version: 2)), throwsA(isA<ErrorApp>()));
    });
  });

  group('PaginaClientes', () {
    test('lee nombre, apellido y ci_nit; el apellido y el ci pueden faltar', () {
      final pagina = PaginaClientes.fromJson(
        jsonPaginaClientes([jsonCliente(1, 'Ana', ci: '123'), jsonCliente(2, 'Luis', apellido: null)], total: 2),
      );

      expect(pagina.total, 2);
      expect(pagina.items.first.ciNit, '123');
      expect(pagina.items.last.apellido, isNull);
      expect(pagina.items.last.ciNit, isNull);
    });

    test('una versión mayor falla', () {
      expect(() => PaginaClientes.fromJson(jsonPaginaClientes([], version: '2.1')), throwsA(isA<ErrorApp>()));
    });
  });

  group('fechas', () {
    test('sin zona se toma como UTC y aIsoUtc quita la fracción cero', () {
      expect(leerFechaUtc('2026-10-31T10:00:00'), DateTime.utc(2026, 10, 31, 10));
      expect(leerFechaUtc('2026-10-31T10:00:00-04:00'), DateTime.utc(2026, 10, 31, 14));
      expect(leerFechaUtc(null), isNull);
      expect(leerFechaUtc('basura'), isNull);
      expect(aIsoUtc(DateTime.utc(2026, 10, 31, 10)), '2026-10-31T10:00:00Z');
      expect(aIsoUtc(DateTime.utc(2026, 10, 31, 10, 0, 0, 250)), '2026-10-31T10:00:00.250Z');
    });
  });
}
