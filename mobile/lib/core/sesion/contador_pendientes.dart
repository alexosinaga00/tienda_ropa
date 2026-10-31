import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../features/vendedor/data/contador_pendientes_sqlite.dart';
import '../../features/vendedor/state/catalogo_local_providers.dart';

/// Cuántas operaciones registradas sin conexión siguen sin enviarse. Los avisos de "cerrar sesión" y "cambiar de tienda"
/// lo consultan para advertir que esas operaciones no se pierden pero hay que entrar de nuevo para enviarlas.
///
/// La implementación real cuenta en la base local ([ContadorPendientesSqlite]); [ContadorPendientesVacio] queda para
/// quien necesite un contador que siempre responde 0. Las pruebas lo reemplazan con `contadorPendientesProvider.overrideWith(...)`.
abstract interface class ContadorPendientes {
  Future<int> pendientesDe({int? empresaId, int? usuarioId});
}

class ContadorPendientesVacio implements ContadorPendientes {
  const ContadorPendientesVacio();

  @override
  Future<int> pendientesDe({int? empresaId, int? usuarioId}) async => 0;
}

final contadorPendientesProvider = Provider<ContadorPendientes>(
  (ref) => ContadorPendientesSqlite(() => ref.read(baseLocalProvider.future)),
);
