import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/boton_cargando.dart';
import '../../../core/widgets/indicador_conexion.dart';
import '../../auth/state/auth_controller.dart';
import '../../tienda/state/tienda_controller.dart';

const _mensajeErrorGenerico = 'No se pudo iniciar sesión. Intenta de nuevo.';

/// Acceso del PERSONAL (cajero, encargado, administrador): la empresa, el correo y la contraseña. El cliente entra por
/// `/login`. Si el acceso sale bien no se navega a mano: el router manda a `/vendedor` cuando cambia la sesión.
class AccesoVendedorScreen extends ConsumerStatefulWidget {
  const AccesoVendedorScreen({super.key});

  @override
  ConsumerState<AccesoVendedorScreen> createState() => _AccesoVendedorScreenState();
}

class _AccesoVendedorScreenState extends ConsumerState<AccesoVendedorScreen> {
  final _formKey = GlobalKey<FormState>();
  final _empresaController = TextEditingController();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _cargando = false;
  bool _verPassword = false;
  bool _empresaEditada = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _empresaController.text = ref.read(tiendaActualProvider)?.nombre ?? '';
  }

  @override
  void dispose() {
    _empresaController.dispose();
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _enviar() async {
    if (_cargando) return;
    if (!_formKey.currentState!.validate()) return;

    setState(() {
      _cargando = true;
      _error = null;
    });
    try {
      await ref
          .read(authControllerProvider.notifier)
          .loginPersonal(
            empresa: _empresaController.text.trim(),
            email: _emailController.text.trim().toLowerCase(),
            password: _passwordController.text,
          );
      // Normalmente el router ya nos sacó de aquí; si seguimos montados y con sesión, vamos al inicio del personal.
      if (mounted && ref.read(authControllerProvider).estaAutenticado) context.go('/vendedor');
    } catch (_) {
      // Nunca se muestra la excepción cruda: el controlador deja el mensaje ya traducido en su estado.
      if (!mounted) return;
      final mensaje = ref.read(authControllerProvider).error;
      setState(() => _error = (mensaje == null || mensaje.isEmpty) ? _mensajeErrorGenerico : mensaje);
    } finally {
      if (mounted) setState(() => _cargando = false);
    }
  }

  void _elegirOtraTienda() {
    ref.read(authControllerProvider.notifier).olvidarMotivoCierre();
    context.push('/tienda');
  }

  void _soyCliente() {
    ref.read(authControllerProvider.notifier).olvidarMotivoCierre();
    context.go('/home');
  }

  @override
  Widget build(BuildContext context) {
    // La tienda guardada se lee de forma asíncrona: si llega después de abrir la pantalla y la persona aún no escribió
    // nada, se rellena la empresa.
    ref.listen(tiendaActualProvider, (anterior, actual) {
      if (!_empresaEditada && actual != null && _empresaController.text.isEmpty) {
        _empresaController.text = actual.nombre;
      }
    });

    final tema = Theme.of(context);
    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: context.canPop(),
        title: const Text('Acceso del personal'),
      ),
      body: SafeArea(
        child: Column(
          children: [
            const IndicadorConexion.banner(),
            Expanded(
              child: SingleChildScrollView(
                keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
                padding: const EdgeInsets.all(AppSpacing.lg),
                child: Form(
                  key: _formKey,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text('Acceso del personal', style: tema.textTheme.headlineMedium),
                      const SizedBox(height: AppSpacing.xs),
                      const Text(
                        'Ingresa con la cuenta que te dio tu empresa.',
                        style: TextStyle(color: AppColors.textoTenue),
                      ),
                      const SizedBox(height: AppSpacing.lg),
                      TextFormField(
                        controller: _empresaController,
                        enabled: !_cargando,
                        keyboardType: TextInputType.text,
                        textInputAction: TextInputAction.next,
                        onChanged: (_) => _empresaEditada = true,
                        decoration: const InputDecoration(labelText: 'Empresa'),
                        validator: (valor) =>
                            (valor == null || valor.trim().isEmpty) ? 'Escribe el nombre de tu empresa.' : null,
                      ),
                      const SizedBox(height: AppSpacing.md),
                      TextFormField(
                        controller: _emailController,
                        enabled: !_cargando,
                        keyboardType: TextInputType.emailAddress,
                        textInputAction: TextInputAction.next,
                        autocorrect: false,
                        enableSuggestions: false,
                        textCapitalization: TextCapitalization.none,
                        autofillHints: const [AutofillHints.username],
                        inputFormatters: [
                          TextInputFormatter.withFunction(
                            (anterior, nuevo) => nuevo.copyWith(text: nuevo.text.toLowerCase()),
                          ),
                        ],
                        decoration: const InputDecoration(labelText: 'Correo'),
                        validator: (valor) {
                          final correo = valor?.trim() ?? '';
                          return (correo.contains('@') && correo.contains('.')) ? null : 'Escribe un correo válido.';
                        },
                      ),
                      const SizedBox(height: AppSpacing.md),
                      TextFormField(
                        controller: _passwordController,
                        enabled: !_cargando,
                        obscureText: !_verPassword,
                        textInputAction: TextInputAction.done,
                        autocorrect: false,
                        enableSuggestions: false,
                        autofillHints: const [AutofillHints.password],
                        onFieldSubmitted: (_) => _enviar(),
                        decoration: InputDecoration(
                          labelText: 'Contraseña',
                          suffixIcon: IconButton(
                            tooltip: _verPassword ? 'Ocultar contraseña' : 'Mostrar contraseña',
                            icon: Icon(_verPassword ? Icons.visibility_off : Icons.visibility),
                            onPressed: () => setState(() => _verPassword = !_verPassword),
                          ),
                        ),
                        validator: (valor) => (valor == null || valor.isEmpty) ? 'Escribe tu contraseña.' : null,
                      ),
                      if (_error != null) ...[
                        const SizedBox(height: AppSpacing.md),
                        Semantics(
                          liveRegion: true,
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Icon(Icons.error_outline, size: 20, color: AppColors.error),
                              const SizedBox(width: AppSpacing.sm),
                              Expanded(
                                child: Text(
                                  _error!,
                                  key: const Key('error_acceso'),
                                  style: const TextStyle(color: AppColors.error),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                      const SizedBox(height: AppSpacing.lg),
                      SizedBox(
                        height: 48,
                        width: double.infinity,
                        child: ElevatedButton(
                          onPressed: _cargando ? null : _enviar,
                          style: ElevatedButton.styleFrom(minimumSize: const Size.fromHeight(48)),
                          child: _cargando ? const BotonCargando() : const Text('Ingresar'),
                        ),
                      ),
                      const SizedBox(height: AppSpacing.md),
                      TextButton(onPressed: _elegirOtraTienda, child: const Text('Elegir otra tienda')),
                      TextButton(onPressed: _soyCliente, child: const Text('Soy cliente')),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
