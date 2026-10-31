import '../../../core/network/error_app.dart';
import '../../../core/utils/dinero.dart';

/// La versión MAYOR del contrato del paquete de descarga que esta app sabe leer. El servidor manda `version_contrato` como
/// texto ("1.0"): solo cuenta el número mayor. Si el servidor sube de versión, la app avisa en vez de leer mal.
const versionContratoSoportada = 1;

const mensajeActualizarApp = 'Actualiza la app para sincronizar.';
const mensajeRespuestaNoEntendida = 'La respuesta del servidor no se entendió.';

ErrorApp _respuestaNoEntendida() =>
    const ErrorApp(tipo: TipoErrorApp.desconocido, mensaje: mensajeRespuestaNoEntendida);

/// Lanza un [ErrorApp] si `version_contrato` (texto "1.0", "2" o número) es mayor que [versionContratoSoportada]. Si falta o
/// no se entiende, se acepta (lector tolerante).
void verificarVersionContrato(Object? version) {
  final mayor = switch (version) {
    final int n => n,
    final num n => n.toInt(),
    final String s => int.tryParse(s.trim().split('.').first),
    _ => null,
  };
  if (mayor != null && mayor > versionContratoSoportada) {
    throw const ErrorApp(tipo: TipoErrorApp.desconocido, mensaje: mensajeActualizarApp);
  }
}

/// Fecha ISO-8601 en UTC con formato estable: sin fracción si es cero ("2026-10-31T10:00:00Z"), así comparar textos funciona.
String aIsoUtc(DateTime fecha) {
  final texto = fecha.toUtc().toIso8601String();
  return texto.endsWith('.000Z') ? '${texto.substring(0, texto.length - 5)}Z' : texto;
}

/// Lee una fecha del servidor; sin zona (o con 'Z') la toma como UTC. `null` si falta o no se entiende.
DateTime? leerFechaUtc(Object? valor) {
  if (valor is! String || valor.trim().isEmpty) return null;
  var texto = valor.trim();
  final tieneZona = texto.endsWith('Z') || RegExp(r'[+-]\d{2}:?\d{2}$').hasMatch(texto);
  if (!tieneZona) texto = '${texto}Z';
  return DateTime.tryParse(texto)?.toUtc();
}

// ---- Lectores tolerantes ----

int? _entero(Object? v) => switch (v) {
  final int n => n,
  final num n => n.toInt(),
  final String s => int.tryParse(s.trim()) ?? double.tryParse(s.trim())?.toInt(),
  _ => null,
};

int _enteroObligatorio(Object? v) => _entero(v) ?? (throw _respuestaNoEntendida());

String? _texto(Object? v) {
  if (v == null) return null;
  final s = v.toString();
  return s.isEmpty ? null : s;
}

String _textoObligatorio(Object? v) => _texto(v) ?? (throw _respuestaNoEntendida());

bool _booleano(Object? v) => switch (v) {
  final bool b => b,
  final num n => n != 0,
  final String s => s.toLowerCase() == 'true' || s == '1',
  _ => false,
};

int _centavos(Object? v, {int? ausente}) {
  if (v == null || (v is String && v.trim().isEmpty)) return ausente ?? (throw _respuestaNoEntendida());
  try {
    return aCentavos(v);
  } on FormatException {
    throw _respuestaNoEntendida();
  }
}

List<T> _lista<T>(Object? v, T Function(Map<String, dynamic> json) leer) {
  if (v is! List) return const [];
  return [
    for (final e in v)
      if (e is Map) leer(Map<String, dynamic>.from(e)),
  ];
}

// ---- Manifiesto ----

class EmpresaPaquete {
  const EmpresaPaquete({required this.id, required this.codigo, required this.nombre});

  factory EmpresaPaquete.fromJson(Map<String, dynamic> json) => EmpresaPaquete(
    id: _enteroObligatorio(json['id']),
    codigo: _textoObligatorio(json['codigo']),
    nombre: _texto(json['nombre']) ?? _textoObligatorio(json['codigo']),
  );

  final int id;
  final String codigo;
  final String nombre;
}

/// Un tramo de atención ("HH:MM"). `diaSemana`: 1 = lunes ... 7 = domingo.
class HorarioPaquete {
  const HorarioPaquete({required this.diaSemana, required this.horaApertura, required this.horaCierre});

