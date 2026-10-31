/// Una organización (tienda) de la plataforma, tal como la publica el backend: solo lo que puede ver cualquiera.
class Tienda {
  const Tienda({required this.codigo, required this.nombre, this.logoUrl, this.colorAcento, this.disponible = true});

  factory Tienda.fromJson(Map<String, dynamic> json) {
    return Tienda(
      codigo: json['codigo'] as String,
      nombre: json['nombre'] as String,
      logoUrl: json['logo_url'] as String?,
      colorAcento: json['color_acento'] as String?,
      // Solo viene en el detalle (`GET /public/{codigo}/tienda`); la lista muestra únicamente las disponibles.
      disponible: json['disponible'] as bool? ?? true,
    );
  }

  /// Identifica a la tienda en las rutas (`/public/{codigo}/...`). No cambia aunque cambie el nombre comercial.
  final String codigo;
  final String nombre;
  final String? logoUrl;

  /// `#RRGGBB`, o null si la tienda no definió uno.
  final String? colorAcento;

  /// Falso cuando la suscripción de la empresa no está activa.
  final bool disponible;

  /// Las siglas para el monograma cuando no hay logo: la inicial de hasta dos palabras ("Chaski Sport" → "CS").
  String get siglas {
    final palabras = nombre.trim().split(RegExp(r'\s+')).where((p) => p.isNotEmpty).toList();
    if (palabras.isEmpty) return '?';
    if (palabras.length == 1) return palabras.first.substring(0, palabras.first.length >= 2 ? 2 : 1).toUpperCase();
    return '${palabras[0][0]}${palabras[1][0]}'.toUpperCase();
  }

  Map<String, dynamic> toJson() => {
    'codigo': codigo,
    'nombre': nombre,
    'logo_url': logoUrl,
    'color_acento': colorAcento,
    'disponible': disponible,
  };

  @override
  bool operator ==(Object other) =>
      other is Tienda &&
      other.codigo == codigo &&
      other.nombre == nombre &&
      other.logoUrl == logoUrl &&
      other.colorAcento == colorAcento &&
      other.disponible == disponible;

  @override
  int get hashCode => Object.hash(codigo, nombre, logoUrl, colorAcento, disponible);
}
