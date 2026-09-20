import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/network/mensaje_error.dart';
import '../../../core/theme/app_theme.dart';
import '../state/auth_controller.dart';

/// CU-35: pide el correo para recuperar la contraseña. El backend responde igual exista o no el correo (no revela
/// nada). Todavía no hay servicio de correo: solo con ENVIRONMENT=local devuelve el token, y entonces se ofrece
/// seguir directo a restablecer (igual que la web).
class RecuperarScreen extends ConsumerStatefulWidget {
  const RecuperarScreen({super.key});

  @override
  ConsumerState<RecuperarScreen> createState() => _RecuperarScreenState();
}

class _RecuperarScreenState extends ConsumerState<RecuperarScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  bool _cargando = false;
  bool _enviado = false;
  String? _tokenDev;

  @override
  void dispose() {
    _emailController.dispose();
    super.dispose();
  }

  Future<void> _enviar() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() => _cargando = true);
    try {
      final tokenDev = await ref.read(authRepositoryProvider).solicitarRecuperacion(_emailController.text.trim());
      if (!mounted) return;
      setState(() {
        _enviado = true;
        _tokenDev = tokenDev;
      });
    } catch (e) {
      if (!mounted) return;
      // El backend responde igual para cualquier correo: un error acá es de red o del límite de intentos.
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(mensajeDeError(e, 'No se pudo enviar la solicitud. Probá de nuevo.'))),
      );
    } finally {
      if (mounted) setState(() => _cargando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(title: const Text('Recuperar contraseña')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: _enviado ? _construirConfirmacion(context) : _construirFormulario(context),
        ),
      ),
    );
  }

  Widget _construirFormulario(BuildContext context) {
    return Form(
      key: _formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('¿Olvidaste tu contraseña?', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: AppSpacing.xs),
          const Text(
            'Ingresá tu email y te mandamos instrucciones para restablecerla.',
            style: TextStyle(color: AppColors.textoTenue),
          ),
          const SizedBox(height: AppSpacing.xl),
          TextFormField(
            controller: _emailController,
            keyboardType: TextInputType.emailAddress,
            decoration: const InputDecoration(labelText: 'Email'),
            validator: (valor) => (valor == null || !valor.contains('@')) ? 'Ingresá un email válido' : null,
          ),
          const SizedBox(height: AppSpacing.xl),
          ElevatedButton(
            onPressed: _cargando ? null : _enviar,
            child: _cargando
                ? const SizedBox(
                    height: 20,
                    width: 20,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                  )
                : const Text('Enviar instrucciones'),
          ),
          const SizedBox(height: AppSpacing.md),
          TextButton(onPressed: () => context.go('/login'), child: const Text('Volver a ingresar')),
        ],
      ),
    );
  }

  Widget _construirConfirmacion(BuildContext context) {
    final tokenDev = _tokenDev;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Revisá tu correo', style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: AppSpacing.sm),
        const Text(
          'Si el correo está registrado, se enviarán instrucciones de recuperación.',
          style: TextStyle(color: AppColors.exito),
        ),
        if (tokenDev != null) ...[
          const SizedBox(height: AppSpacing.lg),
          const Text(
            'Modo desarrollo (no hay servicio de correo configurado todavía):',
            style: TextStyle(color: AppColors.textoTenue),
          ),
          const SizedBox(height: AppSpacing.sm),
          OutlinedButton(
            onPressed: () => context.go('/restablecer?token=${Uri.encodeComponent(tokenDev)}'),
            child: const Text('Continuar a restablecer contraseña'),
          ),
        ],
        const SizedBox(height: AppSpacing.md),
        TextButton(onPressed: () => context.go('/login'), child: const Text('Volver a ingresar')),
      ],
    );
  }
}
