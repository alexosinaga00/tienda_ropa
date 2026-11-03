import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../core/theme/app_theme.dart';
import '../../tienda/state/tienda_controller.dart';
import '../state/auth_controller.dart';

/// Solo rutas internas y que no sean de auth (evita volver a /login o
/// saltar a una URL externa armada a mano en el query param).
String _destinoTrasLogin(String? returnTo) {
  if (returnTo == null || !returnTo.startsWith('/') || returnTo.startsWith('//')) {
    return '/home';
  }
  final ruta = Uri.parse(returnTo).path;
  if (ruta == '/login' || ruta == '/registro' || ruta == '/splash') {
    return '/home';
  }
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
    final destino = _destinoTrasLogin(
      GoRouterState.of(context).uri.queryParameters['returnTo'],
    );

    setState(() => _cargando = true);
    try {
      await ref
          .read(authControllerProvider.notifier)
          .login(
            email: _emailController.text.trim(),
            password: _passwordController.text,
          );
      // Navegación explícita: el catálogo y el detalle abren esta pantalla
      // con context.push(), y el redirect del router se evalúa contra la
      // ruta base de la pila (/home), no contra /login apilada encima --
      // así que por sí solo nunca la saca y el login "no hace nada".
      if (mounted) context.go(destino);
    } catch (_) {
      if (!mounted) return;
      final mensaje =
          ref.read(authControllerProvider).error ??
          'No se pudo iniciar sesión.';
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(mensaje)));
    } finally {
      if (mounted) setState(() => _cargando = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    // Íconos claros en la barra de estado: la portada oscura llega hasta
    // el borde superior (SafeArea sin `top`, el padding lo pone la portada).
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: Scaffold(
        backgroundColor: AppColors.fondo,
        body: SafeArea(
          top: false,
          child: SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const _PortadaProbador(),
                Padding(
                  padding: const EdgeInsets.all(AppSpacing.xl),
                  child: Form(
                    key: _formKey,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text(
                          'Bienvenido/a',
                          style: Theme.of(context).textTheme.headlineMedium,
                        ),
                        const SizedBox(height: AppSpacing.xs),
                        const Text(
                          'Ingresá para continuar',
                          style: TextStyle(color: AppColors.textoTenue),
                        ),
                        const SizedBox(height: AppSpacing.xl),
                        TextFormField(
                          controller: _emailController,
                          keyboardType: TextInputType.emailAddress,
                          decoration: const InputDecoration(labelText: 'Email'),
                          validator: (valor) =>
                              (valor == null || !valor.contains('@'))
                              ? 'Ingresá un email válido'
                              : null,
                        ),
                        const SizedBox(height: AppSpacing.md),
                        TextFormField(
                          controller: _passwordController,
                          obscureText: true,
                          decoration: const InputDecoration(
                            labelText: 'Contraseña',
                          ),
                          validator: (valor) => (valor == null || valor.isEmpty)
                              ? 'Ingresá tu contraseña'
                              : null,
                        ),
                        const SizedBox(height: AppSpacing.xl),
                        ElevatedButton(
                          onPressed: _cargando ? null : _enviar,
                          child: _cargando
                              ? const SizedBox(
                                  height: 20,
                                  width: 20,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                    color: Colors.white,
                                  ),
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
      ),
    );
  }
}

// Paleta terracota de CLAUDE.md (carbón + acento cuero). Local a la
// portada: el tema global de la app todavía usa la paleta anterior.
const _carbon = Color(0xFF241C18);
const _carbonClaro = Color(0xFF3A2A22);
const _cuero = Color(0xFF9A3E1F);
const _cueroSuave = Color(0xFFE3D2C1);
const _crema = Color(0xFFF0DDCE);
const _textoPortada = Color(0xFFC9BCB2);

/// Portada del login: marca + gancho del probador virtual, sin imágenes
/// (no depende de red ni de assets, así nunca queda un hueco vacío).
class _PortadaProbador extends ConsumerWidget {
  const _PortadaProbador();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // El nombre de la tienda elegida; sin tienda (no debería ocurrir en el login) queda la marca de la plataforma.
    final nombreTienda = ref.watch(tiendaControllerProvider.select((s) => s.tienda?.nombre)) ?? 'FashionStore';
    final arriba = MediaQuery.paddingOf(context).top;
    return ClipRRect(
      borderRadius: const BorderRadius.vertical(bottom: Radius.circular(18)),
      child: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [_carbon, _carbonClaro],
          ),
        ),
        child: Stack(
          children: [
            // Aros decorativos, como el reflejo de un espejo.
            Positioned(
              top: -60,
              right: -70,
              child: _Aro(diametro: 240, color: _cuero.withValues(alpha: 0.35)),
            ),
            Positioned(
              top: 10,
              right: -20,
              child: _Aro(
                diametro: 150,
                color: _cueroSuave.withValues(alpha: 0.10),
              ),
            ),
            Padding(
              padding: EdgeInsets.fromLTRB(
                AppSpacing.xl,
                arriba + AppSpacing.lg,
                AppSpacing.xl,
                AppSpacing.xl,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const _VisorAR(),
                  const SizedBox(height: AppSpacing.lg),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppSpacing.sm + 2,
                      vertical: AppSpacing.xs,
                    ),
                    decoration: BoxDecoration(
                      color: _cuero.withValues(alpha: 0.28),
                      borderRadius: BorderRadius.circular(999),
                      border: Border.all(color: _cuero),
                    ),
                    child: const Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.view_in_ar, size: 14, color: _crema),
                        SizedBox(width: AppSpacing.xs + 2),
                        Text(
                          'PROBADOR VIRTUAL',
                          style: TextStyle(
                            color: _crema,
                            fontSize: 11,
                            fontWeight: FontWeight.w700,
                            letterSpacing: 1.4,
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: AppSpacing.md),
                  Text(
                    nombreTienda,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontFamily: 'serif',
                      fontStyle: FontStyle.italic,
                      fontWeight: FontWeight.w600,
                      fontSize: 34,
                      height: 1.1,
                      color: _crema,
                    ),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  const Text(
                    'Probátela antes de comprarla.',
                    style: TextStyle(
                      fontFamily: 'serif',
                      fontSize: 20,
                      height: 1.25,
                      color: Colors.white,
                    ),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  const Text(
                    'Mirá cómo te quedan poleras, camisas y chamarras en tiempo real, '
                    'con la cámara de tu celular.',
                    style: TextStyle(
                      fontSize: 14,
                      height: 1.4,
                      color: _textoPortada,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Aro extends StatelessWidget {
  const _Aro({required this.diametro, required this.color});

  final double diametro;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: diametro,
      height: diametro,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: Border.all(color: color, width: 2),
      ),
    );
  }
}

/// Prenda dentro de un visor con esquinas de escaneo, la idea del modo espejo.
class _VisorAR extends StatelessWidget {
  const _VisorAR();

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 72,
      height: 72,
      child: CustomPaint(
        painter: _EsquinasVisor(),
        child: const Center(
          child: Icon(Icons.checkroom, size: 36, color: _crema),
        ),
      ),
    );
  }
}

class _EsquinasVisor extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final pincel = Paint()
      ..color = _cueroSuave
      ..strokeWidth = 2.5
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round;
    const largo = 16.0;
    final w = size.width, h = size.height;
    final esquinas = [
      [Offset(0, largo), Offset.zero, const Offset(largo, 0)],
      [Offset(w - largo, 0), Offset(w, 0), Offset(w, largo)],
      [Offset(0, h - largo), Offset(0, h), Offset(largo, h)],
      [Offset(w - largo, h), Offset(w, h), Offset(w, h - largo)],
    ];
    for (final e in esquinas) {
      canvas.drawPath(
        Path()
          ..moveTo(e[0].dx, e[0].dy)
          ..lineTo(e[1].dx, e[1].dy)
          ..lineTo(e[2].dx, e[2].dy),
        pincel,
      );
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