  factory HorarioPaquete.fromJson(Map<String, dynamic> json) => HorarioPaquete(
    diaSemana: _enteroObligatorio(json['dia_semana']),
    horaApertura: _textoObligatorio(json['hora_apertura']),
    horaCierre: _textoObligatorio(json['hora_cierre']),
  );

  final int diaSemana;
  final String horaApertura;
  final String horaCierre;
}

class SucursalPaquete {
  const SucursalPaquete({
    required this.id,
    required this.codigo,
    required this.nombre,
    this.direccion = '',
    this.esDeposito = false,
    this.horarios = const [],
  });

  factory SucursalPaquete.fromJson(Map<String, dynamic> json) => SucursalPaquete(
    id: _enteroObligatorio(json['id']),
    codigo: _texto(json['codigo']) ?? 'S${json['id']}',
    nombre: _textoObligatorio(json['nombre']),
    direccion: _texto(json['direccion']) ?? '',
    esDeposito: _booleano(json['es_deposito']),
    horarios: _lista(json['horarios'], HorarioPaquete.fromJson),
  );

  final int id;
  final String codigo;
  final String nombre;
  final String direccion;
  final bool esDeposito;
  final List<HorarioPaquete> horarios;
}

class CategoriaPaquete {
  const CategoriaPaquete({required this.id, required this.nombre, this.categoriaPadreId});

  factory CategoriaPaquete.fromJson(Map<String, dynamic> json) => CategoriaPaquete(
    id: _enteroObligatorio(json['id']),
    nombre: _textoObligatorio(json['nombre']),
    categoriaPadreId: _entero(json['categoria_padre_id']),
  );

  final int id;
  final String nombre;
  final int? categoriaPadreId;
}

class TallaPaquete {
  const TallaPaquete({required this.id, required this.codigo, this.orden = 0});

  factory TallaPaquete.fromJson(Map<String, dynamic> json) => TallaPaquete(
    id: _enteroObligatorio(json['id']),
    codigo: _textoObligatorio(json['codigo']),
    orden: _entero(json['orden']) ?? 0,
  );

  final int id;
  final String codigo;
  final int orden;
}

class ColorPaquete {
  const ColorPaquete({required this.id, required this.nombre, this.codigoHex});

  factory ColorPaquete.fromJson(Map<String, dynamic> json) => ColorPaquete(
    id: _enteroObligatorio(json['id']),
    nombre: _textoObligatorio(json['nombre']),
    codigoHex: _texto(json['codigo_hex']),
  );

  final int id;
  final String nombre;
  final String? codigoHex;
}

/// Las reglas que el servidor comunica al dispositivo (hoy solo informativas).
class ReglasPaquete {
  const ReglasPaquete({this.metodosPagoOffline = const ['efectivo'], this.maxOperacionesPorLote, this.plazoCambioHoras});

  factory ReglasPaquete.fromJson(Map<String, dynamic> json) => ReglasPaquete(
    metodosPagoOffline: json['metodos_pago_offline'] is List
        ? [for (final m in json['metodos_pago_offline'] as List) m.toString()]
        : const ['efectivo'],
    maxOperacionesPorLote: _entero(json['max_operaciones_por_lote']),
    plazoCambioHoras: _entero(json['plazo_cambio_horas']),
  );

  final List<String> metodosPagoOffline;
  final int? maxOperacionesPorLote;
  final int? plazoCambioHoras;
}

class ManifiestoPaquete {
  const ManifiestoPaquete({
    required this.versionContrato,
    required this.empresa,
    this.generadoEn,
    this.avisoDesactualizadoHoras,
    this.sucursales = const [],
    this.categorias = const [],
    this.tallas = const [],
    this.colores = const [],
    this.promocionesVigentes = const [],
    this.reglas = const ReglasPaquete(),
  });

