// Fechas y horas que llegan del servidor.
//
// REGLA: un instante del servidor se lee SIEMPRE como UTC y se muestra o se compara en hora local.
// - Con zona ("2026-11-07T03:12:00Z" o "...-04:00") ya es un instante exacto.
// - Sin zona ("2026-11-07T03:12:00", como mandaba el servidor antes) se toma como UTC: Dart lo tomaría como hora
//   local y quedaría corrido (en Bolivia, 4 horas).
// Las fechas de negocio sin hora (`fecha_visita`) y las horas de reloj de pared (horarios) NO pasan por aquí.

/// Si el texto ISO trae zona horaria después de la hora ("Z", "+01:00", "-0400").
bool _traeZona(String texto) {
  final separador = RegExp('[T ]').firstMatch(texto);
  if (separador == null) return false;
  final resto = texto.substring(separador.end);
  return resto.endsWith('Z') || resto.endsWith('z') || RegExp(r'[+-]\d{2}(:?\d{2})?$').hasMatch(resto);
}

/// Un instante del servidor como UTC (`isUtc` verdadero). Lanza [FormatException] si el texto no es una fecha.
/// Para mostrarlo o compararlo por día, pásalo por `.toLocal()` (o usa [fechaDelServidor]).
DateTime instanteUtcDelServidor(String valor) {
  final texto = valor.trim();
  if (!texto.contains(RegExp('[T ]'))) {
    final dia = DateTime.parse(texto);
    return DateTime.utc(dia.year, dia.month, dia.day);
  }
  return DateTime.parse(_traeZona(texto) ? texto : '${texto}Z').toUtc();
}

/// Lo mismo, tolerante: `null` si el valor falta, no es texto o no se entiende. Para lectores que no deben romper.
DateTime? leerInstanteUtc(Object? valor) {
  if (valor is! String || valor.trim().isEmpty) return null;
  try {
    return instanteUtcDelServidor(valor);
  } on FormatException {
    return null;
  }
}

/// Un instante del servidor ya en hora local, listo para mostrar o para comparar por día.
DateTime fechaDelServidor(String valor) => instanteUtcDelServidor(valor).toLocal();

/// "dd/MM/yyyy HH:mm" de una fecha. Si viene en UTC la pasa a hora local primero; una ya local no cambia.
String formatearFechaHora(DateTime f) {
  final local = f.toLocal();
  String dos(int n) => n.toString().padLeft(2, '0');
  return '${dos(local.day)}/${dos(local.month)}/${local.year} ${dos(local.hour)}:${dos(local.minute)}';
}
