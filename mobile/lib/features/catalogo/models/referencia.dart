class CategoriaRef {
  const CategoriaRef({required this.id, required this.nombre, this.categoriaPadreId});

  factory CategoriaRef.fromJson(Map<String, dynamic> json) => CategoriaRef(
    id: json['id'] as int,
    nombre: json['nombre'] as String,
    categoriaPadreId: json['categoria_padre_id'] as int?,
  );

  final int id;
  final String nombre;
  final int? categoriaPadreId;
}

class TallaRef {
  const TallaRef({required this.id, required this.codigo, required this.orden});

  factory TallaRef.fromJson(Map<String, dynamic> json) =>
      TallaRef(id: json['id'] as int, codigo: json['codigo'] as String, orden: json['orden'] as int);

  final int id;
  final String codigo;
  final int orden;
}

class ColorRef {
  const ColorRef({required this.id, required this.nombre, this.codigoHex});

  factory ColorRef.fromJson(Map<String, dynamic> json) =>
      ColorRef(id: json['id'] as int, nombre: json['nombre'] as String, codigoHex: json['codigo_hex'] as String?);

  final int id;
  final String nombre;
  final String? codigoHex;
}

class MaterialRef {
  const MaterialRef({required this.id, required this.nombre});

  factory MaterialRef.fromJson(Map<String, dynamic> json) =>
      MaterialRef(id: json['id'] as int, nombre: json['nombre'] as String);

  final int id;
  final String nombre;
}

class TemporadaRef {
  const TemporadaRef({required this.id, required this.nombre, required this.anio});

  factory TemporadaRef.fromJson(Map<String, dynamic> json) =>
      TemporadaRef(id: json['id'] as int, nombre: json['nombre'] as String, anio: json['anio'] as int);

  final int id;
  final String nombre;
  final int anio;
}

class SucursalRef {
  const SucursalRef({required this.id, required this.codigo, required this.nombre, this.esDeposito = false});

  factory SucursalRef.fromJson(Map<String, dynamic> json) => SucursalRef(
    id: json['id'] as int,
    codigo: json['codigo'] as String,
    nombre: json['nombre'] as String,
    esDeposito: json['es_deposito'] as bool? ?? false,
  );

  final int id;
  final String codigo;
  final String nombre;
  // Un depósito es solo almacén: despacha envíos pero no recibe clientes
  // para retiro ni reservas.
  final bool esDeposito;
}
