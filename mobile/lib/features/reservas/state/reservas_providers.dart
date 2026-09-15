import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/network/providers.dart';
import '../../catalogo/models/referencia.dart';
import '../../catalogo/state/catalogo_providers.dart';
import '../data/disponibilidad_repository.dart';
import '../data/horarios_repository.dart';
import '../data/notificaciones_repository.dart';
import '../data/reservas_repository.dart';
import '../models/disponibilidad_sucursal.dart';
import '../models/horario_sucursal.dart';
import '../models/notificacion_app.dart';
import '../models/reserva.dart';
import 'carrito_reserva_controller.dart';

final reservasRepositoryProvider = Provider<ReservasRepository>((ref) => ReservasRepository(ref.watch(dioProvider)));

final disponibilidadRepositoryProvider = Provider<DisponibilidadRepository>(
  (ref) => DisponibilidadRepository(ref.watch(dioProvider)),
);

final horariosRepositoryProvider = Provider<HorariosRepository>((ref) => HorariosRepository(ref.watch(dioProvider)));

final notificacionesRepositoryProvider = Provider<NotificacionesRepository>(
  (ref) => NotificacionesRepository(ref.watch(dioProvider)),
);

final horariosSucursalProvider = FutureProvider.family<List<HorarioSucursal>, int>(
  (ref, sucursalId) => ref.watch(horariosRepositoryProvider).porSucursal(sucursalId),
);

/// Disponibilidad de una variante en todas las sucursales (lo usa el
/// detalle de producto, para mostrar "disponible/agotado" por sucursal).
/// autoDispose: el stock cambia con cada compra, así que se vuelve a pedir
/// cada vez que se entra al detalle en vez de quedar cacheado la sesión.
final disponibilidadPorVarianteProvider = FutureProvider.autoDispose.family<List<DisponibilidadSucursal>, int>(
  (ref, varianteId) => ref.watch(disponibilidadRepositoryProvider).porVariante(varianteId),
);

/// Unidades disponibles de una variante sumando todas las sucursales.
final disponibleTotalProvider = FutureProvider.autoDispose.family<int, int>((ref, varianteId) async {
  final lista = await ref.watch(disponibilidadPorVarianteProvider(varianteId).future);
  return lista.fold<int>(0, (total, d) => total + d.cantidadDisponible);
});

final notificacionesProvider = FutureProvider<List<NotificacionApp>>(
  (ref) => ref.watch(notificacionesRepositoryProvider).listar(),
);

/// El punto que pide revisar el enunciado: de todas las sucursales, solo
/// las que tienen disponible AL MENOS 1 unidad de CADA variante del
/// carrito. Se recalcula solo si cambia el carrito.
final sucursalesDisponiblesProvider = FutureProvider<List<SucursalRef>>((ref) async {
  final carrito = ref.watch(carritoReservaProvider);
  if (carrito.isEmpty) return const [];

  final disponibilidadRepo = ref.watch(disponibilidadRepositoryProvider);
  // En un depósito no se reserva: no recibe clientes.
  final todasSucursales = (await ref.watch(sucursalesRefProvider.future)).where((s) => !s.esDeposito).toList();

  final listasPorVariante = await Future.wait(carrito.map((item) => disponibilidadRepo.porVariante(item.varianteId)));

  Set<int>? interseccion;
  for (final lista in listasPorVariante) {
    final conStock = lista.where((d) => d.cantidadDisponible >= 1).map((d) => d.sucursalId).toSet();
    interseccion = interseccion == null ? conStock : interseccion.intersection(conStock);
  }

  final idsValidos = interseccion ?? <int>{};
  return todasSucursales.where((s) => idsValidos.contains(s.id)).toList();
});

class MisReservasController extends StateNotifier<AsyncValue<List<Reserva>>> {
  MisReservasController(this._ref) : super(const AsyncValue.loading()) {
    cargar();
  }

  final Ref _ref;

  ReservasRepository get _repo => _ref.read(reservasRepositoryProvider);

  Future<void> cargar() async {
    state = const AsyncValue.loading();
    try {
      state = AsyncValue.data(await _repo.misReservas());
    } catch (error, stackTrace) {
      state = AsyncValue.error(error, stackTrace);
    }
  }

  Future<void> cancelar(int id) async {
    await _repo.cancelar(id);
    await cargar();
  }
}

final misReservasControllerProvider = StateNotifierProvider<MisReservasController, AsyncValue<List<Reserva>>>(
  (ref) => MisReservasController(ref),
);
