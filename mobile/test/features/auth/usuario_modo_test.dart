import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/auth/models/usuario.dart';

Usuario _usuario({
  List<String> roles = const [],
  List<String> permisos = const [],
  int? empresaId = 7,
  String? empresaCodigo = 'chaski',
  String? empresaNombre = 'Chaski Sport',
  String? telefono = '70012345',
}) {
  return Usuario(
    id: 3,
    nombre: 'Ana',
    apellido: 'Rojas',
    email: 'ana@example.com',
    telefono: telefono,
    activo: true,
    roles: roles,
    permisos: permisos,
    empresaId: empresaId,
    empresaCodigo: empresaCodigo,
    empresaNombre: empresaNombre,
  );
}

Map<String, dynamic> _json({Map<String, dynamic> extra = const {}, List<String> quitar = const []}) {
  final base = <String, dynamic>{
    'id': 3,
    'nombre': 'Ana',
    'apellido': 'Rojas',
    'email': 'ana@example.com',
    'telefono': null,
    'activo': true,
    'roles': ['cajero'],
    'permisos': ['ventas.presencial'],
    'empresa_id': 7,
    'empresa_codigo': 'chaski',
    'empresa_nombre': 'Chaski Sport',
    ...extra,
  };
  for (final clave in quitar) {
    base.remove(clave);
  }
  return base;
}

