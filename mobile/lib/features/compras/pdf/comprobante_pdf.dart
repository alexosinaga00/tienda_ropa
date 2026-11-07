import 'dart:typed_data';

import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;

import '../../../core/utils/fecha_servidor.dart';
import '../models/venta.dart';

/// Una prenda del comprobante.
class LineaComprobante {
  const LineaComprobante({
    required this.nombre,
    required this.cantidad,
    required this.precioUnitario,
    required this.subtotal,
    this.talla,
    this.color,
  });

  final String nombre;
  final int cantidad;
  final double precioUnitario;
  final double subtotal;
  final String? talla;
  final String? color;

  /// "M · Azul"; vacío si la prenda no tiene talla ni color.
  String get detalle => [?talla, ?color].join(' · ');
}

/// Todo lo que lleva el PDF. Es un dato simple (sin Riverpod ni Flutter) para generarlo en una prueba sin pantalla.
class DatosComprobante {
  const DatosComprobante({
    required this.codigo,
    required this.fecha,
    required this.lineas,
    required this.subtotal,
    required this.descuento,
    required this.costoEnvio,
    required this.total,
    this.estado,
    this.sucursal,
    this.cliente,
    this.enlaceVerificacion,
  });

  /// Arma los datos desde la compra tal como la muestra la pantalla (con nombre, talla y color de cada prenda).
  factory DatosComprobante.desdeVenta(Venta venta, {String? sucursal, String? cliente}) => DatosComprobante(
    codigo: venta.codigo,
    fecha: venta.fecha,
    estado: etiquetasEstadoVenta[venta.estado] ?? venta.estado,
    sucursal: sucursal,
    cliente: cliente,
    lineas: [
      for (final l in venta.detalle)
        LineaComprobante(
          nombre: l.productoNombre ?? 'Prenda',
          talla: l.tallaCodigo,
          color: l.colorNombre,
          cantidad: l.cantidad,
          precioUnitario: l.precioUnitario,
          subtotal: l.subtotal,
        ),
    ],
    subtotal: venta.subtotal,
    descuento: venta.descuento,
    costoEnvio: venta.costoEnvio,
    total: venta.total,
    enlaceVerificacion: venta.enlaceVerificacion,
  );

  final String codigo;

  /// Se muestra en hora local (si viene en UTC se pasa a local).
  final DateTime fecha;
  final String? estado;
  final String? sucursal;
  final String? cliente;
  final List<LineaComprobante> lineas;
  final double subtotal;
  final double descuento;
  final double costoEnvio;
  final double total;

  /// El texto que se dibuja en el QR. Si falta, el PDF sale igual, sin QR.
  final String? enlaceVerificacion;

  /// El nombre del archivo: `comprobante-V-0007.pdf`, sin caracteres que un sistema de archivos rechace.
  String get nombreArchivo => 'comprobante-${codigo.replaceAll(RegExp(r'[^A-Za-z0-9._-]'), '_')}.pdf';
}

String _bs(double monto) => 'Bs ${monto.toStringAsFixed(2)}';

const _tinta = PdfColor.fromInt(0xFF1B1916);
const _tenue = PdfColor.fromInt(0xFF6B645C);
const _linea = PdfColor.fromInt(0xFFE4DFD6);

