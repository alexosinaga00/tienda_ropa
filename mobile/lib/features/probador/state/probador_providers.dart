import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/providers.dart';
import '../../catalogo/state/catalogo_providers.dart';
import '../data/probador_repository.dart';
import '../models/activo_probador.dart';

final probadorRepositoryProvider = Provider<ProbadorRepository>(
  (ref) => ProbadorRepository(ref.watch(dioProvider)),
);

class PrendaProbador {
  const PrendaProbador({
    required this.varianteId,
    required this.productoId,
    required this.nombre,
    required this.assets,
  });

  final int varianteId;
  final int productoId;
  final String nombre;
  final AssetsVariante assets;
}

/// Recorre el catálogo buscando productos que admiten probador Y que ya
/// tienen un overlay validado: `admite_probador` es a nivel de producto,
/// pero el asset se sube por variante, así que no todo lo que admite
/// probador tiene ya la imagen lista. Lo que sí tiene se usa para llenar
/// el selector horizontal de la pantalla del probador.
final prendasProbadorProvider = FutureProvider<List<PrendaProbador>>((ref) async {
  final catalogoRepo = ref.watch(catalogoRepositoryProvider);
  final probadorRepo = ref.watch(probadorRepositoryProvider);

  final items = await catalogoRepo.listar(pagina: 1, tamanio: 50);
  final candidatos = items.where((i) => i.admiteProbador);

  final prendas = <PrendaProbador>[];
  for (final item in candidatos) {
    try {
      final detalle = await catalogoRepo.detalle(item.id);
      if (detalle.variantes.isEmpty) continue;
      final varianteId = detalle.variantes.first.id;
      final assets = await probadorRepo.obtenerAssets(varianteId);
      prendas.add(PrendaProbador(varianteId: varianteId, productoId: item.id, nombre: item.nombre, assets: assets));
    } catch (_) {
      // Sin overlay validado todavía para esta variante: no aparece en el selector.
      continue;
    }
  }
  return prendas;
});

/// Los assets del probador de una variante, o null si todavía no tiene un overlay validado (el backend responde 404).
/// Los botones "Probar" del detalle y del carrito la usan para decidir si se muestran. Cualquier otro error (red,
/// sesión) se propaga: el botón simplemente no aparece.
final assetsProbadorProvider = FutureProvider.autoDispose.family<AssetsVariante?, int>((ref, varianteId) async {
  try {
    return await ref.watch(probadorRepositoryProvider).obtenerAssets(varianteId);
  } on DioException catch (e) {
    if (e.response?.statusCode == 404) return null;
    rethrow;
  }
});

/// La prenda de una variante concreta lista para el probador (nombre incluido), o null si no tiene overlay validado.
final prendaProbadorPorVarianteProvider = FutureProvider.autoDispose.family<PrendaProbador?, int>((
  ref,
  varianteId,
) async {
  final assets = await ref.watch(assetsProbadorProvider(varianteId).future);
  if (assets == null) return null;
  final datos = await ref.watch(catalogoRepositoryProvider).detallePorVariantes([varianteId]);
  if (datos.isEmpty) return null;
  return PrendaProbador(
    varianteId: varianteId,
    productoId: datos.first.productoId,
    nombre: datos.first.productoNombre,
    assets: assets,
  );
});

/// La lista que muestra el probador. Con [varianteInicial] (la prenda que el cliente acaba de elegir en el detalle o
/// en el carrito) esa prenda va primera -y por eso el probador abre con ella puesta- y se quitan las demás variantes
/// de su mismo producto para no repetirlo. Sin inicial, o si esa variante no tiene overlay, es la lista de siempre.
final prendasParaProbadorProvider = FutureProvider.autoDispose.family<List<PrendaProbador>, int?>((
  ref,
  varianteInicial,
) async {
  final base = await ref.watch(prendasProbadorProvider.future);
  if (varianteInicial == null) return base;

  PrendaProbador? inicial;
  try {
    inicial = await ref.watch(prendaProbadorPorVarianteProvider(varianteInicial).future);
  } catch (_) {
    // Sin red o sin sesión para resolver la inicial: el probador abre con su lista habitual.
    return base;
  }
  if (inicial == null) return base;
  final elegida = inicial;
  return [elegida, ...base.where((p) => p.productoId != elegida.productoId)];
});
