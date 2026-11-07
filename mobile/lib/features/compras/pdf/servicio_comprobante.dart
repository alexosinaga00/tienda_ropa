import 'dart:io';

import 'package:flutter/services.dart' show rootBundle;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';

import 'comprobante_pdf.dart';

/// Genera el PDF del comprobante y lo entrega a la persona (hoja de compartir del sistema: guardar en archivos,
/// WhatsApp, correo...). Es la interfaz que usa la pantalla y que las pruebas reemplazan por un falso, sin disco ni
/// hoja de compartir. Si algo falla, lanza: la pantalla lo dice con un mensaje.
abstract interface class ServicioComprobante {
  Future<void> compartirPdf(DatosComprobante datos);
}

const rutaFuenteNormal = 'assets/fonts/Roboto-Regular.ttf';
const rutaFuenteNegrita = 'assets/fonts/Roboto-Bold.ttf';

/// El servicio real: arma el PDF con Roboto (asset), lo guarda en la carpeta temporal (sin permisos de
/// almacenamiento) y lo comparte con `share_plus`, igual que el probador con su imagen.
class ServicioComprobanteReal implements ServicioComprobante {
  const ServicioComprobanteReal();

  @override
  Future<void> compartirPdf(DatosComprobante datos) async {
    final bytes = await generarComprobantePdf(
      datos,
      fuenteNormal: await rootBundle.load(rutaFuenteNormal),
      fuenteNegrita: await rootBundle.load(rutaFuenteNegrita),
    );
    final carpeta = await getTemporaryDirectory();
    final archivo = File('${carpeta.path}/${datos.nombreArchivo}');
    await archivo.writeAsBytes(bytes, flush: true);
    await SharePlus.instance.share(
      ShareParams(
        files: [XFile(archivo.path, mimeType: 'application/pdf', name: datos.nombreArchivo)],
        subject: 'Comprobante ${datos.codigo}',
        text: 'Mi comprobante de compra ${datos.codigo} en FashionStore',
      ),
    );
  }
}

final servicioComprobanteProvider = Provider<ServicioComprobante>((ref) => const ServicioComprobanteReal());