  /// Lanza [ErrorApp] si la versión del contrato es mayor que la soportada o falta la empresa.
  factory ManifiestoPaquete.fromJson(Map<String, dynamic> json) {
    verificarVersionContrato(json['version_contrato']);
    final empresa = json['empresa'];
    if (empresa is! Map) throw _respuestaNoEntendida();
    final referencia = json['referencia'] is Map ? Map<String, dynamic>.from(json['referencia'] as Map) : const <String, dynamic>{};
    return ManifiestoPaquete(
      versionContrato: _texto(json['version_contrato']) ?? '$versionContratoSoportada',
      generadoEn: leerFechaUtc(json['generado_en']),
      avisoDesactualizadoHoras: _entero(json['aviso_desactualizado_horas']),
      empresa: EmpresaPaquete.fromJson(Map<String, dynamic>.from(empresa)),
      sucursales: _lista(json['sucursales'], SucursalPaquete.fromJson),
      categorias: _lista(referencia['categorias'], CategoriaPaquete.fromJson),
      tallas: _lista(referencia['tallas'], TallaPaquete.fromJson),
      colores: _lista(referencia['colores'], ColorPaquete.fromJson),
      promocionesVigentes: _lista(json['promociones_vigentes'], (m) => m),
      reglas: json['reglas'] is Map ? ReglasPaquete.fromJson(Map<String, dynamic>.from(json['reglas'] as Map)) : const ReglasPaquete(),
    );
  }

  final String versionContrato;
  final DateTime? generadoEn;
  final int? avisoDesactualizadoHoras;
  final EmpresaPaquete empresa;
  final List<SucursalPaquete> sucursales;
  final List<CategoriaPaquete> categorias;
  final List<TallaPaquete> tallas;
  final List<ColorPaquete> colores;

  /// Se conservan tal cual: la base local todavía no las usa.
  final List<Map<String, dynamic>> promocionesVigentes;
  final ReglasPaquete reglas;
}

// ---- Catálogo ----

class VariantePaquete {
  const VariantePaquete({
    required this.id,
    required this.tallaId,
    required this.colorId,
    required this.sku,
    required this.precioCentavos,
    this.descuentoCentavos = 0,
    this.codigoBarras,
  });

  factory VariantePaquete.fromJson(Map<String, dynamic> json) => VariantePaquete(
    id: _enteroObligatorio(json['id']),
    tallaId: _enteroObligatorio(json['talla_id']),
    colorId: _enteroObligatorio(json['color_id']),
    sku: _textoObligatorio(json['sku']),
    codigoBarras: _texto(json['codigo_barras']),
    // Sin precio no se vende: una variante sin precio hace fallar la descarga en vez de valer 0.
    precioCentavos: _centavos(json['precio']),
    descuentoCentavos: _centavos(json['descuento_unitario'], ausente: 0),
  );

  final int id;
  final int tallaId;
  final int colorId;
  final String sku;
  final String? codigoBarras;
  final int precioCentavos;
  final int descuentoCentavos;
}

class ProductoPaquete {
  const ProductoPaquete({
    required this.id,
    required this.codigo,
    required this.nombre,
    required this.categoriaId,
    this.genero = 'unisex',
    this.temporadaId,
    this.imagenPrincipal,
    this.variantes = const [],
  });

  factory ProductoPaquete.fromJson(Map<String, dynamic> json) => ProductoPaquete(
    id: _enteroObligatorio(json['id']),
    codigo: _textoObligatorio(json['codigo']),
    nombre: _textoObligatorio(json['nombre']),
    categoriaId: _enteroObligatorio(json['categoria_id']),
    genero: _texto(json['genero']) ?? 'unisex',
    temporadaId: _entero(json['temporada_id']),
    imagenPrincipal: _texto(json['imagen_principal']),
    variantes: _lista(json['variantes'], VariantePaquete.fromJson),
  );

  final int id;
  final String codigo;
  final String nombre;
  final int categoriaId;
  final String genero;
  final int? temporadaId;
  final String? imagenPrincipal;
  final List<VariantePaquete> variantes;
}

class PaginaCatalogo {
  const PaginaCatalogo({required this.total, required this.items, this.siguienteDesdeId, this.generadoEn});

  factory PaginaCatalogo.fromJson(Map<String, dynamic> json) {
    verificarVersionContrato(json['version_contrato']);
    return PaginaCatalogo(
      generadoEn: leerFechaUtc(json['generado_en']),
      total: _entero(json['total']) ?? 0,
      siguienteDesdeId: _entero(json['siguiente_desde_id']),
      items: _lista(json['items'], ProductoPaquete.fromJson),
    );
  }

