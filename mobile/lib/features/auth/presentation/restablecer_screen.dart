import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_theme.dart';
import '../state/auth_controller.dart';

/// CU-35: pone la contraseña nueva con el token de recuperación (llega por el query param `token`, igual que en
/// la web).
class RestablecerScreen extends ConsumerStatefulWidget {
  const RestablecerScreen({required this.token, super.key});

  final String? token;

  @override
  ConsumerState<RestablecerScreen> createState() => _RestablecerScreenState();
}

class _RestablecerScreenState extends ConsumerState<RestablecerScreen> {
  final _formKey = GlobalKey<FormState>();
  final _passwordController = TextEditingController();
  final _confirmarController = TextEditingController();
  bool _cargando = false;
  bool _completado = false;
  String? _error;

  @override
  void dispose() {
    _passwordController.dispose();
    _confirmarController.dispose();
    super.dispose();
  }

  Future<void> _enviar(String token) async {
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _cargando = true;
      _error = null;
    });
    try {
      await ref.read(authRepositoryProvider).confirmarRecuperacion(token: token, password: _passwordController.text);
      if (!mounted) return;
      setState(() => _completado = true);
      Future.delayed(const Duration(milliseconds: 2500), () {
        if (mounted) context.go('/login');
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _error = 'El enlace de recuperación venció o no es válido. Solicitá uno nuevo.');
    } finally {
      if (mounted) setState(() => _cargando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final token = widget.token;
    return Scaffold(
      backgroundColor: AppColors.fondo,
      appBar: AppBar(title: const Text('Nueva contraseña')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.xl),
          child: (token == null || token.isEmpty)
              ? _construirSinToken(context)
              : (_completado ? _construirCompletado(context) : _construirFormulario(context, token)),
        ),
      ),
    );
  }

  Widget _construirSinToken(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Enlace inválido', style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: AppSpacing.sm),
        const Text(
          'Falta el código de recuperación. Solicitá uno nuevo.',
          style: TextStyle(color: AppColors.textoTenue),
        ),
        const SizedBox(height: AppSpacing.lg),
        ElevatedButton(onPressed: () => context.go('/recuperar'), child: const Text('Solicitar otro enlace')),
      ],
    );
  }

  Widget _construirCompletado(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Contraseña actualizada', style: Theme.of(context).textTheme.headlineSmall),
        const SizedBox(height: AppSpacing.sm),
        const Text('Ya podés ingresar con tu contraseña nueva.', style: TextStyle(color: AppColors.exito)),
        const SizedBox(height: AppSpacing.lg),
        ElevatedButton(onPressed: () => context.go('/login'), child: const Text('Ir a ingresar')),
      ],
    );
  }

  Widget _construirFormulario(BuildContext context, String token) {
    return Form(
      key: _formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text('Elegí una contraseña nueva', style: Theme.of(context).textTheme.headlineSmall),
          const SizedBox(height: AppSpacing.xl),
          TextFormField(
            controller: _passwordController,
            obscureText: true,
            decoration: const InputDecoration(labelText: 'Contraseña nueva'),
            validator: (valor) {
              if (valor == null || valor.length < 8) return 'Usá al menos 8 caracteres';
              if (valor.length > 72) return 'Usá como máximo 72 caracteres';
              return null;
            },
          ),
          const SizedBox(height: AppSpacing.md),
          TextFormField(
            controller: _confirmarController,
            obscureText: true,
            decoration: const InputDecoration(labelText: 'Repetí la contraseña'),
            validator: (valor) => valor == _passwordController.text ? null : 'Las contraseñas no coinciden',
          ),
          if (_error != null) ...[
            const SizedBox(height: AppSpacing.md),
            Text(_error!, style: const TextStyle(color: AppColors.error)),
          ],
          const SizedBox(height: AppSpacing.xl),
          ElevatedButton(
            onPressed: _cargando ? null : () => _enviar(token),
            child: _cargando
                ? const SizedBox(
                    height: 20,
                    width: 20,
                    child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                  )
                : const Text('Cambiar contraseña'),
          ),
          const SizedBox(height: AppSpacing.md),
          TextButton(onPressed: () => context.go('/login'), child: const Text('Volver a ingresar')),
        ],
      ),
    );
  }
}
