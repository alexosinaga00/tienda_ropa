import 'dart:async';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/network/mensaje_error.dart';
import '../../../core/theme/app_theme.dart';
import '../models/tienda.dart';
import '../state/tienda_controller.dart';

/// `#RRGGBB` → color, o null si no se entiende (nulo, vacío o mal formado). Nunca lanza.
Color? _colorDeAcento(String? hex) {
  if (hex == null) return null;
  final limpio = hex.trim();
  if (!RegExp(r'^#[0-9a-fA-F]{6}$').hasMatch(limpio)) return null;
  return Color(0xFF000000 | int.parse(limpio.substring(1), radix: 16));
}

/// Pantalla para elegir la tienda (`/tienda`): lista las organizaciones, con búsqueda por nombre o código.
class EligeTiendaScreen extends ConsumerStatefulWidget {
  const EligeTiendaScreen({super.key});

  @override
  ConsumerState<EligeTiendaScreen> createState() => _EligeTiendaScreenState();
}

enum _Fase { cargando, listo, error }

class _EligeTiendaScreenState extends ConsumerState<EligeTiendaScreen> {
  static const _espera = Duration(milliseconds: 400);

  final _busqueda = TextEditingController();
  Timer? _temporizador;
  _Fase _fase = _Fase.cargando;
  List<Tienda> _tiendas = const [];
  Object? _error;

  /// Numera cada consulta: una respuesta tardía de una búsqueda anterior se descarta.
  int _consulta = 0;
  bool _eligiendo = false;

  /// El aviso que ya se mostró (el controlador lo limpia después de la primera vez).
  String? _aviso;
  bool _limpiandoAviso = false;

  @override
  void initState() {
    super.initState();
    _cargar();
  }

  @override
  void dispose() {
    _temporizador?.cancel();
    _busqueda.dispose();
    super.dispose();
  }

  Future<void> _cargar() async {
    final numero = ++_consulta;
    setState(() {
      _fase = _Fase.cargando;
      _error = null;
    });
    try {
      final tiendas = await ref.read(tiendaRepositoryProvider).listar(q: _busqueda.text);
      if (!mounted || numero != _consulta) return;
      setState(() {
        _tiendas = tiendas;
        _fase = _Fase.listo;
      });
    } catch (e) {
      if (!mounted || numero != _consulta) return;
      setState(() {
        _error = e;
        _fase = _Fase.error;
      });
    }
  }

  void _alEscribir(String _) {
    _temporizador?.cancel();
    _temporizador = Timer(_espera, _cargar);
    setState(() {});
  }

  void _buscarYa(String _) {
    _temporizador?.cancel();
    _cargar();
  }

  void _limpiarBusqueda() {
    _temporizador?.cancel();
    _busqueda.clear();
    _cargar();
  }

  Future<void> _elegir(Tienda tienda) async {
    if (_eligiendo) return;
    _eligiendo = true;
    try {
      await ref.read(tiendaControllerProvider.notifier).elegir(tienda);
      if (!mounted) return;
      context.go('/home');
    } finally {
      _eligiendo = false;
    }
  }

  void _atenderAviso(String? aviso) {
    if (aviso == null || _limpiandoAviso) return;
    _aviso = aviso;
    _limpiandoAviso = true;
    // Se muestra una sola vez: el controlador lo borra cuando ya se pintó.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _limpiandoAviso = false;
      if (!mounted) return;
      ref.read(tiendaControllerProvider.notifier).limpiarAviso();
    });
  }

  @override
  Widget build(BuildContext context) {
    _atenderAviso(ref.watch(tiendaControllerProvider.select((s) => s.aviso)));
    final guardada = ref.watch(tiendaActualProvider);

    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: false,
        leading: context.canPop() ? BackButton(onPressed: () => context.pop()) : null,
        title: const Text('Elige tu tienda'),
      ),
      body: SafeArea(
        child: Column(
          children: [
            if (_aviso != null) _FranjaAviso(texto: _aviso!),
            Padding(
              padding: const EdgeInsets.fromLTRB(AppSpacing.md, AppSpacing.sm, AppSpacing.md, AppSpacing.sm),
              child: TextField(
                controller: _busqueda,
                textInputAction: TextInputAction.search,
                onChanged: _alEscribir,
                onSubmitted: _buscarYa,
                decoration: InputDecoration(
                  labelText: 'Buscar tienda',
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: _busqueda.text.isEmpty
                      ? null
                      : IconButton(
                          tooltip: 'Borrar búsqueda',
                          icon: const Icon(Icons.close),
                          onPressed: _limpiarBusqueda,
                        ),
                ),
              ),
            ),
            Expanded(child: _contenido(guardada)),
            Padding(
              padding: const EdgeInsets.fromLTRB(AppSpacing.md, 0, AppSpacing.md, AppSpacing.sm),
              child: TextButton(
                style: TextButton.styleFrom(minimumSize: const Size.fromHeight(48)),
                onPressed: () => context.push('/vendedor/acceso'),
                child: const Text('Soy personal de una tienda'),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _contenido(Tienda? guardada) {
    switch (_fase) {
      case _Fase.cargando:
        return const _Esqueleto();
      case _Fase.error:
        final sinConexion = _error != null && esSinConexion(_error!);
        return _EstadoError(
          sinConexion: sinConexion,
          mensaje: sinConexion
              ? 'Sin conexión. Revisa tu internet e intenta de nuevo.'
              : mensajeDeError(_error ?? Object(), 'No se pudieron cargar las tiendas.'),
          onReintentar: _cargar,
          nombreGuardada: sinConexion ? guardada?.nombre : null,
          onVolver: () => context.go('/home'),
        );
      case _Fase.listo:
        if (_tiendas.isEmpty) return const _SinResultados();
        return ListView.separated(
          padding: const EdgeInsets.all(AppSpacing.md),
          itemCount: _tiendas.length,
          separatorBuilder: (_, _) => const SizedBox(height: AppSpacing.md),
          itemBuilder: (context, i) => _TarjetaTienda(tienda: _tiendas[i], onTap: () => _elegir(_tiendas[i])),
        );
    }
  }
}

class _FranjaAviso extends StatelessWidget {
  const _FranjaAviso({required this.texto});

  final String texto;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: AppColors.fondoAlterno,
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.md, vertical: AppSpacing.md),
      child: Row(
        children: [
          const Icon(Icons.info_outline, color: AppColors.advertencia),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(texto, style: Theme.of(context).textTheme.bodyLarge),
          ),
        ],
      ),
    );
  }
}

