import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/utils/dinero.dart';
import '../../catalogo/models/referencia.dart';
import '../../catalogo/state/catalogo_providers.dart';
import '../config/cliente_offline_config.dart';
import '../models/linea_carrito_local.dart';
import '../state/cliente_offline_providers.dart';
import '../state/cola_pedidos.dart';
import 'aviso_sin_conexion_cliente.dart';

/// Las sucursales donde se puede retirar: un depósito solo despacha, no recibe clientes.
List<SucursalRef> sucursalesRetirables(Iterable<SucursalRef> todas) => [
  for (final s in todas)
    if (!s.esDeposito) s,
];

/// La sucursal que se sugiere sola: la única donde se puede retirar o, si todas las prendas se vieron con stock en la
/// misma sucursal, esa. Null si el cliente debe elegir.
int? sucursalSugerida(List<SucursalRef> retirables, List<LineaCarritoLocal> lineas) {
  if (retirables.length == 1) return retirables.single.id;
  final conocidas = {for (final l in lineas) l.sucursalId};
  if (conocidas.length != 1) return null;
  final unica = conocidas.single;
  return unica != null && retirables.any((s) => s.id == unica) ? unica : null;
}

/// Pago SIN conexión con el PayPal guardado. Solo con retiro en sucursal (el costo de envío necesita la zona, que se cotiza
/// con conexión), con los precios que el cliente tenía guardados. Muestra el total, pide aceptar "Se cobrará hasta Bs X" y
/// deja el pedido en la cola; el carrito local queda vacío. Al volver la conexión la cola lo envía.
class CheckoutSinConexionScreen extends ConsumerStatefulWidget {
  const CheckoutSinConexionScreen({super.key});

  @override
  ConsumerState<CheckoutSinConexionScreen> createState() => _CheckoutSinConexionScreenState();
}

class _CheckoutSinConexionScreenState extends ConsumerState<CheckoutSinConexionScreen> {
  bool _cargando = true;
  List<SucursalRef> _sucursales = const [];
  int? _sucursalId;
  bool _acepto = false;
  bool _guardando = false;
  String? _error;

