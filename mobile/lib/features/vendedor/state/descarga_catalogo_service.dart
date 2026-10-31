import 'package:flutter/foundation.dart';

import '../../../core/network/error_app.dart';
import '../../../core/utils/fecha_servidor.dart';
import '../../../core/utils/reloj.dart';
import '../data/almacen_paquete.dart';
import '../data/descarga_repository.dart';
import '../data/paquete_api.dart';
import '../models/paquete_sincronizacion.dart';

const mensajeYaActualizando = 'Ya se está actualizando.';
const mensajeSinDatosDescargados = 'No se pudo actualizar y todavía no hay datos descargados.';
const mensajeNoSePudoGuardar = 'No se pudo guardar la descarga. Intenta de nuevo.';
const mensajeOperacionesEnviadas = 'Hay ventas o reservas enviándose al servidor. Se actualizará cuando terminen.';

/// El resultado de intentar actualizar los datos del dispositivo.
sealed class ResultadoDescarga {
  const ResultadoDescarga();

  const factory ResultadoDescarga.exitosa({
    required bool completa,
    required int productos,
    required int milisegundos,
    required int sucursalId,
  }) = DescargaExitosa;
  const factory ResultadoDescarga.pospuesta(String motivo) = DescargaPospuesta;
  const factory ResultadoDescarga.fallida({
    required String mensaje,
    required bool hayDatosAnteriores,
    UltimaDescarga? ultimaDescarga,
  }) = DescargaFallida;
}

class DescargaExitosa extends ResultadoDescarga {
  const DescargaExitosa({
    required this.completa,
    required this.productos,
    required this.milisegundos,
    required this.sucursalId,
  });

  final bool completa;
  final int productos;
  final int milisegundos;

  /// La sucursal cuyos datos se bajaron (la elegida por el servicio si no se pidió una).
  final int sucursalId;
}

/// No se intentó: otra descarga en curso, u operaciones enviadas que aún no tienen respuesta.
class DescargaPospuesta extends ResultadoDescarga {
  const DescargaPospuesta(this.motivo);

  final String motivo;
}

class DescargaFallida extends ResultadoDescarga {
  const DescargaFallida({required this.mensaje, required this.hayDatosAnteriores, this.ultimaDescarga});

  final String mensaje;

  /// Los datos que ya había siguen intactos y se pueden seguir usando.
  final bool hayDatosAnteriores;
  final UltimaDescarga? ultimaDescarga;
}

/// Baja el paquete del servidor (manifiesto, catálogo, stock de UNA sucursal y clientes) y lo guarda de una vez.
///
/// - Nunca hay dos descargas a la vez en este servicio.
/// - Se pospone mientras haya operaciones 'enviadas': su efecto en el stock del servidor es incierto.
/// - El catálogo siempre se baja completo; el stock es incremental (`desde` = `generado_en` de la última descarga de ESA
///   sucursal) salvo la primera vez, si se fuerza, o si cambió el contrato o el esquema local.
/// - Si algo falla, los datos anteriores quedan intactos (la escritura es una sola transacción).
class DescargaCatalogoService {
  DescargaCatalogoService(this._api, this._almacen, this._repositorio, this._reloj);

  final PaqueteApi _api;
  final AlmacenPaquete _almacen;
  final DescargaRepository _repositorio;
  final Reloj _reloj;

  bool _enCurso = false;

  bool get descargando => _enCurso;

  /// [sucursalId] null = la primera vez, cuando el teléfono todavía no conoce las sucursales del usuario: se elige la
  /// primera que no sea depósito del manifiesto y el resultado dice cuál fue.
  Future<ResultadoDescarga> descargar({
    int? sucursalId,
    required int usuarioId,
    bool forzarCompleta = false,
  }) async {
    if (_enCurso) {
      _registrar('descarga_catalogo omitida sucursal=$sucursalId motivo=ya_en_curso');
      return const ResultadoDescarga.pospuesta(mensajeYaActualizando);
    }
    _enCurso = true;
    final cronometro = Stopwatch()..start();
    try {
      return await _descargar(sucursalId, usuarioId, forzarCompleta, cronometro);
    } finally {
      _enCurso = false;
    }
  }

