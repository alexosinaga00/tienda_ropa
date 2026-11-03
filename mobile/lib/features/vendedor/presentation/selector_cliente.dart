import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_theme.dart';
import '../data/clientes_local_repository.dart';
import '../models/cliente_local.dart';
import '../state/sincronizacion_providers.dart';
import 'catalogo_local_screen.dart' show esperaBusquedaCatalogoLocal;

/// Cuántos clientes se leen por página.
const tamanoPaginaClientes = 20;

const textoSinClientes =
    'No encontramos clientes. Sin conexión solo se pueden usar los clientes ya descargados; actualiza tus datos.';

/// Abre el selector de clientes (hoja inferior) y devuelve el elegido, o `null` si se cerró sin elegir. Solo ofrece los clientes
/// del servidor guardados en el teléfono: son los únicos que una operación sin conexión puede usar.
Future<ClienteLocal?> mostrarSelectorCliente(BuildContext context, WidgetRef ref) async {
  final repositorio = await ref.read(clientesLocalProvider.future);
  if (repositorio == null || !context.mounted) return null;
  return showModalBottomSheet<ClienteLocal>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    showDragHandle: true,
    builder: (sheet) => Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(sheet).bottom),
      child: SizedBox(
        height: MediaQuery.sizeOf(sheet).height * 0.9,
        child: SelectorCliente(repositorio: repositorio),
      ),
    ),
  );
}

/// El contenido del selector (separado para poder probarlo sin la hoja).
class SelectorCliente extends StatefulWidget {
  const SelectorCliente({super.key, required this.repositorio});

  final ClientesLocalRepository repositorio;

  @override
  State<SelectorCliente> createState() => _SelectorClienteState();
}

class _SelectorClienteState extends State<SelectorCliente> {
  final _busqueda = TextEditingController();
  final _scroll = ScrollController();
  Timer? _espera;

