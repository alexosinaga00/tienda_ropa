const _conTilde = 'áàäâãéèëêíìïîóòöôõúùüûñç';
const _sinTilde = 'aaaaaeeeeiiiiooooouuuunc';

/// Minúsculas, sin tildes ni diéresis ("Ñandú" → "nandu") y con los espacios colapsados. Es la forma en que se guarda
/// `producto.nombre_busqueda` y en que se normaliza lo que escribe la persona, para que "camisa", "Camisa" y "CAMISÁ"
/// encuentren lo mismo.
String normalizarBusqueda(String texto) {
  final minusculas = texto.toLowerCase().trim();
  final salida = StringBuffer();
  for (final rune in minusculas.runes) {
    final caracter = String.fromCharCode(rune);
    final i = _conTilde.indexOf(caracter);
    salida.write(i >= 0 ? _sinTilde[i] : caracter);
  }
  return salida.toString().replaceAll(RegExp(r'\s+'), ' ');
}
