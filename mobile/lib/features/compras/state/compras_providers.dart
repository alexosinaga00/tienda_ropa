import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../../core/network/providers.dart';
import '../../auth/state/auth_controller.dart';
import '../../catalogo/models/catalogo_detalle.dart' show VarianteCatalogo;
import '../../catalogo/models/referencia.dart';
import '../../catalogo/models/variante_lookup.dart';
import '../../catalogo/state/catalogo_providers.dart';
import '../../reservas/state/reservas_providers.dart'
    show disponibilidadRepositoryProvider, disponibilidadPorVarianteProvider, disponibleTotalProvider;
import '../data/carrito_repository.dart';
import '../data/direcciones_repository.dart';
import '../data/envios_repository.dart';
import '../data/pagos_repository.dart';
import '../data/solicitudes_cambio_repository.dart';
import '../data/ventas_repository.dart';
import '../data/zonas_envio_repository.dart';
import '../models/carrito.dart';
import '../models/cotizacion_envio.dart';
import '../models/direccion_cliente.dart';
import '../models/envio.dart';
import '../models/linea_con_exhibicion.dart';
import '../models/plazo_cambio.dart';
import '../models/reembolso.dart';
import '../models/solicitud_cambio.dart';
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

/// El nombre de la sucursal de una compra (null si no se pudo saber: la pantalla simplemente no lo dice).
final nombreSucursalProvider = FutureProvider.autoDispose.family<String?, int>((ref, sucursalId) async {
  try {
    final sucursales = await ref.watch(sucursalesRefProvider.future);
    for (final s in sucursales) {
      if (s.id == sucursalId) return s.nombre;
    }
    return null;
  } catch (_) {
    return null;
  }
});

/// Hasta cuándo se puede cambiar una compra (null si no se pudo saber: la pantalla simplemente no dice nada).
final plazoCambioProvider = FutureProvider.autoDispose.family<PlazoCambio?, int>((ref, ventaId) async {
  try {
    return await ref.watch(ventasRepositoryProvider).plazoCambio(ventaId);
  } catch (_) {
    return null;
  }
});

/// El dinero que se le devolvió al cliente por una compra (vacío si nada). Si no se pudo consultar (sin conexión, error
/// del servidor) queda vacío: la sección simplemente no aparece y el resto del comprobante se ve igual.
final reembolsosDeCompraProvider = FutureProvider.autoDispose.family<List<Reembolso>, int>((ref, ventaId) async {
  try {
    return await ref.watch(ventasRepositoryProvider).reembolsos(ventaId);
  } catch (_) {
    return const <Reembolso>[];
  }
});

final solicitudesCambioRepositoryProvider = Provider<SolicitudesCambioRepository>(
  (ref) => SolicitudesCambioRepository(ref.watch(apiClientProvider)),
);

/// Las solicitudes de cambio que el cliente pidió de una compra, la más reciente primero. Si falla, el error llega a
/// la sección, que lo dice sin tapar el resto del comprobante.
final misSolicitudesCambioProvider = FutureProvider.autoDispose.family<List<SolicitudCambio>, int>(
  (ref, ventaId) => ref.watch(solicitudesCambioRepositoryProvider).misSolicitudes(ventaId: ventaId),
);

/// Las compras del cliente que tienen una solicitud de cambio pendiente (el aviso de "Mis compras"). Una sola consulta
/// para todas. Un fallo no molesta: queda vacío y la lista se ve igual.
final comprasConCambioPendienteProvider = FutureProvider.autoDispose<Set<int>>((ref) async {
  final autenticado = ref.watch(authControllerProvider.select((s) => s.estaAutenticado));
  if (!autenticado) return const <int>{};
  try {
    final solicitudes = await ref.watch(solicitudesCambioRepositoryProvider).misSolicitudes();
    return {
      for (final s in solicitudes)
        if (s.estaPendiente) s.ventaId,
    };
  } catch (_) {
    return const <int>{};
  }
});

