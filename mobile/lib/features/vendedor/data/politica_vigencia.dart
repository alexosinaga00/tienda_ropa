/// Qué tan viejos son los datos descargados. Solo INFORMA: nunca impide consultar ni vender.
enum EstadoVigencia {
  /// Se descargó hace menos del umbral de aviso.
  fresca,

  /// Pasó el umbral de aviso ("puede estar desactualizada").
  antigua,

  /// Pasó el umbral crítico ("muy desactualizada").
  critica,

  /// Esta sucursal nunca se descargó en este teléfono.
  nunca,
}

/// Los umbrales viven en UN solo lugar. El de aviso lo manda el servidor (`aviso_desactualizado_horas`, configurable por
/// empresa); si todavía no se descargó nada se usa [avisoPorDefecto].
class PoliticaVigencia {
  const PoliticaVigencia({this.umbralAviso = avisoPorDefecto, this.umbralCritico = criticoPorDefecto});

  /// Con las horas de aviso que mandó el servidor (null = las de por defecto). El umbral crítico nunca es menor que
  /// el de aviso más una hora.
  factory PoliticaVigencia.conAvisoHoras(int? horas) {
    final aviso = (horas != null && horas > 0) ? Duration(hours: horas) : avisoPorDefecto;
    final minimoCritico = aviso + const Duration(hours: 1);
    return PoliticaVigencia(
      umbralAviso: aviso,
      umbralCritico: criticoPorDefecto > minimoCritico ? criticoPorDefecto : minimoCritico,
    );
  }

  static const avisoPorDefecto = Duration(hours: 2);
  static const criticoPorDefecto = Duration(hours: 24);

  final Duration umbralAviso;
  final Duration umbralCritico;

  /// [descargadoEn] es la hora del teléfono en que terminó la última descarga (null = nunca).
  EstadoVigencia estadoDe(DateTime? descargadoEn, DateTime ahora) {
    if (descargadoEn == null) return EstadoVigencia.nunca;
    final edad = ahora.difference(descargadoEn);
    if (edad >= umbralCritico) return EstadoVigencia.critica;
    if (edad >= umbralAviso) return EstadoVigencia.antigua;
    return EstadoVigencia.fresca;
  }

  /// El aviso se muestra si los datos no están frescos O si no hay conexión (aunque estén frescos).
  bool debeAvisar(EstadoVigencia estado, {required bool enLinea}) => estado != EstadoVigencia.fresca || !enLinea;
}

/// Lo que la pantalla necesita para dibujar el aviso.
class ResumenVigencia {
  const ResumenVigencia({required this.estado, this.descargadoEn, this.edad});

  final EstadoVigencia estado;
  final DateTime? descargadoEn;
  final Duration? edad;
}
