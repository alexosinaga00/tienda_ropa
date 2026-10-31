import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Cuántas operaciones registradas sin conexión siguen sin enviarse. Los avisos de "cerrar sesión" y "cambiar de tienda"
/// lo consultan para advertir que esas operaciones no se pierden pero hay que entrar de nuevo para enviarlas.
///
/// Hoy no existe la cola de operaciones (llega en E19 y E20): la implementación por defecto devuelve 0 y es la que se
/// reemplaza entonces con `contadorPendientesProvider.overrideWith(...)`.
abstract interface class ContadorPendientes {
  Future<int> pendientesDe({int? empresaId, int? usuarioId});
}

class ContadorPendientesVacio implements ContadorPendientes {
  const ContadorPendientesVacio();

  @override
  Future<int> pendientesDe({int? empresaId, int? usuarioId}) async => 0;
}

final contadorPendientesProvider = Provider<ContadorPendientes>((ref) => const ContadorPendientesVacio());