/// Por línea de la compra (id del detalle): las otras tallas o colores del MISMO producto y del mismo precio que
/// hay en la sucursal de la compra. Sale del catálogo público de la tienda (con `sucursal_id` cada variante trae
/// su stock).
final opcionesCambioProvider = FutureProvider.autoDispose.family<Map<int, List<OpcionCambio>>, int>((
  ref,
  ventaId,
) async {
  final venta = await ref.watch(compraDetalleProvider(ventaId).future);
  final propias = await lookupVariantes(ref, venta.detalle.map((l) => l.varianteId).toList());
  final catalogo = ref.read(catalogoRepositoryProvider);
  final productoIds = {for (final p in propias.values) p.productoId};
  // Sin sucursal no se sabe el stock: no se ofrece ninguna talla (el servidor igual exige stock al aprobar).
  final sucursalId = venta.sucursalId;
  if (sucursalId == null) return const {};
  final detalles = await Future.wait(productoIds.map((id) => catalogo.detalleEnSucursal(id, sucursalId)));
  final porProducto = {for (final d in detalles) d.id: d};
  final nombres = await lookupVariantes(ref, [
    for (final d in detalles)
      for (final v in d.variantes) v.id,
  ]);

  final resultado = <int, List<OpcionCambio>>{};
  // Una línea que ya se devolvió por completo no se ofrece.
  for (final linea in venta.lineasCambiables) {
    final producto = porProducto[propias[linea.varianteId]?.productoId];
    if (producto == null) continue;
    final original = producto.variantes.where((v) => v.id == linea.varianteId).firstOrNull;
    if (original == null) continue;
    // El servidor exige el mismo producto y el mismo precio; solo se ofrece lo que tiene stock en la sucursal.
    bool sirve(VarianteCatalogo v) =>
        v.id != original.id &&
        (v.precioEfectivo - original.precioEfectivo).abs() < 0.005 &&
        (v.cantidadDisponible ?? 0) > 0;
    resultado[linea.id] = [
      for (final v in producto.variantes.where(sirve))
        OpcionCambio(
          varianteId: v.id,
          etiqueta: _etiquetaDeVariante(nombres[v.id], v.sku),
          disponible: v.cantidadDisponible!,
        ),
    ];
  }
  return resultado;
});

/// "L · Azul"; si el catálogo no devolvió talla ni color, el SKU.
String _etiquetaDeVariante(VarianteLookupItem? item, String sku) {
  final partes = [
    if (item?.tallaCodigo != null) item!.tallaCodigo!,
    if (item?.colorNombre != null) item!.colorNombre!,
  ];
  return partes.isEmpty ? sku : partes.join(' · ');
}

/// Después de pedir o cancelar una solicitud de cambio: la lista de la compra, el aviso de "Mis compras" y el stock de
/// las tallas que se ofrecen.
void refrescarDespuesDeSolicitudCambio(WidgetRef ref, int ventaId) {
  ref.invalidate(misSolicitudesCambioProvider(ventaId));
  ref.invalidate(opcionesCambioProvider(ventaId));
  ref.invalidate(comprasConCambioPendienteProvider);
}

/// Después de pagar, cancelar o reintentar una compra cambian el stock, el
/// carrito (cancelar devuelve las prendas) y el estado de la compra.
void refrescarDespuesDeCompra(WidgetRef ref) {
  ref.invalidate(disponibilidadPorVarianteProvider);
  ref.invalidate(disponibleTotalProvider);
  ref.invalidate(sucursalesConStockCarritoProvider);
  ref.invalidate(compraDetalleProvider);
  ref.invalidate(envioDeCompraProvider);
  ref.invalidate(plazoCambioProvider);
  ref.invalidate(misSolicitudesCambioProvider);
  ref.invalidate(reembolsosDeCompraProvider);
  ref.invalidate(opcionesCambioProvider);
  ref.invalidate(comprasConCambioPendienteProvider);
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

/// Completa cada línea (del carrito o de un comprobante) con nombre/foto/talla/color, buscándolos en lote por
/// variante. Una variante que el catálogo ya no devuelve deja la línea sin esos datos.
Future<List<L>> aplicarExhibicion<L extends LineaConExhibicion<L>>(Ref ref, List<L> detalle) async {
  if (detalle.isEmpty) return detalle;
  final porVariante = await lookupVariantes(ref, detalle.map((l) => l.varianteId).toList());
  return detalle.map((linea) {
    final item = porVariante[linea.varianteId];
    return linea.conExhibicion(
      productoNombre: item?.productoNombre,
      imagenPrincipal: item?.imagenPrincipal,
      tallaCodigo: item?.tallaCodigo,
      colorNombre: item?.colorNombre,
    );
  }).toList();
}

final compraDetalleProvider = FutureProvider.autoDispose.family<Venta, int>((ref, ventaId) async {
  final venta = await ref.watch(ventasRepositoryProvider).comprobante(ventaId);
  if (venta.detalle.isEmpty) return venta;
  return venta.conDetalle(await aplicarExhibicion(ref, venta.detalle));
});