void main() {
  group('Usuario.modo', () {
    test('un cliente entra como cliente', () {
      expect(_usuario(roles: ['cliente']).modo, ModoApp.cliente);
      expect(_usuario(roles: ['cliente']).esCliente, isTrue);
    });

    test('el rol cliente manda aunque tenga además otros roles', () {
      expect(_usuario(roles: ['cajero', 'cliente'], permisos: ['ventas.presencial']).modo, ModoApp.cliente);
    });

    test('el rol cliente manda aunque tenga permisos de venta', () {
      final u = _usuario(roles: ['cliente'], permisos: ['ventas.presencial', 'reservas.gestionar_sucursal']);
      expect(u.modo, ModoApp.cliente);
    });

    test('el rol cliente manda aunque sea administrador', () {
      expect(_usuario(roles: ['administrador', 'cliente'], permisos: ['ventas.presencial']).modo, ModoApp.cliente);
    });

    test('un cajero con ventas.presencial es vendedor', () {
      expect(_usuario(roles: ['cajero'], permisos: ['ventas.presencial']).modo, ModoApp.vendedor);
    });

    test('un encargado con reservas.gestionar_sucursal es vendedor', () {
      expect(
        _usuario(roles: ['encargado_sucursal'], permisos: ['reservas.gestionar_sucursal']).modo,
        ModoApp.vendedor,
      );
    });

    test('un administrador con ambos permisos es vendedor', () {
      final u = _usuario(roles: ['administrador'], permisos: ['ventas.presencial', 'reservas.gestionar_sucursal']);
      expect(u.modo, ModoApp.vendedor);
    });

    test('el modo sale de los permisos, no del nombre del rol', () {
      expect(_usuario(roles: ['vendedor'], permisos: const []).modo, ModoApp.sinAcceso);
      expect(_usuario(roles: ['rol_inventado'], permisos: ['ventas.presencial']).modo, ModoApp.vendedor);
    });

    test('un proveedor sin esos permisos no tiene acceso', () {
      expect(_usuario(roles: ['proveedor'], permisos: ['catalogo.ver']).modo, ModoApp.sinAcceso);
    });

    test('el superadministrador (sin empresa) no tiene acceso', () {
      final u = _usuario(
        roles: ['superadministrador'],
        permisos: ['plataforma.gestionar'],
        empresaId: null,
        empresaCodigo: null,
        empresaNombre: null,
      );
      expect(u.modo, ModoApp.sinAcceso);
    });

    test('sin roles ni permisos no tiene acceso', () {
      expect(_usuario().modo, ModoApp.sinAcceso);
      expect(_usuario().esCliente, isFalse);
    });

    test('un permiso parecido no cuenta (se compara exacto)', () {
      expect(_usuario(roles: ['cajero'], permisos: ['ventas.ver', 'reservas.gestionar']).modo, ModoApp.sinAcceso);
    });
  });

  group('Usuario.fromJson', () {
    test('lee todos los campos, la empresa incluida', () {
      final u = Usuario.fromJson(_json());
      expect(u.id, 3);
      expect(u.nombre, 'Ana');
      expect(u.apellido, 'Rojas');
      expect(u.email, 'ana@example.com');
      expect(u.telefono, isNull);
      expect(u.activo, isTrue);
      expect(u.roles, ['cajero']);
      expect(u.permisos, ['ventas.presencial']);
      expect(u.empresaId, 7);
      expect(u.empresaCodigo, 'chaski');
      expect(u.empresaNombre, 'Chaski Sport');
      expect(u.modo, ModoApp.vendedor);
    });

    test('tolera que falten empresa_id, empresa_codigo y empresa_nombre', () {
      final u = Usuario.fromJson(_json(quitar: ['empresa_id', 'empresa_codigo', 'empresa_nombre']));
      expect(u.empresaId, isNull);
      expect(u.empresaCodigo, isNull);
      expect(u.empresaNombre, isNull);
    });

    test('tolera empresa en null (superadministrador)', () {
      final u = Usuario.fromJson(
        _json(
          extra: {
            'empresa_id': null,
            'empresa_codigo': null,
            'empresa_nombre': null,
            'roles': ['superadministrador'],
            'permisos': ['plataforma.gestionar'],
          },
        ),
      );
      expect(u.empresaId, isNull);
      expect(u.empresaCodigo, isNull);
      expect(u.modo, ModoApp.sinAcceso);
    });

    test('tolera que falten los permisos (queda vacío)', () {
      final u = Usuario.fromJson(_json(quitar: ['permisos']));
      expect(u.permisos, isEmpty);
      expect(u.modo, ModoApp.sinAcceso);
    });

    test('tolera permisos en null', () {
      final u = Usuario.fromJson(_json(extra: {'permisos': null}));
      expect(u.permisos, isEmpty);
    });

    test('lee el teléfono cuando viene', () {
      expect(Usuario.fromJson(_json(extra: {'telefono': '70012345'})).telefono, '70012345');
    });

    test('un JSON de cliente da modo cliente', () {
      final u = Usuario.fromJson(_json(extra: {'roles': ['cliente'], 'permisos': <String>[]}));
      expect(u.modo, ModoApp.cliente);
    });
  });

  group('Usuario.toJson', () {
    test('ida y vuelta: el usuario recuperado es el mismo', () {
      final original = _usuario(roles: ['encargado_sucursal'], permisos: ['reservas.gestionar_sucursal', 'ventas.presencial']);
      final vuelta = Usuario.fromJson(original.toJson());

      expect(vuelta.id, original.id);
      expect(vuelta.nombre, original.nombre);
      expect(vuelta.apellido, original.apellido);
      expect(vuelta.email, original.email);
      expect(vuelta.telefono, original.telefono);
      expect(vuelta.activo, original.activo);
      expect(vuelta.roles, original.roles);
      expect(vuelta.permisos, original.permisos);
      expect(vuelta.empresaId, original.empresaId);
      expect(vuelta.empresaCodigo, original.empresaCodigo);
      expect(vuelta.empresaNombre, original.empresaNombre);
      expect(vuelta.modo, original.modo);
      expect(vuelta.toJson(), original.toJson());
    });

    test('ida y vuelta pasando por texto JSON (como el almacenamiento seguro)', () {
      final original = _usuario(roles: ['cajero'], permisos: ['ventas.presencial']);
      final texto = jsonEncode(original.toJson());
      final vuelta = Usuario.fromJson(jsonDecode(texto) as Map<String, dynamic>);

      expect(vuelta.toJson(), original.toJson());
      expect(vuelta.modo, ModoApp.vendedor);
    });

    test('ida y vuelta de un usuario sin empresa ni teléfono', () {
      final original = _usuario(
        roles: ['superadministrador'],
        empresaId: null,
        empresaCodigo: null,
        empresaNombre: null,
        telefono: null,
      );
      final vuelta = Usuario.fromJson(jsonDecode(jsonEncode(original.toJson())) as Map<String, dynamic>);

      expect(vuelta.empresaId, isNull);
      expect(vuelta.empresaCodigo, isNull);
      expect(vuelta.empresaNombre, isNull);
      expect(vuelta.telefono, isNull);
      expect(vuelta.toJson(), original.toJson());
    });

    test('el JSON no lleva contraseña ni token', () {
      final json = _usuario(roles: ['cajero'], permisos: ['ventas.presencial']).toJson();
      final texto = jsonEncode(json).toLowerCase();

      expect(texto, isNot(contains('password')));
      expect(texto, isNot(contains('contrase')));
      expect(texto, isNot(contains('token')));
      expect(json.keys, isNot(contains('password')));
      expect(json.keys, isNot(contains('access_token')));
      expect(json.keys, isNot(contains('refresh_token')));
    });

    test('las claves del JSON son exactamente las del perfil', () {
      expect(
        _usuario().toJson().keys.toSet(),
        {
          'id',
          'nombre',
          'apellido',
          'email',
          'telefono',
          'activo',
          'roles',
          'permisos',
          'empresa_id',
          'empresa_codigo',
          'empresa_nombre',
        },
      );
    });
  });
}
