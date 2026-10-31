import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/theme/app_theme.dart';
import '../../auth/state/auth_controller.dart';
import '../../tienda/state/tienda_controller.dart';

class SplashScreen extends ConsumerStatefulWidget {
  const SplashScreen({super.key});

  @override
  ConsumerState<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends ConsumerState<SplashScreen> {
  @override
  void initState() {
    super.initState();
    // Duración mínima del splash: si restaurarSesion() resolviera al toque
    // (sin token guardado), el splash desaparecía casi instantáneo. Se
    // retrasa el arranque de la restauración de sesión en vez de retrasar
    // la navegación en el router, para no tocar esa lógica compartida.
    Future.delayed(const Duration(seconds: 3), () async {
      if (!mounted) return;
      await ref.read(authControllerProvider.notifier).restaurarSesion();
      // La tienda guardada puede haber cambiado de nombre, logo o color, o ya no existir: se confirma en segundo plano
      // (sin conexión no pasa nada, se sigue con lo guardado).
      unawaited(ref.read(tiendaControllerProvider.notifier).validarGuardada());
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.fondo,
      body: Center(
        child: TweenAnimationBuilder<double>(
          tween: Tween(begin: 0, end: 1),
          duration: const Duration(milliseconds: 600),
          curve: Curves.easeOutBack,
          builder: (context, valor, child) {
            return Opacity(
              opacity: valor.clamp(0, 1),
              child: Transform.scale(scale: 0.85 + (0.15 * valor.clamp(0, 1)), child: child),
            );
          },
          child: const Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                'FashionStore',
                style: TextStyle(
                  fontSize: 44,
                  fontWeight: FontWeight.w800,
                  letterSpacing: -1,
                  color: AppColors.acento,
                ),
              ),
              SizedBox(height: AppSpacing.xl),
              CircularProgressIndicator(color: AppColors.acento),
            ],
          ),
        ),
      ),
    );
  }
}
