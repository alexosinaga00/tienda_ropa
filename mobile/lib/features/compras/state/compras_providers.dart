import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/network/providers.dart';
import '../../auth/state/auth_controller.dart';
import '../../catalogo/models/referencia.dart';
import '../../catalogo/models/variante_lookup.dart';
import '../../catalogo/state/catalogo_providers.dart';
import '../../reservas/state/reservas_providers.dart'
    show disponibilidadRepositoryProvider, disponibilidadPorVarianteProvider, disponibleTotalProvider;
import '../data/carrito_repository.dart';
import '../data/direcciones_repository.dart';
import '../data/envios_repository.dart';
import '../data/pagos_repository.dart';
import '../data/ventas_repository.dart';
import '../data/zonas_envio_repository.dart';
import '../models/carrito.dart';
import '../models/cotizacion_envio.dart';
import '../models/direccion_cliente.dart';
import '../models/envio.dart';
import '../models/venta.dart';
import '../models/zona_envio.dart';
import 'carrito_controller.dart';
import 'mis_compras_controller.dart';

final carritoRepositoryProvider = Provider<CarritoRepository>((ref) => CarritoRepository(ref.watch(dioProvider)));

final direccionesRepositoryProvider = Provider<DireccionesRepository>(
  (ref) => DireccionesRepository(ref.watch(dioProvider)),
);

final zonasEnvioRepositoryProvider = Provider<ZonasEnvioRepository>(
  (ref) => ZonasEnvioRepository(ref.watch(dioProvider)),
);

final enviosRepositoryProvider = Provider<EnviosRepository>((ref) => EnviosRepository(ref.watch(dioProvider)));

final ventasRepositoryProvider = Provider<VentasRepository>((ref) => VentasRepository(ref.watch(dioProvider)));

final pagosRepositoryProvider = Provider<PagosRepository>((ref) => PagosRepository(ref.watch(dioProvider)));

/// Se rehace por sesión: son dato personal y, además, el selector de
/// direcciones del checkout las ofrece como destino de envío -- sin esto, al
/// siguiente cliente del mismo teléfono le aparecían las del anterior.
/// Sin sesión no consulta: quedaría en 401.
final misDireccionesProvider = FutureProvider<List<DireccionCliente>>((ref) async {
  final autenticado = ref.watch(authControllerProvider.select((s) => s.estaAutenticado));
  if (!autenticado) return const <DireccionCliente>[];
  return ref.watch(direccionesRepositoryProvider).misDirecciones();
});

final zonasEnvioProvider = FutureProvider<List<ZonaEnvio>>((ref) => ref.watch(zonasEnvioRepositoryProvider).listar());

/// Cotización en vivo de envío a domicilio para una dirección concreta,
/// según la cantidad de prendas del carrito actual.
final cotizacionEnvioProvider = FutureProvider.autoDispose.family<CotizacionEnvio, int>((ref, direccionId) {
  final cantidad = ref.watch(carritoControllerProvider).valueOrNull?.cantidadTotal ?? 1;
  return ref.watch(enviosRepositoryProvider).cotizar(direccionId: direccionId, cantidadPrendas: cantidad);
});

/// Vista previa de subtotal/descuento/total del carrito, con las
/// promociones vigentes ya aplicadas. Se recalcula solo cuando cambia el
/// carrito (agregar/quitar/actualizar cantidad).
final resumenCarritoProvider = FutureProvider.autoDispose<ResumenCarrito?>((ref) async {
  final carrito = ref.watch(carritoControllerProvider).valueOrNull;
  if (carrito == null || carrito.vacio) return null;
  return ref.watch(carritoRepositoryProvider).aplicarPromocion();
});

/// Sucursales que tienen stock de TODAS las variantes del carrito real de
/// compra (a diferencia de sucursalesDisponiblesProvider en reservas, que
/// mira el carrito temporal de reserva). Hace falta tanto para retiro en
/// sucursal como para envío a domicilio: registrar_venta_digital descuenta
/// stock de una única sucursal en los dos casos, no hay "sucursal
/// despachadora" separada.
final sucursalesConStockCarritoProvider = FutureProvider.autoDispose<List<SucursalRef>>((ref) async {
  final carrito = ref.watch(carritoControllerProvider).valueOrNull;
  if (carrito == null || carrito.vacio) return const [];

  final disponibilidadRepo = ref.watch(disponibilidadRepositoryProvider);
  final todasSucursales = await ref.watch(sucursalesRefProvider.future);

  final listasPorVariante = await Future.wait(
    carrito.detalle.map((linea) => disponibilidadRepo.porVariante(linea.varianteId)),
  );

  Set<int>? interseccion;
  for (var i = 0; i < carrito.detalle.length; i++) {
    final cantidadRequerida = carrito.detalle[i].cantidad;
    final conStock = listasPorVariante[i]
        .where((d) => d.cantidadDisponible >= cantidadRequerida)
        .map((d) => d.sucursalId)
        .toSet();
    interseccion = interseccion == null ? conStock : interseccion.intersection(conStock);
  }

  final idsValidos = interseccion ?? <int>{};
  return todasSucursales.where((s) => idsValidos.contains(s.id)).toList();
});

/// Seguimiento del envío de una compra (null si no tiene envío).
final envioDeCompraProvider = FutureProvider.autoDispose.family<Envio?, int>(
  (ref, ventaId) => ref.watch(enviosRepositoryProvider).obtenerPorVenta(ventaId),
);

/// Después de pagar, cancelar o reintentar una compra cambian el stock, el
/// carrito (cancelar devuelve las prendas) y el estado de la compra.
void refrescarDespuesDeCompra(WidgetRef ref) {
  ref.invalidate(disponibilidadPorVarianteProvider);
  ref.invalidate(disponibleTotalProvider);
  ref.invalidate(sucursalesConStockCarritoProvider);
  ref.invalidate(compraDetalleProvider);
  ref.invalidate(envioDeCompraProvider);
  ref.read(carritoControllerProvider.notifier).cargar();
  ref.read(misComprasControllerProvider.notifier).cargar();
}

/// Resuelve nombre/foto/talla/color en lote para un conjunto de variantes,
/// indexado por variante_id -- lo comparten el carrito y el comprobante de
/// compra (ver carrito_controller.dart y compraDetalleProvider).
Future<Map<int, VarianteLookupItem>> lookupVariantes(Ref ref, List<int> varianteIds) async {
  if (varianteIds.isEmpty) return const {};
  final lookup = await ref.read(catalogoRepositoryProvider).detallePorVariantes(varianteIds.toSet().toList());
  return {for (final item in lookup) if (item.varianteId != null) item.varianteId!: item};
}

final compraDetalleProvider = FutureProvider.autoDispose.family<Venta, int>((ref, ventaId) async {
  final venta = await ref.watch(ventasRepositoryProvider).comprobante(ventaId);
  if (venta.detalle.isEmpty) return venta;

  final porVariante = await lookupVariantes(ref, venta.detalle.map((l) => l.varianteId).toList());
  final detalleResuelto = venta.detalle.map((linea) {
    final item = porVariante[linea.varianteId];
    return linea.conExhibicion(
      productoNombre: item?.productoNombre,
      imagenPrincipal: item?.imagenPrincipal,
      tallaCodigo: item?.tallaCodigo,
      colorNombre: item?.colorNombre,
    );
  }).toList();
  return venta.conDetalle(detalleResuelto);
});
