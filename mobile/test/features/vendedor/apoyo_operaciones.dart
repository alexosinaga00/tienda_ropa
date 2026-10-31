import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/conectividad/conectividad_service.dart';
import 'package:mobile/core/utils/reloj.dart';
import 'package:mobile/features/auth/models/usuario.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';
import 'package:mobile/features/vendedor/state/catalogo_local_providers.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';

import '../../helpers/base_local_falsa.dart';

/// Un [AuthController] real cuyo estado se fija en el constructor (así los providers de empresa y usuario locales leen
/// la sesión que la prueba quiere sin tocar red ni almacenamiento).
class AuthControllerFijo extends AuthController {
  AuthControllerFijo(super.ref, AuthState inicial) {
    state = inicial;
  }

  /// Cambia la sesión en plena prueba (por ejemplo, para entrar con otra empresa).
  void fijar(AuthState nuevo) => state = nuevo;
}

/// Una cuenta del personal (cajero) de la empresa dada.
Usuario personalDe({int id = 7, int empresaId = 1, String codigo = 'chaski'}) {
  return Usuario(
    id: id,
    nombre: 'Marta',
    apellido: 'Quispe',
    email: 'marta$id@$codigo.bo',
    telefono: null,
    activo: true,
    roles: const ['cajero'],
    permisos: const ['ventas.presencial'],
    empresaId: empresaId,
    empresaCodigo: codigo,
    empresaNombre: codigo,
  );
}

AuthState sesionDe(Usuario usuario) => AuthState(estado: EstadoSesion.autenticado, usuario: usuario);

const sinSesion = AuthState(estado: EstadoSesion.noAutenticado);

/// Un contenedor de Riverpod con la base real de prueba, la sesión dada y, si se piden, reloj y conectividad.
ProviderContainer contenedorLocal(
  Database db, {
  AuthState auth = sinSesion,
  Reloj? reloj,
  ConectividadService? conectividad,
  List<Override> extra = const [],
}) {
  final contenedor = ProviderContainer(
    overrides: [
      baseLocalProvider.overrideWith((ref) async => db),
      authControllerProvider.overrideWith((ref) => AuthControllerFijo(ref, auth)),
      if (reloj != null) relojProvider.overrideWithValue(reloj),
      if (conectividad != null) conectividadServiceProvider.overrideWithValue(conectividad),
      ...extra,
    ],
  );
  addTearDown(contenedor.dispose);
  return contenedor;
}

/// Un cliente de la empresa; devuelve su id. Sin [servidorId] es un cliente creado en el teléfono.
Future<int> sembrarCliente(
  Database db, {
  int empresaId = 1,
  int? servidorId,
  String nombre = 'Cliente',
  String? ciNit,
  String creadoEn = '2026-10-31T09:00:00Z',
}) {
  return db.insert('cliente_minimo', {
    'empresa_id': empresaId,
    'servidor_id': servidorId,
    'nombre': nombre,
    'ci_nit': ciNit,
    'creado_en': creadoEn,
  });
}

/// Una operación con su venta (o su reserva), el detalle y, si se pide, una respuesta del servidor.
///
/// - [tipo] `venta_contado` o `reserva` (la reserva exige [clienteId]).
/// - [creadaEn] y [resueltaEn] en texto ISO tal cual se guardarán.
Future<void> sembrarOperacion(
  Database db, {
  required String id,
  int empresaId = 1,
  int sucursalId = 1,
  int usuarioId = 7,
  String tipo = 'venta_contado',
  String estado = 'registrada',
  String creadaEn = '2026-10-31T09:00:00Z',
  String? resueltaEn,
  int? clienteId,
  int varianteId = 100,
  bool conResultado = false,
}) async {
  await db.insert('operacion_pendiente', {
    'operacion_id': id,
    'empresa_id': empresaId,
    'sucursal_id': sucursalId,
    'usuario_id': usuarioId,
    'tipo': tipo,
    'estado': estado,
    'payload': '{}',
    'version_contrato': 1,
    'fecha_operacion': creadaEn,
    'creada_en': creadaEn,
    'resuelta_en': resueltaEn,
  });
  if (tipo == 'reserva') {
    final reservaId = await db.insert('reserva', {
      'operacion_id': id,
      'empresa_id': empresaId,
      'sucursal_id': sucursalId,
      'usuario_id': usuarioId,
      'cliente_minimo_id': clienteId!,
      'fecha_operacion': creadaEn,
      'fecha_visita': '2026-11-02',
      'hora_visita_desde': '10:00',
      'hora_visita_hasta': '11:00',
    });
    await db.insert('reserva_detalle', {'reserva_id': reservaId, 'variante_id': varianteId, 'cantidad': 1});
  } else {
    final ventaId = await db.insert('venta', {
      'operacion_id': id,
      'empresa_id': empresaId,
      'sucursal_id': sucursalId,
      'usuario_id': usuarioId,
      'cliente_minimo_id': clienteId,
      'fecha_operacion': creadaEn,
      'forma_pago': 'efectivo',
      'total_centavos': 7500,
    });
    await db.insert('venta_detalle', {
      'venta_id': ventaId,
      'variante_id': varianteId,
      'cantidad': 1,
      'precio_unitario_centavos': 7500,
    });
  }
  if (conResultado) {
    await db.insert('resultado_sync', {
      'operacion_id': id,
      'recibido_en': resueltaEn ?? creadaEn,
      'estado_resultado': estado,
    });
  }
}

/// Dos empresas con su catálogo mínimo: la 1 (sucursal 1, producto 10 con las variantes 100 y 101) y la 2 (sucursal 11,
/// producto 20 con la variante 200).
Future<void> sembrarDosEmpresas(Database db) async {
  await sembrarEmpresa(db);
  await sembrarSucursal(db, id: 1);
  await sembrarReferencias(db);
  await sembrarProducto(
    db,
    id: 10,
    nombre: 'Polera Básica',
    variantes: [variante(100), variante(101, tallaId: 2)],
  );
  await sembrarStock(db, varianteId: 100, sucursalId: 1, cantidad: 5);
  await sembrarStock(db, varianteId: 101, sucursalId: 1, cantidad: 3);

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
  await sembrarStock(db, varianteId: 200, sucursalId: 11, cantidad: 4);
}
