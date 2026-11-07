import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/error_app.dart';
import '../../../core/network/mensaje_error.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/utils/fecha_servidor.dart';
import '../state/cliente_offline_providers.dart';
import '../models/metodo_pago.dart';
import 'aviso_sin_conexion_cliente.dart';
import 'paypal_aprobacion_screen.dart';
import 'retorno_paypal.dart';

const textoPaypalGuardadoExito = 'Listo: tu PayPal quedó guardado.';
const textoPaypalCancelado = 'Cancelaste el guardado de tu PayPal. No se guardó nada.';

/// El mensaje para la persona de un error al guardar, confirmar o quitar el PayPal.
String mensajeErrorMetodoPago(Object error) {
  final app = error is ErrorApp ? error : null;
  switch (app?.codigo) {
    case 'paypal_no_aprobado':
      return 'No se aprobó tu PayPal. Intenta de nuevo y acepta el permiso en la página de PayPal.';
    case 'paypal_no_disponible':
      return 'PayPal no responde por ahora. Intenta de nuevo en unos minutos.';
  }
  if (app?.estado == 429) return 'Hiciste muchos intentos seguidos. Espera un rato e inténtalo otra vez.';
  if (app?.tipo == TipoErrorApp.sinConexion) return 'Necesitas conexión para guardar o quitar tu PayPal.';
  return mensajeDeError(error, 'No pudimos completar la operación con PayPal. Intenta de nuevo.');
}

/// Mi PayPal guardado. PayPal guarda el medio de pago; aquí solo se ve si hay uno guardado (con el correo enmascarado que
/// manda el servidor), se inicia el guardado (se abre PayPal en un WebView y al volver se confirma con el servidor) y se
/// quita. Guardar y quitar necesitan conexión; ver el estado, no (se muestra lo que se recordó la última vez).
class MetodoPagoScreen extends ConsumerStatefulWidget {
  const MetodoPagoScreen({super.key});

  @override
  ConsumerState<MetodoPagoScreen> createState() => _MetodoPagoScreenState();
}