/// Genera el comprobante en PDF (A4) con los datos de la compra y el QR vectorial de su enlace de verificación.
///
/// Función pura: no toca el disco, la red ni Flutter. Las fuentes llegan como bytes de TTF (la app usa Roboto, que
/// viene como asset) para que las tildes y la ñ salgan bien sin depender de Helvetica, que no las trae completas.
Future<Uint8List> generarComprobantePdf(
  DatosComprobante datos, {
  required ByteData fuenteNormal,
  required ByteData fuenteNegrita,
}) async {
  final tema = pw.ThemeData.withFont(base: pw.Font.ttf(fuenteNormal), bold: pw.Font.ttf(fuenteNegrita));
  final documento = pw.Document(title: 'Comprobante ${datos.codigo}', creator: 'FashionStore', theme: tema);
  final enlace = datos.enlaceVerificacion;

  pw.Widget dato(String etiqueta, String valor) => pw.Padding(
    padding: const pw.EdgeInsets.only(bottom: 3),
    child: pw.Row(
      crossAxisAlignment: pw.CrossAxisAlignment.start,
      children: [
        pw.SizedBox(
          width: 70,
          child: pw.Text(etiqueta, style: const pw.TextStyle(fontSize: 10, color: _tenue)),
        ),
        pw.Expanded(child: pw.Text(valor, style: const pw.TextStyle(fontSize: 11))),
      ],
    ),
  );

  pw.Widget filaMonto(String etiqueta, String valor, {bool negrita = false}) => pw.Padding(
    padding: const pw.EdgeInsets.symmetric(vertical: 2),
    child: pw.Row(
      mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
      children: [
        pw.Text(
          etiqueta,
          style: pw.TextStyle(fontSize: negrita ? 13 : 11, fontWeight: _peso(negrita)),
        ),
        pw.Text(
          valor,
          style: pw.TextStyle(fontSize: negrita ? 13 : 11, fontWeight: _peso(negrita)),
        ),
      ],
    ),
  );

  pw.Widget celda(String texto, {bool negrita = false, pw.TextAlign alineacion = pw.TextAlign.left}) => pw.Padding(
    padding: const pw.EdgeInsets.symmetric(vertical: 5, horizontal: 4),
    child: pw.Text(
      texto,
      textAlign: alineacion,
      style: pw.TextStyle(fontSize: 10, fontWeight: _peso(negrita)),
    ),
  );

  documento.addPage(
    pw.MultiPage(
      pageFormat: PdfPageFormat.a4,
      margin: const pw.EdgeInsets.all(40),
      build: (contexto) => [
        pw.Row(
          mainAxisAlignment: pw.MainAxisAlignment.spaceBetween,
          crossAxisAlignment: pw.CrossAxisAlignment.start,
          children: [
            pw.Expanded(
              child: pw.Column(
                crossAxisAlignment: pw.CrossAxisAlignment.start,
                children: [
                  pw.Text('Comprobante de compra', style: pw.TextStyle(fontSize: 20, fontWeight: pw.FontWeight.bold)),
                  pw.SizedBox(height: 4),
                  pw.Text('FashionStore', style: const pw.TextStyle(fontSize: 11, color: _tenue)),
                  pw.SizedBox(height: 14),
                  dato('Código', datos.codigo),
                  dato('Fecha', formatearFechaHora(datos.fecha)),
                  if (datos.estado != null) dato('Estado', datos.estado!),
                  if (datos.sucursal != null && datos.sucursal!.isNotEmpty) dato('Sucursal', datos.sucursal!),
                  if (datos.cliente != null && datos.cliente!.isNotEmpty) dato('Cliente', datos.cliente!),
                ],
              ),
            ),
            if (enlace != null && enlace.isNotEmpty)
              pw.Column(
                children: [
                  pw.BarcodeWidget(
                    barcode: pw.Barcode.qrCode(),
                    data: enlace,
                    width: 110,
                    height: 110,
                    drawText: false,
                  ),
                  pw.SizedBox(height: 3),
                  pw.Text('Verificar en caja', style: const pw.TextStyle(fontSize: 8, color: _tenue)),
                ],
              ),
          ],
        ),
        pw.SizedBox(height: 18),
        pw.Table(
          border: const pw.TableBorder(
            horizontalInside: pw.BorderSide(color: _linea),
            bottom: pw.BorderSide(color: _tinta),
          ),
          columnWidths: {
            0: const pw.FlexColumnWidth(5),
            1: const pw.FixedColumnWidth(40),
            2: const pw.FixedColumnWidth(70),
            3: const pw.FixedColumnWidth(75),
          },
          children: [
            pw.TableRow(
              decoration: const pw.BoxDecoration(
                border: pw.Border(bottom: pw.BorderSide(color: _tinta)),
              ),
              children: [
                celda('Prenda', negrita: true),
                celda('Cant.', negrita: true, alineacion: pw.TextAlign.right),
                celda('Precio', negrita: true, alineacion: pw.TextAlign.right),
                celda('Subtotal', negrita: true, alineacion: pw.TextAlign.right),
              ],
            ),
            for (final l in datos.lineas)
              pw.TableRow(
                children: [
                  celda(l.detalle.isEmpty ? l.nombre : '${l.nombre}\n${l.detalle}'),
                  celda('${l.cantidad}', alineacion: pw.TextAlign.right),
                  celda(_bs(l.precioUnitario), alineacion: pw.TextAlign.right),
                  celda(_bs(l.subtotal), alineacion: pw.TextAlign.right),
                ],
              ),
          ],
        ),
        pw.SizedBox(height: 12),
        pw.Align(
          alignment: pw.Alignment.centerRight,
          child: pw.SizedBox(
            width: 220,
            child: pw.Column(
              children: [
                filaMonto('Subtotal', _bs(datos.subtotal)),
                if (datos.descuento > 0) filaMonto('Descuento', '- ${_bs(datos.descuento)}'),
                if (datos.costoEnvio > 0) filaMonto('Envío', _bs(datos.costoEnvio)),
                pw.Divider(color: _tinta, thickness: 0.8),
                filaMonto('Total', _bs(datos.total), negrita: true),
              ],
            ),
          ),
        ),
        pw.SizedBox(height: 24),
        pw.Text(
          'Guarda este comprobante: lo necesitas para cambiar una prenda dentro del plazo.',
          style: const pw.TextStyle(fontSize: 9, color: _tenue),
        ),
      ],
    ),
  );

  return documento.save();
}

pw.FontWeight _peso(bool negrita) => negrita ? pw.FontWeight.bold : pw.FontWeight.normal;