  String _texto = '';
  final List<ClienteLocal> _clientes = [];
  bool _cargando = true;
  bool _cargandoMas = false;
  bool _hayMas = false;
  bool _error = false;
  int _generacion = 0;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_alDesplazar);
    unawaited(_recargar());
  }

  @override
  void dispose() {
    _espera?.cancel();
    _scroll.dispose();
    _busqueda.dispose();
    super.dispose();
  }

  void _alDesplazar() {
    if (_scroll.hasClients && _scroll.position.extentAfter < 400) unawaited(_cargarMas());
  }

  Future<void> _recargar() async {
    final generacion = ++_generacion;
    setState(() {
      _cargando = _clientes.isEmpty;
      _cargandoMas = false;
      _error = false;
    });
    try {
      final pagina = await widget.repositorio.buscar(texto: _texto, limite: tamanoPaginaClientes);
      if (!mounted || generacion != _generacion) return;
      setState(() {
        _clientes
          ..clear()
          ..addAll(pagina);
        _hayMas = pagina.length == tamanoPaginaClientes;
        _cargando = false;
      });
      _revisarSiHayHueco();
    } catch (_) {
      if (!mounted || generacion != _generacion) return;
      setState(() {
        _error = true;
        _cargando = false;
      });
    }
  }

  Future<void> _cargarMas() async {
    if (_cargando || _cargandoMas || !_hayMas || _error) return;
    final generacion = _generacion;
    setState(() => _cargandoMas = true);
    try {
      final pagina = await widget.repositorio.buscar(
        texto: _texto,
        limite: tamanoPaginaClientes,
        desplazamiento: _clientes.length,
      );
      if (!mounted || generacion != _generacion) return;
      final conocidos = {for (final c in _clientes) c.id};
      setState(() {
        _clientes.addAll(pagina.where((c) => !conocidos.contains(c.id)));
        _hayMas = pagina.length == tamanoPaginaClientes;
        _cargandoMas = false;
      });
      _revisarSiHayHueco();
    } catch (_) {
      if (!mounted || generacion != _generacion) return;
      setState(() {
        _hayMas = false;
        _cargandoMas = false;
      });
    }
  }

  void _revisarSiHayHueco() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && _scroll.hasClients && _scroll.position.extentAfter < 400) unawaited(_cargarMas());
    });
  }

  void _alEscribir(String valor) {
    _espera?.cancel();
    _espera = Timer(esperaBusquedaCatalogoLocal, () => _aplicarTexto(valor));
    setState(() {});
  }

  void _aplicarTexto(String valor) {
    _espera?.cancel();
    if (!mounted) return;
    if (valor.trim() == _texto) return;
    _texto = valor.trim();
    unawaited(_recargar());
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          padding: const EdgeInsets.only(left: AppSpacing.md, right: AppSpacing.sm),
          child: Row(
            children: [
              Expanded(
                child: Semantics(
                  header: true,
                  child: Text(
                    'Elige un cliente',
                    style: Theme.of(context).textTheme.titleLarge?.copyWith(color: AppColors.texto, fontWeight: FontWeight.w600),
                  ),
                ),
              ),
              IconButton(
                tooltip: 'Cerrar',
                icon: const Icon(Icons.close, size: 24),
                onPressed: () => Navigator.of(context).pop(),
              ),
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.md, AppSpacing.sm, AppSpacing.md, AppSpacing.sm),
          child: TextField(
            key: const Key('buscador_clientes'),
            controller: _busqueda,
            textInputAction: TextInputAction.search,
            onChanged: _alEscribir,
            onSubmitted: _aplicarTexto,
            decoration: InputDecoration(
              hintText: 'Buscar por nombre o CI/NIT',
              prefixIcon: const Icon(Icons.search, size: 24),
              suffixIcon: _busqueda.text.isEmpty
                  ? null
                  : IconButton(
                      tooltip: 'Borrar búsqueda',
                      icon: const Icon(Icons.close, size: 24),
                      onPressed: () {
                        _busqueda.clear();
                        _aplicarTexto('');
                        setState(() {});
                      },
                    ),
            ),
          ),
        ),
        Expanded(child: _cuerpo()),
      ],
    );
  }

  Widget _cuerpo() {
    if (_cargando) return const Center(child: CircularProgressIndicator());
    if (_error) {
      return _Mensaje(
        icono: Icons.error_outline,
        texto: 'No pudimos leer los clientes guardados en el teléfono.',
        boton: 'Reintentar',
        alPulsar: () => unawaited(_recargar()),
      );
    }
    if (_clientes.isEmpty) return const _Mensaje(icono: Icons.person_off_outlined, texto: textoSinClientes);

    return ListView.builder(
      controller: _scroll,
      itemCount: _clientes.length + 1,
      itemBuilder: (context, i) {
        if (i == _clientes.length) {
          return Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Center(child: _cargandoMas ? const CircularProgressIndicator() : const SizedBox(height: 4)),
          );
        }
        final c = _clientes[i];
        final ci = c.ciNit?.trim();
        return ListTile(
          key: Key('cliente_${c.id}'),
          minTileHeight: 56,
          leading: const Icon(Icons.person_outline, size: 24, color: AppColors.texto),
          title: Text(c.nombreCompleto, maxLines: 1, overflow: TextOverflow.ellipsis),
          subtitle: ci == null || ci.isEmpty ? null : Text('CI/NIT: $ci', maxLines: 1, overflow: TextOverflow.ellipsis),
          onTap: () => Navigator.of(context).pop(c),
        );
      },
    );
  }
}

class _Mensaje extends StatelessWidget {
  const _Mensaje({required this.icono, required this.texto, this.boton, this.alPulsar});

  final IconData icono;
  final String texto;
  final String? boton;
  final VoidCallback? alPulsar;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icono, size: 48, color: AppColors.textoTenue),
            const SizedBox(height: AppSpacing.md),
            Text(texto, key: const Key('mensaje_clientes'), textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyLarge),
            if (boton != null) ...[
              const SizedBox(height: AppSpacing.lg),
              ElevatedButton(
                style: ElevatedButton.styleFrom(minimumSize: const Size(160, 52)),
                onPressed: alPulsar,
                child: Text(boton!),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
