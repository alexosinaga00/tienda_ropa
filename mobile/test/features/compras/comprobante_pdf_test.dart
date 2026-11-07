import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/compras/models/venta.dart';
import 'package:mobile/features/compras/pdf/comprobante_pdf.dart';
// ignore: implementation_imports
import 'package:pdf/src/pdf/font/ttf_parser.dart' show TtfParser;

ByteData _fuente(String nombre) => ByteData.sublistView(File('assets/fonts/$nombre').readAsBytesSync());

Future<Uint8List> _generar(DatosComprobante datos) => generarComprobantePdf(
  datos,
  fuenteNormal: _fuente('Roboto-Regular.ttf'),
  fuenteNegrita: _fuente('Roboto-Bold.ttf'),
);

DatosComprobante _datos({String? enlace = 'https://tienda.example/caja?venta=V-0007', int lineas = 2}) =>
    DatosComprobante(
      codigo: 'V-0007',
      fecha: DateTime.utc(2026, 11, 7, 15, 30),
      estado: 'Pagada',
      sucursal: 'Sucursal Bolívar',
      cliente: 'Ñandú Peña',
      lineas: [
        for (var i = 0; i < lineas; i++)
          LineaComprobante(
            nombre: 'Camisa niño algodón $i',
            talla: 'M',
            color: 'Azul añil',
            cantidad: 2,
            precioUnitario: 150,
            subtotal: 300,
          ),
      ],
      subtotal: 300.0 * lineas,
      descuento: 20,
      costoEnvio: 15,
      total: 300.0 * lineas - 5,
      enlaceVerificacion: enlace,
    );

void main() {
  test('genera un PDF válido (empieza por %PDF y termina con %%EOF)', () async {
    final bytes = await _generar(_datos());

    expect(bytes, isNotEmpty);
    expect(ascii.decode(bytes.sublist(0, 5)), '%PDF-');
    expect(ascii.decode(bytes.sublist(bytes.length - 6), allowInvalid: true).trim(), endsWith('%%EOF'));
  });

  test('tildes, ñ y signos del español no lanzan', () async {
    final datos = DatosComprobante(
      codigo: 'V-0099',
      fecha: DateTime.utc(2026, 11, 7),
      sucursal: 'Cañada Ñuflo — Ávila ¿ó?',
      cliente: 'José Peña Ñáñez',
      lineas: const [
        LineaComprobante(
          nombre: 'Pantalón ñoño “edición” útil',
          talla: 'XL',
          color: 'Café',
          cantidad: 1,
          precioUnitario: 99.5,
          subtotal: 99.5,
        ),
      ],
      subtotal: 99.5,
      descuento: 0,
      costoEnvio: 0,
      total: 99.5,
    );

    final bytes = await _generar(datos);

    expect(ascii.decode(bytes.sublist(0, 4)), '%PDF');
  });

  test('la fuente incluida trae las tildes, la ñ y los signos del español', () {
    final mapa = TtfParser(_fuente('Roboto-Regular.ttf')).charToGlyphIndexMap;

    for (final letra in 'áéíóúüñÁÉÍÓÚÑ¿¡—“”'.runes) {
      expect(mapa.containsKey(letra), isTrue, reason: 'falta ${String.fromCharCode(letra)}');
    }
  });

  test('sin enlace de verificación el PDF sale igual, sin QR', () async {
    final conQr = await _generar(_datos());
    final sinQr = await _generar(_datos(enlace: null));

    expect(ascii.decode(sinQr.sublist(0, 4)), '%PDF');
    expect(sinQr.length, lessThan(conQr.length));
  });

  test('con muchas prendas pasa a más páginas sin lanzar', () async {
    final pocas = await _generar(_datos(lineas: 1));
    final muchas = await _generar(_datos(lineas: 70));

    expect(ascii.decode(muchas.sublist(0, 4)), '%PDF');
    expect(muchas.length, greaterThan(pocas.length));
  });

  group('DatosComprobante', () {
    test('desdeVenta toma lo que muestra la pantalla, con la enlace del servidor', () {
      final venta = Venta.fromJson({
        'id': 7,
        'codigo': 'V-0007',
        'estado': 'pagada',
        'fecha': '2026-11-07T15:30:00Z',
        'subtotal': '300.00',
        'descuento': '20.00',
        'costo_envio': '15.00',
        'total': '295.00',
        'enlace_verificacion': 'https://tienda.example/caja?venta=V-0007',
        'detalle': [
          {'id': 1, 'variante_id': 3, 'cantidad': 2, 'precio_unitario': '150.00', 'subtotal': '300.00'},
        ],
      });

      final datos = DatosComprobante.desdeVenta(
        venta.conDetalle([
          venta.detalle.single.conExhibicion(
            productoNombre: 'Polera',
            imagenPrincipal: null,
            tallaCodigo: 'M',
            colorNombre: 'Azul',
          ),
        ]),
        sucursal: 'Centro',
      );

      expect(datos.codigo, 'V-0007');
      expect(datos.estado, 'Pagada');
      expect(datos.sucursal, 'Centro');
      expect(datos.enlaceVerificacion, 'https://tienda.example/caja?venta=V-0007');
      expect(datos.lineas.single.nombre, 'Polera');
      expect(datos.lineas.single.detalle, 'M · Azul');
      expect(datos.total, 295);
    });

    test('el nombre del archivo no lleva caracteres raros', () {
      expect(_datos().nombreArchivo, 'comprobante-V-0007.pdf');
      final raro = DatosComprobante(
        codigo: 'V/00 07',
        fecha: DateTime.utc(2026),
        lineas: const [],
        subtotal: 0,
        descuento: 0,
        costoEnvio: 0,
        total: 0,
      );
      expect(raro.nombreArchivo, 'comprobante-V_00_07.pdf');
    });
  });
}
