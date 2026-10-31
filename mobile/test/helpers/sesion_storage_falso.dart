import 'package:mobile/core/sesion/sesion_storage.dart';
import 'package:mobile/features/auth/models/usuario.dart';
import 'package:mobile/features/tienda/models/tienda.dart';

/// Doble en memoria de SesionStorage para tests: el real usa flutter_secure_storage, que necesita un canal de
/// plataforma que no existe en `flutter test`.
class SesionStorageFalso extends SesionStorage {
  SesionStorageFalso({this.tienda, this.perfil});

  Tienda? tienda;
  Usuario? perfil;
  int vecesBorrada = 0;
  int vecesPerfilBorrado = 0;

  @override
  Future<void> guardarTienda(Tienda tienda) async => this.tienda = tienda;

  @override
  Future<Tienda?> leerTienda() async => tienda;

  @override
  Future<void> borrarTienda() async {
    tienda = null;
    vecesBorrada++;
  }

  @override
  Future<void> guardarPerfil(Usuario usuario) async => perfil = usuario;

  @override
  Future<Usuario?> leerPerfil() async => perfil;

  @override
  Future<void> borrarPerfil() async {
    perfil = null;
    vecesPerfilBorrado++;
  }
}
