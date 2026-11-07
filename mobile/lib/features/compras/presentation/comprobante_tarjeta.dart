import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:qr_flutter/qr_flutter.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/utils/fecha_servidor.dart';
import '../models/venta.dart';
import '../pdf/comprobante_pdf.dart';
import '../pdf/servicio_comprobante.dart';
import '../state/compras_providers.dart';

/// La tarjeta "Comprobante" de una compra pagada o entregada: código, fecha en hora local, sucursal, total, el QR del
/// enlace de verificación (lo dibuja tal cual lo manda el servidor; sin enlace no hay QR, pero sí el resto) y el botón
/// para descargar el PDF. Una compra pendiente de pago o anulada no tiene comprobante: no se muestra nada.
class ComprobanteTarjeta extends ConsumerStatefulWidget {
  const ComprobanteTarjeta({required this.venta, super.key});

  final Venta venta;

  @override
  ConsumerState<ComprobanteTarjeta> createState() => _ComprobanteTarjetaState();
}

class _ComprobanteTarjetaState extends ConsumerState<ComprobanteTarjeta> {
  bool _generando = false;

  Future<void> _descargarPdf() async {
    final venta = widget.venta;
    final sucursalId = venta.sucursalId;
    final sucursal = sucursalId == null ? null : ref.read(nombreSucursalProvider(sucursalId)).valueOrNull;
    setState(() => _generando = true);
    try {
      await ref.read(servicioComprobanteProvider).compartirPdf(DatosComprobante.desdeVenta(venta, sucursal: sucursal));
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('No se pudo generar el PDF. Inténtalo de nuevo.')));
    } finally {
      if (mounted) setState(() => _generando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final venta = widget.venta;
    if (!venta.tieneComprobante) return const SizedBox.shrink();
    final sucursalId = venta.sucursalId;
    final sucursal = sucursalId == null ? null : ref.watch(nombreSucursalProvider(sucursalId)).valueOrNull;
    final enlace = venta.enlaceVerificacion;

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Card(
        key: const Key('tarjeta-comprobante'),
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                children: [
                  const Icon(Icons.receipt_long_outlined, color: AppColors.acento),
                  const SizedBox(width: AppSpacing.sm),
                  // El código va en el título (la cabecera de la pantalla ya lo muestra solo, sin esta frase).
                  Text(
                    'Comprobante ${venta.codigo}',
                    style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.sm),
              _Dato('Fecha', formatearFechaHora(venta.fecha)),
              if (sucursal != null) _Dato('Sucursal', sucursal),
              _Dato('Total', 'Bs ${venta.total.toStringAsFixed(2)}'),
              if (enlace != null) ...[
                const SizedBox(height: AppSpacing.md),
                Center(
                  child: Container(
                    padding: const EdgeInsets.all(AppSpacing.sm),
                    decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(AppRadius.base)),
                    child: QrImageView(
                      // La llave lleva el texto que dibuja: así una prueba comprueba QUÉ se codifica.
                      key: ValueKey('qr-comprobante:$enlace'),
                      data: enlace,
                      size: 180,
                      backgroundColor: Colors.white,
                      semanticsLabel: 'Código QR del comprobante ${venta.codigo}',
                    ),
                  ),
                ),
                const SizedBox(height: AppSpacing.xs),
                const Text(
                  'Muéstralo en caja para verificar tu compra.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: AppColors.textoTenue, fontSize: 13),
                ),
              ],
              const SizedBox(height: AppSpacing.md),
              OutlinedButton.icon(
                key: const Key('descargar-pdf'),
                onPressed: _generando ? null : _descargarPdf,
                icon: _generando
                    ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.picture_as_pdf_outlined),
                label: Text(_generando ? 'Generando PDF…' : 'Descargar PDF'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Dato extends StatelessWidget {
  const _Dato(this.etiqueta, this.valor);

  final String etiqueta;
  final String valor;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 80,
            child: Text(etiqueta, style: const TextStyle(color: AppColors.textoTenue, fontSize: 13)),
          ),
          Expanded(
            child: Text(valor, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
          ),
        ],
      ),
    );
  }
}