  /// Retiro en sucursal: sin costo de envío.
  static const _costoEnvioCentavos = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _preparar());
  }

  Future<void> _preparar() async {
    List<SucursalRef> sucursales = const [];
    try {
      final guardadas = await ref.read(cacheCatalogoClienteProvider).leerReferencias(cacheSucursal);
      sucursales = [for (final g in guardadas) SucursalRef.fromJson(g)];
    } catch (_) {
      sucursales = const [];
    }
    if (sucursales.isEmpty && enLineaAhora(ref)) {
      // Nunca se guardaron: con conexión se piden (y de paso se recuerdan).
      try {
        sucursales = await ref.read(sucursalesRefProvider.future);
      } catch (_) {
        sucursales = const [];
      }
    }
    if (!mounted) return;
    final retirables = sucursalesRetirables(sucursales);
    setState(() {
      _sucursales = retirables;
      _sucursalId = sucursalSugerida(retirables, ref.read(carritoLocalProvider));
      _cargando = false;
    });
  }

  Future<void> _confirmar() async {
    final lineas = ref.read(carritoLocalProvider);
    final sucursal = _sucursales.where((s) => s.id == _sucursalId).firstOrNull;
    if (_guardando || sucursal == null || lineas.isEmpty) return;
    setState(() {
      _guardando = true;
      _error = null;
    });
    final pedido = await ref
        .read(colaPedidosProvider)
        .encolar(
          EntradaPedido(
            sucursalId: sucursal.id,
            sucursalNombre: sucursal.nombre,
            costoEnvioCentavos: _costoEnvioCentavos,
            lineas: lineas,
          ),
        );
    if (!mounted) return;
    if (pedido == null) {
      setState(() {
        _guardando = false;
        _error = 'No pudimos guardar tu pedido en este teléfono. Revisa que tengas espacio e inténtalo de nuevo.';
      });
      return;
    }
    // El pedido se llevó las prendas: el carrito local queda vacío.
    await ref.read(carritoLocalProvider.notifier).cargar();
    if (!mounted) return;
    setState(() => _guardando = false);
    context.pushReplacement('/pedidos-sin-conexion?nuevo=${pedido.operacionId}');
  }

  @override
  Widget build(BuildContext context) {
    final lineas = ref.watch(carritoLocalProvider);
    final tienePaypal = ref.watch(tienePaypalGuardadoProvider);
    final correo = ref.watch(metodoPagoLocalProvider)?.correoPaypal;
    final enLinea = estaEnLinea(ref);
    final totalCentavos = totalDeLineasCentavos(lineas) + _costoEnvioCentavos;
    final demasiadas = lineas.length > maxLineasPedido;
    final puedeConfirmar =
        !_cargando && !_guardando && lineas.isNotEmpty && !demasiadas && tienePaypal && _sucursalId != null && _acepto;

    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(title: const Text('Pagar sin conexión')),
      body: Column(
        children: [
          const AvisoSinConexionCliente(),
          Expanded(
            child: _cargando
                ? const Center(child: CircularProgressIndicator(color: AppColors.acento))
                : lineas.isEmpty
                ? _Vacio(onVolver: () => context.go('/carrito'))
                : ListView(
                    padding: const EdgeInsets.all(AppSpacing.md),
                    children: [
                      if (enLinea)
                        const Padding(
                          padding: EdgeInsets.only(bottom: AppSpacing.md),
                          child: Text(
                            'Ya tienes conexión: también puedes pagar con QR o PayPal desde tu carrito. Si prefieres, '
                            'deja este pedido para cobrarlo de tu PayPal guardado.',
                            key: Key('volvio-conexion'),
                            style: TextStyle(color: AppColors.exito),
                          ),
                        ),
                      const _Titulo('Tus prendas'),
                      for (final linea in lineas) _FilaPrenda(linea: linea),
                      if (demasiadas)
                        const Padding(
                          padding: EdgeInsets.only(top: AppSpacing.sm),
                          child: Text(
                            'Son demasiadas prendas distintas para un solo pedido sin conexión. Quita algunas en tu carrito.',
                            key: Key('demasiadas-lineas'),
                            style: TextStyle(color: AppColors.error),
                          ),
                        ),
                      const SizedBox(height: AppSpacing.lg),
                      const _Titulo('Retiro en sucursal'),
                      const Text(
                        'Sin conexión solo puedes retirar en una sucursal (sin costo de envío).',
                        style: TextStyle(color: AppColors.textoTenue, fontSize: 13),
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      if (_sucursales.isEmpty)
                        const Text(
                          'No tenemos sucursales guardadas en este teléfono. Conéctate una vez para guardarlas.',
                          key: Key('sin-sucursales'),
                          style: TextStyle(color: AppColors.error),
                        )
                      else ...[
                        Wrap(
                          spacing: AppSpacing.sm,
                          children: [
                            for (final s in _sucursales)
                              ChoiceChip(
                                key: Key('sucursal-${s.id}'),
                                label: Text(s.nombre),
                                selected: _sucursalId == s.id,
                                onSelected: (_) => setState(() => _sucursalId = s.id),
                              ),
                          ],
                        ),
                        const SizedBox(height: AppSpacing.xs),
                        const Text(
                          'El stock se confirma al cobrar: si ya no hay, no se cobra nada y te avisamos.',
                          style: TextStyle(color: AppColors.textoTenue, fontSize: 12),
                        ),
                      ],
                      const SizedBox(height: AppSpacing.lg),
                      const _Titulo('Pago'),
                      if (tienePaypal)
                        ListTile(
                          key: const Key('metodo-paypal-guardado'),
                          contentPadding: EdgeInsets.zero,
                          leading: const Icon(Icons.account_balance_wallet_outlined, color: AppColors.acento),
                          title: const Text('Mi PayPal guardado'),
                          subtitle: Text(
                            correo == null
                                ? 'Se cobra cuando vuelva la conexión.'
                                : '$correo. Se cobra cuando vuelva la conexión.',
                          ),
                        )
                      else ...[
                        const ListTile(
                          key: Key('metodo-paypal-no-disponible'),
                          contentPadding: EdgeInsets.zero,
                          enabled: false,
                          leading: Icon(Icons.account_balance_wallet_outlined),
                          title: Text('Pagar con mi PayPal guardado'),
                          subtitle: Text('$textoPaypalSinGuardar.'),
                        ),
                        Align(
                          alignment: Alignment.centerLeft,
                          child: TextButton(
                            key: const Key('ir-a-metodo-de-pago'),
                            onPressed: () => context.push('/cuenta/metodo-pago'),
                            child: const Text('Ir a Método de pago'),
                          ),
                        ),
                      ],
                      const SizedBox(height: AppSpacing.lg),
                      Card(
                        child: Padding(
                          padding: const EdgeInsets.all(AppSpacing.md),
                          child: Column(
                            children: [
                              _FilaTotal('Subtotal', totalDeLineasCentavos(lineas)),
                              const _FilaTotal('Envío', 0, detalle: 'Retiro en sucursal'),
                              const Divider(),
                              _FilaTotal('Total', totalCentavos, negrita: true),
                            ],
                          ),
                        ),
                      ),
                      CheckboxListTile(
                        key: const Key('aceptar-total'),
                        contentPadding: EdgeInsets.zero,
                        controlAffinity: ListTileControlAffinity.leading,
                        value: _acepto,
                        onChanged: tienePaypal ? (v) => setState(() => _acepto = v ?? false) : null,
                        title: Text(
                          'Se cobrará hasta ${formatearBs(totalCentavos)} cuando vuelva la conexión.',
                          key: const Key('texto-aceptacion'),
                        ),
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      ElevatedButton.icon(
                        key: const Key('confirmar-pedido'),
                        onPressed: puedeConfirmar ? _confirmar : null,
                        icon: _guardando
                            ? const SizedBox(
                                height: 18,
                                width: 18,
                                child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                              )
                            : const Icon(Icons.lock_outline),
                        label: Text(_guardando ? 'Guardando…' : 'Confirmar pedido'),
                      ),
                      if (_error != null)
                        Padding(
                          padding: const EdgeInsets.only(top: AppSpacing.sm),
                          child: Text(
                            _error!,
                            key: const Key('error-pedido'),
                            style: const TextStyle(color: AppColors.error),
                          ),
                        ),
                      const Padding(
                        padding: EdgeInsets.only(top: AppSpacing.md),
                        child: Text(
                          'Usamos los precios que tenías guardados. Si cambiaron y el total supera lo que aceptaste, '
                          'no se cobra y te avisamos.',
                          style: TextStyle(color: AppColors.textoTenue, fontSize: 12),
                        ),
                      ),
                    ],
                  ),
          ),
        ],
      ),
    );
  }
}

