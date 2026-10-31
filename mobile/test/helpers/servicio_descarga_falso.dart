import 'dart:async';

import 'package:mobile/features/vendedor/state/descarga_catalogo_service.dart';

/// Un [DescargaCatalogoService] que no toca la red: registra los pedidos, puede esperar una [puerta], hacer algo en la base
/// ([alDescargar]) y devolver el [resultado] que se quiera.
class ServicioDescargaFalso implements DescargaCatalogoService {
  ServicioDescargaFalso({this.resultado, this.alDescargar});

  /// null = una descarga exitosa de la sucursal pedida (o de la 1).
  ResultadoDescarga? resultado;
  Future<void> Function()? alDescargar;
  Completer<void>? puerta;
  final List<({int? sucursalId, int usuarioId, bool forzarCompleta})> pedidos = [];
  bool _enCurso = false;

  int get llamadas => pedidos.length;

  @override
  bool get descargando => _enCurso;

  @override
  Future<ResultadoDescarga> descargar({int? sucursalId, required int usuarioId, bool forzarCompleta = false}) async {
    pedidos.add((sucursalId: sucursalId, usuarioId: usuarioId, forzarCompleta: forzarCompleta));
    _enCurso = true;
    try {
      await puerta?.future;
      await alDescargar?.call();
      return resultado ??
          ResultadoDescarga.exitosa(completa: true, productos: 0, milisegundos: 1, sucursalId: sucursalId ?? 1);
    } finally {
      _enCurso = false;
    }
  }
}
