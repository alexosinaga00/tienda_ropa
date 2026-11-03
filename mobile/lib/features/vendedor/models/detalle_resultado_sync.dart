import 'dart:convert';

/// El precio con que se cobró una prenda y el vigente en el servidor (D17: se respeta el que cobró la persona).
class AvisoPrecio {
  const AvisoPrecio({required this.varianteId, this.precioOperacionCentavos, this.precioActualCentavos});

  final int varianteId;
  final int? precioOperacionCentavos;
  final int? precioActualCentavos;
}

/// Lo que faltó de una prenda cuando el servidor intentó aplicar la operación.
class FaltanteStock {
  const FaltanteStock({required this.varianteId, required this.solicitado, required this.disponible});

  final int varianteId;
  final int solicitado;
  final int disponible;
}

/// Lo que la cola guarda en `resultado_sync.detalle_json` (montos en CENTAVOS), leído con tolerancia: un JSON dañado, de otra
/// forma o con campos que no son del tipo esperado nunca rompe la pantalla; solo deja esos datos vacíos.
class DetalleResultadoSync {
  const DetalleResultadoSync({
    this.recursoTipo,
    this.recursoId,
    this.recursoCodigo,
    this.recursoTotalCentavos,
    this.cambioCentavos,
    this.duplicada = false,
    this.avisos = const [],
    this.faltantes = const [],
    this.resolucionAccion,
    this.resolucionMotivo,
  });

  static const vacio = DetalleResultadoSync();

  /// `venta` o `reserva`: lo que el servidor creó.
  final String? recursoTipo;
  final int? recursoId;

  /// El código legible del recurso creado (p. ej. `V-000123`).
  final String? recursoCodigo;
  final int? recursoTotalCentavos;
  final int? cambioCentavos;
  final bool duplicada;
  final List<AvisoPrecio> avisos;
  final List<FaltanteStock> faltantes;

  /// Lo que decidió un encargado (`forzar` o `rechazar`) y por qué.
  final String? resolucionAccion;
  final String? resolucionMotivo;

  factory DetalleResultadoSync.desde(String? json) {
    if (json == null || json.trim().isEmpty) return vacio;
    final Object? crudo;
    try {
      crudo = jsonDecode(json);
    } catch (_) {
      return vacio;
    }
    if (crudo is! Map) return vacio;

    final recurso = crudo['recurso'];
    final resolucion = crudo['resolucion'];
    return DetalleResultadoSync(
      recursoTipo: recurso is Map ? _texto(recurso['tipo']) : null,
      recursoId: recurso is Map ? _entero(recurso['id']) : null,
      recursoCodigo: recurso is Map ? _texto(recurso['codigo']) : null,
      recursoTotalCentavos: recurso is Map ? _entero(recurso['total_centavos']) : null,
      cambioCentavos: _entero(crudo['cambio_centavos']),
      duplicada: crudo['duplicada'] == true,
      avisos: [
        if (crudo['avisos'] is List)
          for (final a in crudo['avisos'] as List)
            if (a is Map && _entero(a['variante_id']) != null)
              AvisoPrecio(
                varianteId: _entero(a['variante_id'])!,
                precioOperacionCentavos: _entero(a['precio_operacion_centavos']),
                precioActualCentavos: _entero(a['precio_actual_centavos']),
              ),
      ],
      faltantes: [
        if (crudo['faltantes'] is List)
          for (final f in crudo['faltantes'] as List)
            if (f is Map && _entero(f['variante_id']) != null)
              FaltanteStock(
                varianteId: _entero(f['variante_id'])!,
                solicitado: _entero(f['solicitado']) ?? 0,
                disponible: _entero(f['disponible']) ?? 0,
              ),
      ],
      resolucionAccion: resolucion is Map ? _texto(resolucion['accion']) : null,
      resolucionMotivo: resolucion is Map ? _texto(resolucion['motivo']) : null,
    );
  }

  static int? _entero(Object? valor) => valor is num ? valor.toInt() : null;

  static String? _texto(Object? valor) {
    if (valor is! String) return null;
    final t = valor.trim();
    return t.isEmpty ? null : t;
  }
}