class _Titulo extends StatelessWidget {
  const _Titulo(this.texto);

  final String texto;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.only(bottom: AppSpacing.sm),
    child: Text(texto, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
  );
}

class _Vacio extends StatelessWidget {
  const _Vacio({required this.onVolver});

  final VoidCallback onVolver;

  @override
  Widget build(BuildContext context) {
    return Center(
      key: const Key('carrito-vacio'),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('No hay prendas en tu carrito sin conexión.', textAlign: TextAlign.center),
            const SizedBox(height: AppSpacing.md),
            OutlinedButton(onPressed: onVolver, child: const Text('Ir a mi carrito')),
          ],
        ),
      ),
    );
  }
}

class _FilaPrenda extends StatelessWidget {
  const _FilaPrenda({required this.linea});

  final LineaCarritoLocal linea;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      leading: MiniaturaPrenda(url: linea.imagen),
      title: Text(linea.productoNombre, maxLines: 1, overflow: TextOverflow.ellipsis),
      subtitle: linea.detalle.isEmpty ? null : Text(linea.detalle),
      trailing: Text('${linea.cantidad} × ${formatearBs(linea.precioUnitarioCentavos)}'),
    );
  }
}

class _FilaTotal extends StatelessWidget {
  const _FilaTotal(this.etiqueta, this.centavos, {this.negrita = false, this.detalle});

  final String etiqueta;
  final int centavos;
  final bool negrita;
  final String? detalle;

  @override
  Widget build(BuildContext context) {
    final estilo = TextStyle(fontWeight: negrita ? FontWeight.w700 : FontWeight.w400);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(detalle == null ? etiqueta : '$etiqueta ($detalle)', style: estilo),
          Text(formatearBs(centavos), style: estilo),
        ],
      ),
    );
  }
}

/// La foto de una prenda guardada. Si ya se vio, sale del disco aunque no haya red; si no, un ícono.
class MiniaturaPrenda extends StatelessWidget {
  const MiniaturaPrenda({required this.url, this.tamano = 48, super.key});

  final String? url;
  final double tamano;

  @override
  Widget build(BuildContext context) {
    final vacio = Container(
      width: tamano,
      height: tamano,
      color: AppColors.fondoAlterno,
      child: const Icon(Icons.checkroom, color: AppColors.textoTenue),
    );
    return ClipRRect(
      borderRadius: BorderRadius.circular(AppRadius.base),
      child: url == null
          ? vacio
          : CachedNetworkImage(
              imageUrl: url!,
              width: tamano,
              height: tamano,
              fit: BoxFit.cover,
              placeholder: (context, _) => vacio,
              errorWidget: (context, _, error) => vacio,
            ),
    );
  }
}