class _MetodoPagoScreenState extends ConsumerState<MetodoPagoScreen> {
  /// Lo que dijo el servidor en esta visita.
  MetodoPagoPaypal? _servidor;
  bool _cargando = true;
  bool _guardando = false;
  bool _quitando = false;
  String? _error;
  String? _aviso;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _cargar());
  }

  Future<void> _cargar() async {
    if (!mounted) return;
    if (!enLineaAhora(ref)) {
      setState(() => _cargando = false);
      return;
    }
    final estado = await ref.read(metodoPagoLocalProvider.notifier).refrescar();
    if (!mounted) return;
    setState(() {
      _servidor = estado;
      _cargando = false;
      if (estado == null && ref.read(metodoPagoLocalProvider) == null) {
        _error = 'No pudimos consultar tu método de pago. Intenta de nuevo.';
      }
    });
  }

  Future<void> _guardar() async {
    if (_guardando || !enLineaAhora(ref)) return;
    setState(() {
      _guardando = true;
      _error = null;
      _aviso = null;
    });
    try {
      final inicio = await ref.read(metodoPagoRepositoryProvider).iniciar();
      if (!esUrlAbrible(inicio.urlAprobacion)) {
        throw const ErrorApp(
          tipo: TipoErrorApp.desconocido,
          mensaje: 'No pudimos abrir PayPal. Prueba de nuevo en unos minutos.',
        );
      }
      if (!mounted) return;
      final retorno = await ref.read(abridorAprobacionPaypalProvider)(context, inicio.urlAprobacion);
      if (!mounted) return;
      switch (retorno) {
        case RetornoAprobado(:final token):
          await _confirmar(token.isEmpty ? inicio.tokenPreparacion : token);
        case RetornoSinDatos():
          setState(() => _error = 'No recibimos la confirmación de PayPal. Intenta guardar tu PayPal otra vez.');
        case RetornoCancelado() || null:
          setState(() => _aviso = textoPaypalCancelado);
      }
    } catch (e) {
      if (mounted) setState(() => _error = e is ErrorApp && e.codigo == null ? e.mensaje : mensajeErrorMetodoPago(e));
    } finally {
      if (mounted) setState(() => _guardando = false);
    }
  }

  Future<void> _confirmar(String token) async {
    final metodo = await ref.read(metodoPagoRepositoryProvider).confirmar(token);
    await ref.read(metodoPagoLocalProvider.notifier).recordar(metodo);
    if (!mounted) return;
    setState(() {
      _servidor = metodo;
      _aviso = metodo.guardado ? textoPaypalGuardadoExito : null;
    });
  }

  Future<void> _quitar() async {
    if (_quitando || !enLineaAhora(ref)) return;
    final confirmado = await showDialog<bool>(
      context: context,
      builder: (contexto) => AlertDialog(
        title: const Text('¿Quitar tu PayPal?'),
        content: const Text('Ya no podrás pagar pedidos sin conexión hasta que lo guardes otra vez.'),
        actions: [
          TextButton(
            key: const Key('cancelar-quitar-paypal'),
            onPressed: () => Navigator.pop(contexto, false),
            child: const Text('Cancelar'),
          ),
          TextButton(
            key: const Key('confirmar-quitar-paypal'),
            onPressed: () => Navigator.pop(contexto, true),
            child: const Text('Sí, quitar'),
          ),
        ],
      ),
    );
    if (confirmado != true || !mounted) return;
    setState(() {
      _quitando = true;
      _error = null;
      _aviso = null;
    });
    try {
      await ref.read(metodoPagoRepositoryProvider).quitar();
      await ref.read(metodoPagoLocalProvider.notifier).recordar(MetodoPagoPaypal.sinGuardar);
      if (mounted) {
        setState(() {
          _servidor = MetodoPagoPaypal.sinGuardar;
          _aviso = 'Quitamos tu PayPal.';
        });
      }
    } catch (e) {
      if (mounted) setState(() => _error = mensajeErrorMetodoPago(e));
    } finally {
      if (mounted) setState(() => _quitando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final enLinea = estaEnLinea(ref);
    final recordado = ref.watch(metodoPagoLocalProvider);
    // Lo del servidor y, si no se pudo preguntar, lo que se recordó la última vez.
    final guardado = _servidor?.guardado ?? recordado?.guardado;
    final correo = _servidor != null ? _servidor!.correoPaypal : recordado?.correoPaypal;
    final guardadoEn = _servidor != null ? _servidor!.guardadoEn : recordado?.guardadoEn;
    final esRecordado = _servidor == null && recordado != null;

    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(title: const Text('Método de pago')),
      body: Column(
        children: [
          const AvisoSinConexionCliente(),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.all(AppSpacing.md),
              children: [
                if (!enLinea)
                  const Padding(
                    padding: EdgeInsets.only(bottom: AppSpacing.md),
                    child: Text(
                      'Puedes ver si tienes un PayPal guardado, pero guardarlo o quitarlo necesita conexión.',
                      key: Key('motivo-sin-conexion'),
                      style: TextStyle(color: AppColors.textoTenue),
                    ),
                  ),
                if (_error != null)
                  _Mensaje(
                    clave: const Key('error-metodo'),
                    texto: _error!,
                    color: AppColors.error,
                    icono: Icons.error,
                  ),
                if (_aviso != null)
                  _Mensaje(
                    clave: const Key('aviso-metodo'),
                    texto: _aviso!,
                    color: AppColors.exito,
                    icono: Icons.check_circle,
                  ),
                if (_cargando)
                  const Padding(
                    padding: EdgeInsets.all(AppSpacing.xl),
                    child: Center(child: CircularProgressIndicator(color: AppColors.acento)),
                  )
                else
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(AppSpacing.md),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              const Icon(Icons.account_balance_wallet_outlined, color: AppColors.acento),
                              const SizedBox(width: AppSpacing.sm),
                              const Text('PayPal', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                              const Spacer(),
                              if (guardado != null)
                                Chip(
                                  key: Key(guardado ? 'paypal-guardado' : 'paypal-no-guardado'),
                                  label: Text(
                                    guardado ? 'Guardado' : 'Sin guardar',
                                    style: const TextStyle(fontSize: 12),
                                  ),
                                  backgroundColor: guardado ? const Color(0xFFDCFCE7) : AppColors.fondoAlterno,
                                ),
                            ],
                          ),
                          const SizedBox(height: AppSpacing.sm),
                          if (guardado == null)
                            const Text('No pudimos consultar tu método de pago.', key: Key('paypal-desconocido'))
                          else if (guardado) ...[
                            Text(
                              correo == null ? 'Tu cuenta de PayPal está guardada.' : 'Cuenta $correo',
                              key: const Key('correo-paypal'),
                              style: const TextStyle(fontWeight: FontWeight.w600),
                            ),
                            if (guardadoEn != null)
                              Text(
                                'Guardado el ${formatearFechaHora(guardadoEn.toLocal()).substring(0, 10)}.',
                                style: const TextStyle(color: AppColors.textoTenue, fontSize: 13),
                              ),
                          ] else
                            const Text(
                              'Todavía no guardaste tu PayPal. Sin él no puedes pagar un pedido hecho sin conexión.',
                              style: TextStyle(color: AppColors.textoTenue),
                            ),
                          if (esRecordado)
                            const Padding(
                              padding: EdgeInsets.only(top: AppSpacing.xs),
                              child: Text(
                                'Dato recordado de tu última visita con conexión.',
                                key: Key('dato-recordado'),
                                style: TextStyle(color: AppColors.textoTenue, fontSize: 12),
                              ),
                            ),
                          const SizedBox(height: AppSpacing.md),
                          ElevatedButton.icon(
                            key: const Key('guardar-paypal'),
                            onPressed: !enLinea || _guardando || _quitando ? null : _guardar,
                            icon: _guardando
                                ? const SizedBox(
                                    height: 18,
                                    width: 18,
                                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                                  )
                                : const Icon(Icons.lock_outline),
                            label: Text(
                              _guardando
                                  ? 'Abriendo PayPal…'
                                  : guardado == true
                                  ? 'Cambiar mi PayPal'
                                  : 'Guardar mi PayPal',
                            ),
                          ),
                          if (guardado == true) ...[
                            const SizedBox(height: AppSpacing.sm),
                            OutlinedButton.icon(
                              key: const Key('quitar-paypal'),
                              style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(48)),
                              onPressed: !enLinea || _guardando || _quitando ? null : _quitar,
                              icon: const Icon(Icons.delete_outline),
                              label: Text(_quitando ? 'Quitando…' : 'Quitar'),
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),
                const SizedBox(height: AppSpacing.lg),
                const _ComoFunciona(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Mensaje extends StatelessWidget {
  const _Mensaje({required this.clave, required this.texto, required this.color, required this.icono});

  final Key clave;
  final String texto;
  final Color color;
  final IconData icono;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Row(
        key: clave,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icono, color: color, size: 20),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(texto, style: TextStyle(color: color)),
          ),
        ],
      ),
    );
  }
}

class _ComoFunciona extends StatelessWidget {
  const _ComoFunciona();

  @override
  Widget build(BuildContext context) {
    const puntos = [
      (
        Icons.verified_user_outlined,
        'PayPal guarda tu medio de pago. FashionStore nunca ve ni guarda los datos de tu tarjeta.',
      ),
      (
        Icons.schedule,
        'Si haces un pedido sin conexión, autorizas que lo cobremos de tu PayPal cuando vuelva la conexión. '
            'Se cobrará hasta el total que veas y aceptes cuando termines el pedido.',
      ),
      (Icons.delete_outline, 'Puedes quitar tu PayPal cuando quieras.'),
    ];
    return Column(
      key: const Key('como-funciona'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Cómo funciona', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
        const SizedBox(height: AppSpacing.sm),
        for (final (icono, texto) in puntos)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.sm),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(icono, size: 20, color: AppColors.textoTenue),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(texto, style: const TextStyle(color: AppColors.textoTenue)),
                ),
              ],
            ),
          ),
      ],
    );
  }
}
