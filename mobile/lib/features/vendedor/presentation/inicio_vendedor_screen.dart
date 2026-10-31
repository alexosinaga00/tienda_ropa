import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/conectividad/conectividad_service.dart';
import '../../../core/sesion/dialogos_sesion.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/indicador_conexion.dart';
import '../../auth/models/usuario.dart';
import '../../auth/state/auth_controller.dart';
import '../../tienda/presentation/marca_tienda.dart';
import '../../tienda/state/tienda_controller.dart';

/// El nombre legible del primer rol de la cuenta; un rol desconocido se muestra tal cual.
String rolLegible(List<String> roles) {
  if (roles.isEmpty) return 'Personal';
  return switch (roles.first) {
    'administrador' => 'Administrador',
    'encargado_sucursal' => 'Encargado de sucursal',
    'cajero' => 'Cajero',
    final otro => otro,
  };
}

/// Inicio del personal. PROVISIONAL: las siguientes etapas reemplazan el cuerpo (caja, reservas...); el nombre del
/// archivo, la clase y la ruta `/vendedor` se mantienen.
class InicioVendedorScreen extends ConsumerStatefulWidget {
  const InicioVendedorScreen({super.key});

  @override
  ConsumerState<InicioVendedorScreen> createState() => _InicioVendedorScreenState();
}

class _InicioVendedorScreenState extends ConsumerState<InicioVendedorScreen> {
  @override
  void initState() {
    super.initState();
    // Una sesión restaurada sin red se confirma con el servidor apenas se pueda (después del primer frame).
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (!ref.read(authControllerProvider).verificada) {
        ref.read(authControllerProvider.notifier).verificarSesion();
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    // Al volver la conexión se reintenta la verificación (`verificarSesion` no hace nada si ya está verificada).
    ref.listen<AsyncValue<bool>>(enLineaProvider, (anterior, actual) {
      if (actual.valueOrNull != true || anterior?.valueOrNull != false) return;
      if (!ref.read(authControllerProvider).verificada) {
        ref.read(authControllerProvider.notifier).verificarSesion();
      }
    });

    final auth = ref.watch(authControllerProvider);
    final tienda = ref.watch(tiendaActualProvider);
    final usuario = auth.usuario;

    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: false,
        title: MarcaTienda(tienda: tienda),
      ),
      body: usuario == null
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                const IndicadorConexion.banner(),
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.all(AppSpacing.lg),
                    children: [
                      _TarjetaSaludo(
                        usuario: usuario,
                        nombreTienda: tienda?.nombre ?? usuario.empresaNombre ?? '',
                        verificada: auth.verificada,
                      ),
                      const SizedBox(height: AppSpacing.lg),
                      const Text(
                        'Las herramientas de venta llegan en las siguientes etapas.',
                        style: TextStyle(color: AppColors.textoTenue),
                      ),
                      const SizedBox(height: AppSpacing.xl),
                      OutlinedButton(
                        style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(48)),
                        onPressed: () => cambiarDeTiendaConAviso(context, ref),
                        child: const Text('Cambiar de tienda'),
                      ),
                      const SizedBox(height: AppSpacing.md),
                      ElevatedButton(
                        style: ElevatedButton.styleFrom(minimumSize: const Size.fromHeight(48)),
                        onPressed: () => cerrarSesionConAviso(context, ref),
                        child: const Text('Cerrar sesión'),
                      ),
                    ],
                  ),
                ),
              ],
            ),
    );
  }
}

class _TarjetaSaludo extends StatelessWidget {
  const _TarjetaSaludo({required this.usuario, required this.nombreTienda, required this.verificada});

  final Usuario usuario;
  final String nombreTienda;
  final bool verificada;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Card(
      elevation: 0,
      color: AppColors.fondoAlterno,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.base),
        side: const BorderSide(color: AppColors.borde),
      ),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Hola, ${usuario.nombre}', style: tema.textTheme.headlineMedium),
            const SizedBox(height: AppSpacing.sm),
            Text(rolLegible(usuario.roles), style: tema.textTheme.bodyLarge),
            if (nombreTienda.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(nombreTienda, style: tema.textTheme.bodyMedium),
            ],
            const SizedBox(height: AppSpacing.md),
            Row(
              children: [
                Icon(
                  verificada ? Icons.verified_user_outlined : Icons.warning_amber_rounded,
                  size: 20,
                  color: verificada ? AppColors.exito : AppColors.advertencia,
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    verificada ? 'Sesión verificada' : 'Sesión sin verificar: sin conexión',
                    style: TextStyle(
                      color: verificada ? AppColors.exito : AppColors.advertencia,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
