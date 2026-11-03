import 'package:mobile/core/sync/contrato_sync.dart';
import 'package:mobile/core/utils/reloj.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import 'base_local_falsa.dart';

/// Un reloj que se mueve a mano.
class RelojDePrueba implements Reloj {
  RelojDePrueba([DateTime? inicio]) : actual = inicio ?? DateTime.utc(2026, 10, 31, 12);

  DateTime actual;

  @override
  DateTime ahora() => actual;

  void avanzar(Duration d) => actual = actual.add(d);
}

/// Un cliente de `cliente_minimo`; devuelve su id local. Sin [servidorId] es un cliente creado solo en el teléfono.
Future<int> sembrarClienteMinimo(
  Database db, {
  int empresaId = 1,
  int? servidorId,
  String nombre = 'Cliente',
  String? apellido,
  String? ciNit,
  String creadoEn = '2026-10-31T09:00:00Z',
}) {
  return db.insert('cliente_minimo', {
    'empresa_id': empresaId,
    'servidor_id': servidorId,
    'nombre': nombre,
    'apellido': apellido,
    'ci_nit': ciNit,
    'creado_en': creadoEn,
  });
}

/// El mundo mínimo para registrar operaciones:
/// - Empresa 1: sucursal 1 (activa), sucursal 2 (dada de baja), producto 10 "Polera Básica" con las variantes 100 (talla S, 75,00)
///   y 101 (talla M, 50,00), y el producto 11 dado de baja con la variante 110.
///   Clientes: id 1 "Ana Pérez" (servidor 501), id 2 "Luis Solo" (solo en el teléfono).
/// - Empresa 2: sucursal 11, producto 20 con la variante 200 y el cliente id 3 (servidor 601).
Future<void> sembrarMundoDeOperaciones(Database db) async {
  await sembrarEmpresa(db);
  await sembrarSucursal(db, id: 1);
  await sembrarSucursal(db, id: 2, activo: false);
  await sembrarReferencias(db);
  await sembrarProducto(
    db,
    id: 10,
    nombre: 'Polera Básica',
    imagen: 'https://img.test/polera.jpg',
    variantes: [variante(100, sku: 'POL-S-NEG'), variante(101, tallaId: 2, sku: 'POL-M-NEG', precio: 5000)],
  );
  await sembrarProducto(db, id: 11, nombre: 'Chompa Vieja', activo: false, variantes: [variante(110, tallaId: 3)]);
  await sembrarStock(db, varianteId: 100, sucursalId: 1, cantidad: 10);
  await sembrarStock(db, varianteId: 101, sucursalId: 1, cantidad: 4);
  await sembrarClienteMinimo(db, servidorId: 501, nombre: 'Ana', apellido: 'Pérez', ciNit: '1234567');
  await sembrarClienteMinimo(db, nombre: 'Luis', apellido: 'Solo');

  await sembrarEmpresa(db, id: 2, codigo: 'andina', nombre: 'Boutique Andina');
  await sembrarSucursal(db, id: 11, empresaId: 2);
  await sembrarReferencias(db, empresaId: 2, categoriaId: 2);
  await sembrarProducto(
    db,
    id: 20,
    empresaId: 2,
    nombre: 'Chompa Andina',
    categoriaId: 2,
    variantes: [variante(200, tallaId: 201, colorId: 201)],
  );
  await sembrarClienteMinimo(db, empresaId: 2, servidorId: 601, nombre: 'Rosa', apellido: 'Mamani');
}

/// Cuántas filas tiene una tabla (para comprobar que un rollback no dejó nada).
Future<int> contarFilas(Database db, String tabla) async {
  final filas = await db.rawQuery('SELECT COUNT(*) AS n FROM $tabla');
  return filas.first['n']! as int;
}

/// Las filas de las cuatro tablas que escribe un registro (para comparar "antes" y "después").
Future<List<int>> huellaDeRegistro(Database db) async => [
  for (final t in ['operacion_pendiente', 'venta', 'venta_detalle', 'reserva', 'reserva_detalle', 'resultado_sync'])
    await contarFilas(db, t),
];

/// Un resultado del servidor para armar pruebas.
ResultadoOperacionSync resultadoDe(
  String operacionId,
  EstadoResultadoSync estado, {
  String? motivo,
  String? mensaje,
  bool duplicada = false,
  DateTime? procesadaEn,
  RecursoSync? recurso,
  int? cambioCentavos,
  List<AvisoPrecioSync> avisos = const [],
  List<FaltanteSync> faltantes = const [],
  ResolucionSync? resolucion,
}) {
  return ResultadoOperacionSync(
    operacionId: operacionId,
    estado: estado,
    motivo: motivo,
    mensaje: mensaje,
    duplicada: duplicada,
    procesadaEn: procesadaEn,
    recurso: recurso,
    cambioCentavos: cambioCentavos,
    avisos: avisos,
    faltantes: faltantes,
    resolucion: resolucion,
  );
}
