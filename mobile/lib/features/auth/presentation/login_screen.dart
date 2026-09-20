import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_theme.dart';
import '../state/auth_controller.dart';

/// Solo rutas internas y que no sean de auth (evita volver a /login o
/// saltar a una URL externa armada a mano en el query param).
String _destinoTrasLogin(String? returnTo) {
  if (returnTo == null || !returnTo.startsWith('/') || returnTo.startsWith('//')) return '/home';
  final ruta = Uri.parse(returnTo).path;
  if (ruta == '/login' || ruta == '/registro' || ruta == '/splash') return '/home';
  return returnTo;
}

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _cargando = false;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _enviar() async {
    if (!_formKey.currentState!.validate()) return;

    // Se lee antes del await: después, `context` puede ya no ser válido.
    final destino = _destinoTrasLogin(GoRouterState.of(context).uri.queryParameters['returnTo']);

    setState(() => _cargando = true);
    try {
      await ref
          .read(authControllerProvider.notifier)
          .login(email: _emailController.text.trim(), password: _passwordController.text);
      // Navegación explícita: el catálogo y el detalle abren esta pantalla
      // con context.push(), y el redirect del router se evalúa contra la
      // ruta base de la pila (/home), no contra /login apilada encima --
      // así que por sí solo nunca la saca y el login "no hace nada".
      if (mounted) context.go(destino);
    } catch (_) {
      if (!mounted) return;
      final mensaje = ref.read(authControllerProvider).error ?? 'No se pudo iniciar sesión.';
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(mensaje)));
    } finally {
      if (mounted) setState(() => _cargando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.fondo,
      body: SafeArea(
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Espacio reservado para la fotografía protagonista del
              // catálogo; se reemplaza por un asset real en la etapa 2.
              Container(
                height: 260,
                decoration: const BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                    colors: [AppColors.acento, Color(0xFF3A4A5F)],
                  ),
                ),
                child: const Center(
                  child: Icon(Icons.checkroom, size: 72, color: Colors.white70),
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(AppSpacing.xl),
                child: Form(
                  key: _formKey,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text('Bienvenido/a', style: Theme.of(context).textTheme.headlineMedium),
                      const SizedBox(height: AppSpacing.xs),
                      const Text('Ingresá para continuar', style: TextStyle(color: AppColors.textoTenue)),
                      const SizedBox(height: AppSpacing.xl),
                      TextFormField(
                        controller: _emailController,
                        keyboardType: TextInputType.emailAddress,
                        decoration: const InputDecoration(labelText: 'Email'),
                        validator: (valor) =>
                            (valor == null || !valor.contains('@')) ? 'Ingresá un email válido' : null,
                      ),
                      const SizedBox(height: AppSpacing.md),
                      TextFormField(
                        controller: _passwordController,
                        obscureText: true,
                        decoration: const InputDecoration(labelText: 'Contraseña'),
                        validator: (valor) =>
                            (valor == null || valor.isEmpty) ? 'Ingresá tu contraseña' : null,
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
                            : const Text('Ingresar'),
                      ),
                      const SizedBox(height: AppSpacing.md),
                      TextButton(
                        onPressed: () => context.go('/recuperar'),
                        child: const Text('¿Olvidaste tu contraseña?'),
                      ),
                      TextButton(
                        onPressed: () => context.go('/registro'),
                        child: const Text('¿No tenés cuenta? Registrate'),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