class _TarjetaTienda extends StatelessWidget {
  const _TarjetaTienda({required this.tienda, required this.onTap});

  final Tienda tienda;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final acento = _colorDeAcento(tienda.colorAcento) ?? AppColors.acento;
    final tema = Theme.of(context).textTheme;
    final forma = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(AppRadius.base),
      side: const BorderSide(color: AppColors.borde),
    );

    return Semantics(
      button: true,
      label: 'Elegir la tienda ${tienda.nombre}',
      excludeSemantics: true,
      onTap: onTap,
      child: Material(
        color: AppColors.fondo,
        shape: forma,
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: onTap,
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 48),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Container(
                  height: 112,
                  color: acento.withValues(alpha: 0.12),
                  alignment: Alignment.center,
                  child: _LogoOMonograma(tienda: tienda, acento: acento),
                ),
                Padding(
                  padding: const EdgeInsets.all(AppSpacing.md),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        tienda.nombre,
                        style: tema.titleLarge?.copyWith(color: AppColors.texto, fontWeight: FontWeight.w600),
                      ),
                      const SizedBox(height: AppSpacing.xs),
                      Text(tienda.codigo, style: tema.bodyMedium?.copyWith(color: AppColors.textoTenue)),
                    ],
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

class _LogoOMonograma extends StatelessWidget {
  const _LogoOMonograma({required this.tienda, required this.acento});

  final Tienda tienda;
  final Color acento;

  @override
  Widget build(BuildContext context) {
    final monograma = _Monograma(siglas: tienda.siglas, acento: acento);
    final logo = tienda.logoUrl;
    if (logo == null || logo.isEmpty) return monograma;
    return Padding(
      padding: const EdgeInsets.all(AppSpacing.md),
      child: CachedNetworkImage(
        imageUrl: logo,
        height: 80,
        fit: BoxFit.contain,
        placeholder: (context, url) => const SizedBox(height: 80),
        errorWidget: (context, url, error) => monograma,
      ),
    );
  }
}

class _Monograma extends StatelessWidget {
  const _Monograma({required this.siglas, required this.acento});

  final String siglas;
  final Color acento;

  @override
  Widget build(BuildContext context) {
    final colorTexto = acento.computeLuminance() > 0.5 ? AppColors.texto : Colors.white;
    return Container(
      width: 72,
      height: 72,
      alignment: Alignment.center,
      decoration: BoxDecoration(color: acento, shape: BoxShape.circle),
      child: Text(
        siglas,
        style: Theme.of(
          context,
        ).textTheme.headlineSmall?.copyWith(color: colorTexto, fontWeight: FontWeight.w700),
      ),
    );
  }
}

/// Cuatro tarjetas grises mientras llega la lista.
class _Esqueleto extends StatelessWidget {
  const _Esqueleto();

  @override
  Widget build(BuildContext context) {
    return ListView.separated(
      key: const Key('esqueleto_tiendas'),
      physics: const NeverScrollableScrollPhysics(),
      padding: const EdgeInsets.all(AppSpacing.md),
      itemCount: 4,
      separatorBuilder: (_, _) => const SizedBox(height: AppSpacing.md),
      itemBuilder: (_, _) => Container(
        height: 188,
        decoration: BoxDecoration(
          color: AppColors.fondoAlterno,
          borderRadius: BorderRadius.circular(AppRadius.base),
          border: Border.all(color: AppColors.borde),
        ),
      ),
    );
  }
}

class _SinResultados extends StatelessWidget {
  const _SinResultados();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.storefront_outlined, size: 48, color: AppColors.textoTenue),
            const SizedBox(height: AppSpacing.md),
            Text(
              'No encontramos tiendas con ese nombre',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyLarge,
            ),
          ],
        ),
      ),
    );
  }
}

class _EstadoError extends StatelessWidget {
  const _EstadoError({
    required this.sinConexion,
    required this.mensaje,
    required this.onReintentar,
    required this.onVolver,
    this.nombreGuardada,
  });

  final bool sinConexion;
  final String mensaje;
  final VoidCallback onReintentar;
  final VoidCallback onVolver;

  /// El nombre de la tienda guardada, si la hay y no hay conexión: ofrece volver a ella.
  final String? nombreGuardada;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(sinConexion ? Icons.cloud_off_outlined : Icons.error_outline, size: 48, color: AppColors.textoTenue),
            const SizedBox(height: AppSpacing.md),
            Text(mensaje, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyLarge),
            const SizedBox(height: AppSpacing.lg),
            ElevatedButton(onPressed: onReintentar, child: const Text('Reintentar')),
            if (nombreGuardada != null) ...[
              const SizedBox(height: AppSpacing.sm),
              TextButton(
                onPressed: onVolver,
                style: TextButton.styleFrom(minimumSize: const Size.fromHeight(48)),
                child: Text('Volver a $nombreGuardada'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
