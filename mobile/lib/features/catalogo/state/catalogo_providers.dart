import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/network/providers.dart';
import '../data/catalogo_repository.dart';
import '../data/referencia_repository.dart';
import '../models/catalogo_detalle.dart';
import '../models/referencia.dart';

final catalogoRepositoryProvider = Provider<CatalogoRepository>((ref) => CatalogoRepository(ref.watch(apiClientProvider)));

final detalleProductoProvider = FutureProvider.family<CatalogoDetalle, int>(
  (ref, productoId) => ref.watch(catalogoRepositoryProvider).detalle(productoId),
);

final referenciaRepositoryProvider = Provider<ReferenciaRepository>(
  (ref) => ReferenciaRepository(ref.watch(apiClientProvider)),
);

// Catálogos de referencia: se piden una sola vez y quedan en caché para
// toda la sesión (FutureProvider sin autoDispose), los usan tanto el
// panel de filtros como el detalle de producto.
final categoriasRefProvider = FutureProvider<List<CategoriaRef>>(
  (ref) => ref.watch(referenciaRepositoryProvider).categorias(),
);
final tallasRefProvider = FutureProvider<List<TallaRef>>((ref) => ref.watch(referenciaRepositoryProvider).tallas());
final coloresRefProvider = FutureProvider<List<ColorRef>>(
  (ref) => ref.watch(referenciaRepositoryProvider).colores(),
);
final materialesRefProvider = FutureProvider<List<MaterialRef>>(
  (ref) => ref.watch(referenciaRepositoryProvider).materiales(),
);
final temporadasRefProvider = FutureProvider<List<TemporadaRef>>(
  (ref) => ref.watch(referenciaRepositoryProvider).temporadas(),
);
final sucursalesRefProvider = FutureProvider<List<SucursalRef>>(
  (ref) => ref.watch(referenciaRepositoryProvider).sucursales(),
);
