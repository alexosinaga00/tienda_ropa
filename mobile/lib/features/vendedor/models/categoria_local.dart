/// Una categoría de la copia local; [padreId] es `null` en las categorías de primer nivel.
class CategoriaLocal {
  const CategoriaLocal({required this.id, required this.nombre, this.padreId});

  final int id;
  final String nombre;
  final int? padreId;

  @override
  String toString() => 'CategoriaLocal($id, $nombre)';
}
