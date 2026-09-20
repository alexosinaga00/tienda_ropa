/// El backend guarda las fechas en UTC y las manda sin zona ("2026-09-20T16:52:29"): sin la 'Z', Dart las tomaría como
/// hora local y quedarían corridas (en Bolivia, 4 horas). Devuelve la fecha ya en hora local.
DateTime fechaDelServidor(String valor) {
  final tieneZona = valor.endsWith('Z') || RegExp(r'[+-]\d{2}:?\d{2}$').hasMatch(valor);
  return DateTime.parse(tieneZona ? valor : '${valor}Z').toLocal();
}
