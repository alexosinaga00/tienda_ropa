import 'dart:math';

/// Cuánto esperar antes del próximo reintento: 5 s, 10 s, 20 s... hasta un tope de 5 min, con una variación aleatoria
/// (jitter) para que muchos teléfonos no vuelvan a la vez. Es una función pura: el azar se inyecta para probarla.
///
/// [intentos] es la cantidad de intentos ya hechos (el primero fallido es 1). Nunca devuelve más que [tope].
Duration calcularEspera(
  int intentos, {
  Duration base = const Duration(seconds: 5),
  double factor = 2,
  Duration tope = const Duration(minutes: 5),
  double jitter = 0.2,
  Random? azar,
}) {
  final n = intentos < 1 ? 1 : intentos;
  // `min` antes de multiplicar evita desbordar con muchos intentos.
  final exponente = (n - 1) > 30 ? 30 : (n - 1);
  final crudo = base.inMilliseconds * pow(factor, exponente);
  final sinVariacion = min(crudo, tope.inMilliseconds.toDouble());
  final variacion = jitter <= 0 ? 0.0 : (((azar ?? Random()).nextDouble() * 2) - 1) * jitter;
  final conJitter = sinVariacion * (1 + variacion);
  return Duration(milliseconds: min(conJitter, tope.inMilliseconds.toDouble()).round());
}