  final DateTime? generadoEn;

  /// Productos activos de la empresa: sirve para verificar que no faltó ninguna página.
  final int total;

  /// `null` = última página.
  final int? siguienteDesdeId;
  final List<ProductoPaquete> items;
}

// ---- Stock ----

class ItemStockPaquete {
  const ItemStockPaquete({required this.varianteId, required this.cantidadDisponible, this.actualizadoEn});

  factory ItemStockPaquete.fromJson(Map<String, dynamic> json) => ItemStockPaquete(
    varianteId: _enteroObligatorio(json['variante_id']),
    cantidadDisponible: _entero(json['cantidad_disponible']) ?? 0,
    actualizadoEn: leerFechaUtc(json['actualizado_en']),
  );

  final int varianteId;

  /// Física menos reservada. Puede llegar negativa si hay más reservas que existencias: al guardar se lleva a 0.
  final int cantidadDisponible;
  final DateTime? actualizadoEn;
}

class PaginaStock {
  const PaginaStock({
    required this.sucursalId,
    required this.generadoEn,
    required this.items,
    this.incremental = false,
    this.siguienteDesdeVarianteId,
  });

  /// `generado_en` es obligatorio: sin él no hay forma segura de pedir el siguiente delta.
  factory PaginaStock.fromJson(Map<String, dynamic> json) {
    verificarVersionContrato(json['version_contrato']);
    final generadoEn = leerFechaUtc(json['generado_en']);
    if (generadoEn == null) throw _respuestaNoEntendida();
    return PaginaStock(
      sucursalId: _enteroObligatorio(json['sucursal_id']),
      generadoEn: generadoEn,
      incremental: _booleano(json['incremental']),
      siguienteDesdeVarianteId: _entero(json['siguiente_desde_variante_id']),
      items: _lista(json['items'], ItemStockPaquete.fromJson),
    );
  }

  final int sucursalId;
  final DateTime generadoEn;
  final bool incremental;
  final int? siguienteDesdeVarianteId;
  final List<ItemStockPaquete> items;
}

// ---- Clientes ----

class ClientePaquete {
  const ClientePaquete({required this.id, required this.nombre, this.apellido, this.ciNit});

  factory ClientePaquete.fromJson(Map<String, dynamic> json) => ClientePaquete(
    id: _enteroObligatorio(json['id']),
    nombre: _textoObligatorio(json['nombre']),
    apellido: _texto(json['apellido']),
    ciNit: _texto(json['ci_nit']),
  );

  final int id;
  final String nombre;
  final String? apellido;
  final String? ciNit;
}

class PaginaClientes {
  const PaginaClientes({required this.total, required this.items, this.siguienteDesdeId, this.generadoEn});

  factory PaginaClientes.fromJson(Map<String, dynamic> json) {
    verificarVersionContrato(json['version_contrato']);
    return PaginaClientes(
      generadoEn: leerFechaUtc(json['generado_en']),
      total: _entero(json['total']) ?? 0,
      siguienteDesdeId: _entero(json['siguiente_desde_id']),
      items: _lista(json['items'], ClientePaquete.fromJson),
    );
  }

  final DateTime? generadoEn;
  final int total;
  final int? siguienteDesdeId;
  final List<ClientePaquete> items;
}

// ---- Resultados de recorrer todas las páginas ----

class CatalogoDescargado {
  const CatalogoDescargado({required this.productos, this.generadoEn});

  final List<ProductoPaquete> productos;

  /// El `generado_en` de la primera página.
  final DateTime? generadoEn;
}

class StockDescargado {
  const StockDescargado({required this.sucursalId, required this.items, required this.incremental, required this.generadoEn});

  final int sucursalId;
  final List<ItemStockPaquete> items;
  final bool incremental;

  /// El `generado_en` de la PRIMERA página: es el instante más antiguo en que se leyó, así que el siguiente delta nunca se
  /// salta un cambio que ocurrió mientras se descargaban las demás páginas.
  final DateTime generadoEn;
}

class ClientesDescargados {
  const ClientesDescargados({required this.clientes});

  final List<ClientePaquete> clientes;
}
