import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../../features/auth/models/usuario.dart';
import '../../features/tienda/models/tienda.dart';

/// Guarda en el almacenamiento seguro del dispositivo la tienda elegida. Mismo criterio que [TokenStorage]: ya está en
/// el proyecto, no se agrega ninguna librería, y no se guarda ninguna contraseña ni token. Las pruebas lo reemplazan
/// por un falso que hereda de esta clase.
class SesionStorage {
  const SesionStorage();

  static const _claveTienda = 'fs_tienda';
  static const _clavePerfil = 'fs_perfil';

  static const _storage = FlutterSecureStorage();

  Future<void> guardarTienda(Tienda tienda) => _storage.write(key: _claveTienda, value: jsonEncode(tienda.toJson()));

  /// La tienda guardada, o null si no hay o el valor guardado está dañado.
  Future<Tienda?> leerTienda() async {
    final texto = await _storage.read(key: _claveTienda);
    if (texto == null) return null;
    try {
      return Tienda.fromJson(jsonDecode(texto) as Map<String, dynamic>);
    } catch (_) {
      await _storage.delete(key: _claveTienda);
      return null;
    }
  }

  Future<void> borrarTienda() => _storage.delete(key: _claveTienda);

  /// El último perfil verificado del personal (roles y permisos incluidos). Solo sirve para mostrar la interfaz cuando
  /// no hay conexión: el servidor vuelve a validar todo al sincronizar. No guarda contraseñas ni tokens.
  Future<void> guardarPerfil(Usuario usuario) => _storage.write(key: _clavePerfil, value: jsonEncode(usuario.toJson()));

  /// El perfil guardado, o null si no hay o el valor está dañado.
  Future<Usuario?> leerPerfil() async {
    final texto = await _storage.read(key: _clavePerfil);
    if (texto == null) return null;
    try {
      return Usuario.fromJson(jsonDecode(texto) as Map<String, dynamic>);
    } catch (_) {
      await _storage.delete(key: _clavePerfil);
      return null;
    }
  }

  Future<void> borrarPerfil() => _storage.delete(key: _clavePerfil);
}
