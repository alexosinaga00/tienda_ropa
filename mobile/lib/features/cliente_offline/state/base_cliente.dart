import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:sqflite/sqflite.dart';

import '../../../core/local_cliente/abrir_base_cliente.dart';
import '../data/repositorio_cliente.dart';
import '../models/linea_carrito_local.dart';

/// La base local (SQLite) del CLIENTE: un archivo aparte del de la base del personal. Se abre la primera vez que se usa. En
/// las pruebas se reemplaza con `baseClienteProvider.overrideWith(...)`.
final baseClienteProvider = FutureProvider<Database>((ref) async {
  final db = await abrirBaseCliente();
  ref.onDispose(db.close);
  return db;
});

/// Lo que se limpia de la base del cliente cuando alguien cierra sesión.
class LimpiezaCliente {
  LimpiezaCliente(this._base);

  final Future<Database> Function() _base;

  /// Cierre normal o forzado: borra el carrito local, lo recordado (método de pago) y los pedidos ya resueltos de esa
  /// persona. Los pedidos sin enviar se CONSERVAN: son compras que ya aceptó y salen cuando la misma cuenta vuelva a entrar.
  Future<void> alCerrarSesion(AlcanceCliente alcance) async {
    await RepositorioCliente(await _base(), alcance: alcance).vaciarAlCerrarSesion();
  }

  /// "Borrarlos y salir": además de lo anterior, borra los pedidos sin enviar de esa persona.
  Future<void> borrarTodo(AlcanceCliente alcance) async {
    await RepositorioCliente(await _base(), alcance: alcance).borrarTodo();
  }
}

final limpiezaClienteProvider = Provider<LimpiezaCliente>(
  (ref) => LimpiezaCliente(() => ref.read(baseClienteProvider.future)),
);
