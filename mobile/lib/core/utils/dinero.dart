// El dinero se guarda como ENTERO en centavos: con `double`, 0.1 + 0.2 no da 0.3 y los totales se desvían. El contrato con
// el servidor lleva los montos como texto decimal ("75.00"); aquí se convierte en el límite y la pantalla vuelve a formatear.

final _decimalPositivo = RegExp(r'^(\d+)(?:\.(\d+))?$');

/// Convierte un monto ("75.00", "75", 75, 75.5) a centavos, redondeando hacia arriba desde la mitad (10.005 → 1001).
/// Rechaza lo negativo, lo vacío y lo que no es un número con [FormatException].
int aCentavos(Object monto) {
  final texto = switch (monto) {
    final String s => s.trim(),
    final int n => n.toString(),
    // `toString` de un double da el decimal más corto que lo identifica (10.005, no 10.00499999...).
    final double d => d.toString(),
    _ => throw FormatException('Monto no válido: $monto'),
  };
  final coincidencia = _decimalPositivo.firstMatch(texto);
  if (coincidencia == null) throw FormatException('Monto no válido: $monto');

  final enteros = BigInt.parse(coincidencia.group(1)!);
  final decimales = coincidencia.group(2) ?? '';
  final centavosDecimales = int.parse(decimales.padRight(2, '0').substring(0, 2));
  var centavos = enteros * BigInt.from(100) + BigInt.from(centavosDecimales);
  if (decimales.length > 2 && decimales.codeUnitAt(2) >= 0x35) centavos += BigInt.one; // '5' o más: sube
  return centavos.toInt();
}

/// 7500 → "75.00" (el formato que viaja en el JSON).
String deCentavos(int centavos) {
  if (centavos < 0) throw RangeError.value(centavos, 'centavos', 'No puede ser negativo');
  final enteros = centavos ~/ 100;
  final resto = (centavos % 100).toString().padLeft(2, '0');
  return '$enteros.$resto';
}

/// 7500 → "Bs 75.00" (para mostrar).
String formatearBs(int centavos) => 'Bs ${deCentavos(centavos)}';
