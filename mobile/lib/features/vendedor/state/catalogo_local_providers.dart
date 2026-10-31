import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:sqflite/sqflite.dart';
import '../../../core/local/abrir_base_local.dart';
import '../../../core/network/providers.dart';
import '../../../core/utils/reloj.dart';
import '../../auth/state/auth_controller.dart';
import '../data/almacen_paquete.dart';
import '../data/catalogo_local_repository.dart';
import '../data/descarga_repository.dart';
import '../data/paquete_api.dart';
import '../data/politica_vigencia.dart';
import '../models/sucursal_local.dart';
import 'descarga_catalogo_service.dart';

/// La base local (SQLite) del teléfono. En las pruebas se reemplaza con `abrirBaseDePrueba()`.
final baseLocalProvider = FutureProvider<Database>((ref) async {
  final db = await abrirBaseLocal();
  ref.onDispose(db.close);
  return db;
});

/// La empresa y el usuario de la sesión: todo lo local se filtra por ellos.
final empresaLocalIdProvider = Provider<int?>((ref) => ref.watch(authControllerProvider.select((s) => s.usuario?.empresaId)));
final usuarioLocalIdProvider = Provider<int?>((ref) => ref.watch(authControllerProvider.select((s) => s.usuario?.id)));

/// El catálogo descargado de la empresa de la sesión; null sin sesión. Al cambiar de empresa se reconstruye y ve otra
/// partición de la misma base.
final catalogoLocalProvider = FutureProvider<CatalogoLocalRepository?>((ref) async {
  final empresaId = ref.watch(empresaLocalIdProvider);
  if (empresaId == null) return null;
  final db = await ref.watch(baseLocalProvider.future);
  return CatalogoLocalSqlite(db, empresaId: empresaId);
});

final descargaRepositoryProvider = FutureProvider<DescargaRepository>((ref) async {
  return DescargaRepositorySqlite(await ref.watch(baseLocalProvider.future));
});

/// UNA sola instancia mientras no cambie la tienda ni la base: guarda el candado de "una descarga a la vez".
final descargaServiceProvider = FutureProvider<DescargaCatalogoService>((ref) async {
  final db = await ref.watch(baseLocalProvider.future);
  final reloj = ref.watch(relojProvider);
  return DescargaCatalogoService(
    PaqueteApi(ref.watch(apiClientProvider)),
    AlmacenPaqueteSqlite(db, reloj),
    DescargaRepositorySqlite(db),
    reloj,
  );
});

/// Cada vez que termina una descarga se incrementa: las listas que dependen de lo descargado lo observan para recargarse.
final descargaTerminadaProvider = StateProvider<int>((ref) => 0);

/// Las sucursales que el usuario puede usar (las del último manifiesto).
final sucursalesAutorizadasProvider = FutureProvider<List<SucursalLocal>>((ref) async {
  ref.watch(descargaTerminadaProvider);
  final usuarioId = ref.watch(usuarioLocalIdProvider);
  final catalogo = await ref.watch(catalogoLocalProvider.future);
  if (catalogo == null || usuarioId == null) return const [];
  return catalogo.sucursalesAutorizadas(usuarioId);
});

/// La sucursal con la que trabaja la persona: la que eligió si sigue autorizada; si no, la primera que no sea depósito;
/// si no hay ninguna descargada todavía, null.
final sucursalActivaProvider = FutureProvider<int?>((ref) async {
  ref.watch(descargaTerminadaProvider);
  final empresaId = ref.watch(empresaLocalIdProvider);
  final usuarioId = ref.watch(usuarioLocalIdProvider);
  if (empresaId == null || usuarioId == null) return null;
  final autorizadas = await ref.watch(sucursalesAutorizadasProvider.future);
  if (autorizadas.isEmpty) return null;
  final repositorio = await ref.watch(descargaRepositoryProvider.future);
  final guardada = await repositorio.sucursalActiva(empresaId, usuarioId);
  if (guardada != null && autorizadas.any((s) => s.id == guardada)) return guardada;
  return (autorizadas.where((s) => !s.esDeposito).firstOrNull ?? autorizadas.first).id;
});

/// Guarda la sucursal elegida y hace que todo lo que depende de ella se recalcule.
Future<void> fijarSucursalActiva(WidgetRef ref, int sucursalId) async {
  final empresaId = ref.read(empresaLocalIdProvider);
  final usuarioId = ref.read(usuarioLocalIdProvider);
  if (empresaId == null || usuarioId == null) return;
  final repositorio = await ref.read(descargaRepositoryProvider.future);
  await repositorio.fijarSucursalActiva(empresaId, usuarioId, sucursalId);
  ref.invalidate(sucursalActivaProvider);
}

/// Qué tan viejos son los datos de la sucursal activa. `ahora` sale del [Reloj] (se fija en las pruebas).
final vigenciaProvider = FutureProvider<ResumenVigencia>((ref) async {
  ref.watch(descargaTerminadaProvider);
  final empresaId = ref.watch(empresaLocalIdProvider);
  final sucursalId = await ref.watch(sucursalActivaProvider.future);
  final reloj = ref.watch(relojProvider);
  if (empresaId == null || sucursalId == null) return const ResumenVigencia(estado: EstadoVigencia.nunca);
  final repositorio = await ref.watch(descargaRepositoryProvider.future);
  final ultima = await repositorio.ultimaDescarga(empresaId, sucursalId);
  final politica = PoliticaVigencia.conAvisoHoras(await repositorio.avisoHoras(empresaId));
  final ahora = reloj.ahora();
  return ResumenVigencia(
    estado: politica.estadoDe(ultima?.descargadoEn, ahora),
    descargadoEn: ultima?.descargadoEn,
    edad: ultima == null ? null : ahora.difference(ultima.descargadoEn),
  );
});