  Future<ResultadoDescarga> _descargar(int? pedida, int usuarioId, bool forzarCompleta, Stopwatch cronometro) async {
    int? empresaId;
    var sucursalId = pedida ?? 0;
    try {
      // La empresa se conoce por la sucursal ya guardada; la primera vez no hay nada local que proteger.
      if (pedida != null) {
        empresaId = await _repositorio.empresaDeSucursal(pedida);
        if (empresaId != null && await _repositorio.hayOperacionesEnviadas(empresaId)) {
          _registrar('descarga_catalogo pospuesta sucursal=$pedida motivo=operaciones_enviadas');
          return const ResultadoDescarga.pospuesta(mensajeOperacionesEnviadas);
        }
      }

      final manifiesto = await _api.manifiesto();
      empresaId = manifiesto.empresa.id;
      // Sin sucursal pedida (primera descarga: el teléfono aún no conoce las suyas) se usa la primera que no sea depósito.
      final elegida =
          pedida ??
          manifiesto.sucursales.where((s) => !s.esDeposito).map((s) => s.id).firstOrNull ??
          manifiesto.sucursales.map((s) => s.id).firstOrNull;
      if (elegida == null || !manifiesto.sucursales.any((s) => s.id == elegida)) {
        throw const ErrorApp(tipo: TipoErrorApp.prohibido, mensaje: 'Esa sucursal no está autorizada para tu cuenta.');
      }
      sucursalId = elegida;

      final ultima = await _repositorio.ultimaDescarga(empresaId, sucursalId);
      final formato = await _repositorio.formatoDescarga(empresaId, sucursalId);
      final completa = forzarCompleta || ultima == null || formato != formatoDescargaActual;
      _registrar('descarga_catalogo inicio sucursal=$sucursalId tipo=${completa ? 'completa' : 'incremental'}');

      final catalogo = await _api.descargarCatalogo();
      final stock = await _api.descargarStock(sucursalId: sucursalId, desde: completa ? null : ultima.generadoEn);
      final clientes = completa ? await _api.descargarClientes() : null;

      // Una operación pudo pasar a 'enviada' mientras se descargaba: el stock bajado ya no sería fiable.
      if (await _repositorio.hayOperacionesEnviadas(empresaId)) {
        _registrar('descarga_catalogo pospuesta sucursal=$sucursalId motivo=operaciones_enviadas_durante');
        return const ResultadoDescarga.pospuesta(mensajeOperacionesEnviadas);
      }

      await _almacen.aplicar(
        PaqueteDescargado(
          manifiesto: manifiesto,
          productos: catalogo.productos,
          generadoEnCatalogo: catalogo.generadoEn,
          stock: stock.items,
          sucursalId: sucursalId,
          completoStock: completa,
          generadoEnStock: stock.generadoEn,
          clientes: clientes?.clientes,
        ),
        usuarioId: usuarioId,
      );

      final milisegundos = cronometro.elapsedMilliseconds;
      final variantes = catalogo.productos.fold<int>(0, (suma, p) => suma + p.variantes.length);
      _registrar(
        'descarga_catalogo fin sucursal=$sucursalId tipo=${completa ? 'completa' : 'incremental'} '
        'productos=${catalogo.productos.length} variantes=$variantes stock=${stock.items.length} '
        'clientes=${clientes?.clientes.length ?? 0} ms=$milisegundos resultado=ok',
      );
      return ResultadoDescarga.exitosa(
        completa: completa,
        productos: catalogo.productos.length,
        milisegundos: milisegundos,
        sucursalId: sucursalId,
      );
    } catch (error) {
      return _fallida(error, empresaId, sucursalId, cronometro);
    }
  }

  Future<ResultadoDescarga> _fallida(Object error, int? empresaId, int sucursalId, Stopwatch cronometro) async {
    UltimaDescarga? ultima;
    try {
      empresaId ??= await _repositorio.empresaDeSucursal(sucursalId);
      if (empresaId != null) ultima = await _repositorio.ultimaDescarga(empresaId, sucursalId);
    } catch (_) {
      // Si ni siquiera se puede leer la base, se informa sin datos anteriores.
    }

    final String mensaje;
    final String etiqueta;
    if (error is ErrorApp) {
      etiqueta = error.tipo.name;
      // Sin conexión o servidor caído: lo importante es que lo anterior sigue ahí.
      if (error.tipo == TipoErrorApp.sinConexion || error.tipo == TipoErrorApp.servidor) {
        mensaje = ultima == null
            ? mensajeSinDatosDescargados
            : 'No se pudo actualizar; sigues viendo los datos del ${formatearFechaHora(ultima.descargadoEn.toLocal())}';
      } else {
        mensaje = error.mensaje;
      }
    } else {
      etiqueta = 'error_local';
      mensaje = mensajeNoSePudoGuardar;
    }

    // Solo el tipo de error: nunca el mensaje crudo ni datos de la respuesta.
    _registrar(
      'descarga_catalogo fin sucursal=$sucursalId ms=${cronometro.elapsedMilliseconds} resultado=fallida error=$etiqueta '
      'datos_anteriores=${ultima != null}',
    );
    return ResultadoDescarga.fallida(mensaje: mensaje, hayDatosAnteriores: ultima != null, ultimaDescarga: ultima);
  }

  void _registrar(String linea) => debugPrint('[${aIsoUtc(_reloj.ahora())}] $linea');
}
