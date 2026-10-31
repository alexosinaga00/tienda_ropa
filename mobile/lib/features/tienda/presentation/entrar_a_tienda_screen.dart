import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/network/error_app.dart';
import '../../../core/network/mensaje_error.dart';
import '../../../core/theme/app_theme.dart';
import '../state/tienda_controller.dart';

const mensajeTiendaNoDisponible = 'Esa tienda no está disponible.';

/// Entrada por enlace (`/t/:codigo`): busca la tienda, la guarda como elegida y abre el catálogo. Si no existe o no está
/// disponible vuelve a la lista de tiendas con un aviso.
class EntrarATiendaScreen extends ConsumerStatefulWidget {
  const EntrarATiendaScreen({super.key, required this.codigo});

  final String codigo;

  @override
  ConsumerState<EntrarATiendaScreen> createState() => _EntrarATiendaScreenState();
}

class _EntrarATiendaScreenState extends ConsumerState<EntrarATiendaScreen> {
  Object? _error;

  @override
  void initState() {
    super.initState();
    // Después del primer cuadro: `ScaffoldMessenger.of` y `GoRouter.of` no se pueden pedir dentro de initState.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _abrir();
    });
  }

  Future<void> _abrir() async {
    if (_error != null) setState(() => _error = null);
    final mensajero = ScaffoldMessenger.of(context);
    final router = GoRouter.of(context);
    try {
      final tienda = await ref.read(tiendaRepositoryProvider).obtener(widget.codigo);
      if (!mounted) return;
      if (!tienda.disponible) {
        _noDisponible(mensajero, router);
        return;
      }
      await ref.read(tiendaControllerProvider.notifier).elegir(tienda);
      if (!mounted) return;
      router.go('/home');
    } catch (e) {
      if (!mounted) return;
      if (ErrorApp.desde(e).tipo == TipoErrorApp.noEncontrado) {
        _noDisponible(mensajero, router);
        return;
      }
      setState(() => _error = e);
    }
  }

  void _noDisponible(ScaffoldMessengerState mensajero, GoRouter router) {
    mensajero.showSnackBar(const SnackBar(content: Text(mensajeTiendaNoDisponible)));
    router.go('/tienda');
  }

  @override
  Widget build(BuildContext context) {
    final error = _error;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: error == null ? const _Abriendo() : _ErrorAlAbrir(error: error, onReintentar: _abrir),
          ),
        ),
      ),
    );
  }
}

class _Abriendo extends StatelessWidget {
  const _Abriendo();

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        const CircularProgressIndicator(),
        const SizedBox(height: AppSpacing.md),
        Text('Abriendo tienda…', style: Theme.of(context).textTheme.bodyLarge),
      ],
    );
  }
}

class _ErrorAlAbrir extends StatelessWidget {
  const _ErrorAlAbrir({required this.error, required this.onReintentar});

  final Object error;
  final VoidCallback onReintentar;

  @override
  Widget build(BuildContext context) {
    final sinConexion = esSinConexion(error);
    final mensaje = sinConexion
        ? 'Sin conexión. Revisa tu internet e intenta de nuevo.'
        : mensajeDeError(error, 'No se pudo abrir la tienda.');
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(sinConexion ? Icons.cloud_off_outlined : Icons.error_outline, size: 48, color: AppColors.textoTenue),
        const SizedBox(height: AppSpacing.md),
        Text(mensaje, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyLarge),
        const SizedBox(height: AppSpacing.lg),
        ElevatedButton(onPressed: onReintentar, child: const Text('Reintentar')),
        const SizedBox(height: AppSpacing.sm),
        TextButton(
          onPressed: () => context.go('/tienda'),
          style: TextButton.styleFrom(minimumSize: const Size.fromHeight(48)),
          child: const Text('Elegir otra tienda'),
        ),
      ],
    );
  }
}
