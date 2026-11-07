import 'package:sqflite/sqflite.dart';

import '../models/linea_carrito_local.dart';
import '../models/pedido_sin_conexion.dart';

/// Las únicas columnas de un pedido que se pueden cambiar después de registrarlo.
const columnasModificablesPedido = {
  'estado',
  'intentos',
  'ultimo_intento_en',
  'proximo_intento_en',
  'ultimo_error',
  'motivo',
  'mensaje',
  'venta_id',
  'codigo_venta',
  'total_centavos',
  'total_usd',
  'resuelto_en',
  'visto',
};

/// La ÚNICA clase que toca las tablas de la persona (`cli_meta`, `cli_carrito`, `cli_pedido`). Se construye con un alcance
/// obligatorio (empresa y usuario) y todas sus consultas lo aplican: ninguna pantalla ni servicio recibe una tabla.
///
/// Un pedido en cola solo se puede quitar con [descartarPedido] (y únicamente si todavía no salió o ya venció) o con
/// [borrarTodo] (que solo se llama cuando la persona lo eligió al salir): nada lo borra por intentar enviarlo.
class RepositorioCliente {
  RepositorioCliente(this._db, {required this.alcance});

  final Database _db;
  final AlcanceCliente alcance;

  int get _e => alcance.empresaId;
  int get _u => alcance.usuarioId;

  // ---- Meta ----------------------------------------------------------------------------------------------------------

  Future<String?> leerMeta(String clave) async {
    final filas = await _db.query(
      'cli_meta',
      columns: ['valor'],
      where: 'empresa_id = ? AND usuario_id = ? AND clave = ?',
      whereArgs: [_e, _u, clave],
    );
    return filas.isEmpty ? null : filas.first['valor'] as String?;
  }

  Future<void> guardarMeta(String clave, String valor) async {
    await _db.insert('cli_meta', {
      'empresa_id': _e,
      'usuario_id': _u,
      'clave': clave,
      'valor': valor,
    }, conflictAlgorithm: ConflictAlgorithm.replace);
  }

  Future<void> borrarMeta(String clave) async {
    await _db.delete('cli_meta', where: 'empresa_id = ? AND usuario_id = ? AND clave = ?', whereArgs: [_e, _u, clave]);
  }

  // ---- Carrito local -------------------------------------------------------------------------------------------------

  /// Las líneas de MI carrito local, de la más vieja a la más nueva.
  Future<List<LineaCarritoLocal>> carrito() async {
    final filas = await _db.query(
      'cli_carrito',
      where: 'empresa_id = ? AND usuario_id = ?',
      whereArgs: [_e, _u],
      orderBy: 'agregado_en ASC, variante_id ASC',
    );
    return [for (final f in filas) LineaCarritoLocal.desdeFila(f)];
  }

  /// Agrega la línea; si la variante ya estaba, suma las cantidades (hasta [maximo]). Una sola transacción.
  Future<LineaCarritoLocal> agregarLinea(LineaCarritoLocal linea, {required int maximo}) {
    return _db.transaction((txn) async {
      final existentes = await txn.query(
        'cli_carrito',
        where: 'empresa_id = ? AND usuario_id = ? AND variante_id = ?',
        whereArgs: [_e, _u, linea.varianteId],
      );
      final LineaCarritoLocal nueva;
      if (existentes.isEmpty) {
        nueva = linea.conCantidad(linea.cantidad > maximo ? maximo : linea.cantidad);
      } else {
        final previa = LineaCarritoLocal.desdeFila(existentes.first);
        final suma = previa.cantidad + linea.cantidad;
        // Se conserva cuándo se agregó por primera vez, pero se refrescan los datos que el cliente acaba de ver.
        nueva = LineaCarritoLocal(
          varianteId: linea.varianteId,
          productoId: linea.productoId,
          cantidad: suma > maximo ? maximo : suma,
          productoNombre: linea.productoNombre,
          talla: linea.talla,
          color: linea.color,
          precioUnitarioCentavos: linea.precioUnitarioCentavos,
          imagen: linea.imagen,
          sucursalId: linea.sucursalId ?? previa.sucursalId,
          sucursalNombre: linea.sucursalNombre ?? previa.sucursalNombre,
          agregadoEn: previa.agregadoEn,
        );
      }
      await txn.insert('cli_carrito', nueva.aFila(alcance), conflictAlgorithm: ConflictAlgorithm.replace);
      return nueva;
    });
  }

  /// Cambia la cantidad de una línea; con 0 o menos la quita.
  Future<void> cambiarCantidad(int varianteId, int cantidad) async {
    if (cantidad <= 0) {
      await quitarLinea(varianteId);
      return;
    }
    await _db.update(
      'cli_carrito',
      {'cantidad': cantidad},
      where: 'empresa_id = ? AND usuario_id = ? AND variante_id = ?',
      whereArgs: [_e, _u, varianteId],
    );
  }

  Future<void> quitarLinea(int varianteId) async {
    await _db.delete(
      'cli_carrito',
      where: 'empresa_id = ? AND usuario_id = ? AND variante_id = ?',
      whereArgs: [_e, _u, varianteId],
    );
  }

  Future<void> vaciarCarrito() => _vaciarCarrito(_db);

  Future<void> _vaciarCarrito(DatabaseExecutor ejecutor) async {
    await ejecutor.delete('cli_carrito', where: 'empresa_id = ? AND usuario_id = ?', whereArgs: [_e, _u]);
  }

  // ---- Pedidos sin conexión ------------------------------------------------------------------------------------------

  /// Guarda un pedido NUEVO. Si ya existe uno con la misma `operacion_id` (doble toque), devuelve el que ya estaba y NO
  /// crea otro. Con [vaciarElCarrito] vacía el carrito local en la MISMA transacción: o queda el pedido y el carrito
  /// vacío, o no pasa nada.
  Future<PedidoSinConexion> registrarPedido(PedidoSinConexion pedido, {bool vaciarElCarrito = false}) async {
    _exigirMio(pedido.empresaId, pedido.usuarioId);
    return _db.transaction((txn) async {
      final existentes = await txn.query(
        'cli_pedido',
        where: 'empresa_id = ? AND usuario_id = ? AND operacion_id = ?',
        whereArgs: [_e, _u, pedido.operacionId],
      );
      if (existentes.isNotEmpty) return PedidoSinConexion.desdeFila(existentes.first);
      await txn.insert('cli_pedido', pedido.aFila());
      if (vaciarElCarrito) await _vaciarCarrito(txn);
      return pedido;
    });
  }

  Future<PedidoSinConexion?> pedido(String operacionId) async {
    final filas = await _db.query(
      'cli_pedido',
      where: 'empresa_id = ? AND usuario_id = ? AND operacion_id = ?',
      whereArgs: [_e, _u, operacionId],
    );
    return filas.isEmpty ? null : PedidoSinConexion.desdeFila(filas.first);
  }

  /// Mis pedidos, del más nuevo al más viejo.
  Future<List<PedidoSinConexion>> pedidos() async {
    final filas = await _db.query(
      'cli_pedido',
      where: 'empresa_id = ? AND usuario_id = ?',
      whereArgs: [_e, _u],
      orderBy: 'creado_en DESC',
    );
    return [for (final f in filas) PedidoSinConexion.desdeFila(f)];
  }

  /// Cuántos pedidos míos siguen sin enviar (`pendiente` o `enviando`). Los vencidos y los resueltos no cuentan.
  Future<int> contarSinEnviar() async {
    final filas = await _db.rawQuery(
      "SELECT COUNT(*) AS n FROM cli_pedido WHERE empresa_id = ? AND usuario_id = ? AND estado IN ('pendiente', 'enviando')",
      [_e, _u],
    );
    return (filas.first['n'] as int?) ?? 0;
  }

  /// Lo que falta por enviar, el más antiguo primero: los `pendiente` y los `enviando` que llevan más de [huerfano] (un
  /// cierre brusco los dejó a medias; reenviarlos es seguro porque el servidor es idempotente). Un `enviando` reciente NO
  /// entra: se está enviando ahora mismo.
  Future<List<PedidoSinConexion>> pedidosParaEnviar(DateTime ahora, Duration huerfano) async {
    final todos = await pedidos();
    final candidatos = todos.where((p) {
      if (p.estado == EstadoPedidoLocal.pendiente) return true;
      if (p.estado == EstadoPedidoLocal.enviando) {
        final ultimo = p.ultimoIntentoEn;
        return ultimo == null || ahora.difference(ultimo) > huerfano;
      }
      return false;
    }).toList();
    candidatos.sort((a, b) => a.creadoEn.compareTo(b.creadoEn));
    return candidatos;
  }

  /// Antes de enviar: pasa el pedido a `enviando`, suma un intento y anota la hora. Devuelve false si ya no se puede
  /// enviar (se descartó o ya tiene un resultado).
  Future<bool> marcarEnviando(String operacionId, DateTime ahora) {
    return _db.transaction((txn) async {
      final filas = await txn.query(
        'cli_pedido',
        where: 'empresa_id = ? AND usuario_id = ? AND operacion_id = ?',
        whereArgs: [_e, _u, operacionId],
      );
      if (filas.isEmpty) return false;
      final actual = PedidoSinConexion.desdeFila(filas.first);
      if (!actual.estado.sinEnviar) return false;
      await txn.update(
        'cli_pedido',
        {
          'estado': EstadoPedidoLocal.enviando.name,
          'intentos': actual.intentos + 1,
          'ultimo_intento_en': ahora.toUtc().toIso8601String(),
        },
        where: 'empresa_id = ? AND usuario_id = ? AND operacion_id = ?',
        whereArgs: [_e, _u, operacionId],
      );
      return true;
    });
  }

  /// Cambia SOLO las columnas permitidas ([columnasModificablesPedido]) de un pedido mío. `cobrado`, `rechazado` y
  /// `vencido` son finales: cambiarles el estado es un error (la misma respuesta repetida no cambia nada). Ningún camino
  /// lo borra.
  Future<void> actualizarPedido(String operacionId, Map<String, Object?> cambios) async {
    final invalidas = cambios.keys.where((k) => !columnasModificablesPedido.contains(k));
    if (invalidas.isNotEmpty) throw ArgumentError('Columnas no modificables: ${invalidas.join(', ')}');
    return _db.transaction((txn) async {
      final filas = await txn.query(
        'cli_pedido',
        where: 'empresa_id = ? AND usuario_id = ? AND operacion_id = ?',
        whereArgs: [_e, _u, operacionId],
      );
      if (filas.isEmpty) throw StateError('No existe ese pedido en este teléfono.');
      final actual = PedidoSinConexion.desdeFila(filas.first);
      final nuevo = cambios['estado'];
      if (nuevo != null && nuevo != actual.estado.name && actual.estado.esFinal) {
        throw StateError('Un pedido ${actual.estado.name} ya no puede cambiar de estado.');
      }
      if (cambios.isEmpty) return;
      await txn.update(
        'cli_pedido',
        cambios,
        where: 'empresa_id = ? AND usuario_id = ? AND operacion_id = ?',
        whereArgs: [_e, _u, operacionId],
      );
    });
  }

  /// Quita un pedido que todavía no salió (`pendiente`) o que venció. Devuelve false si no existe, si ya se está enviando
  /// o si ya está cobrado o rechazado.
  Future<bool> descartarPedido(String operacionId) {
    return _db.transaction((txn) async {
      final filas = await txn.query(
        'cli_pedido',
        where: 'empresa_id = ? AND usuario_id = ? AND operacion_id = ?',
        whereArgs: [_e, _u, operacionId],
      );
      if (filas.isEmpty) return false;
      final actual = PedidoSinConexion.desdeFila(filas.first);
      if (actual.estado != EstadoPedidoLocal.pendiente && actual.estado != EstadoPedidoLocal.vencido) return false;
      await txn.delete(
        'cli_pedido',
        where: 'empresa_id = ? AND usuario_id = ? AND operacion_id = ?',
        whereArgs: [_e, _u, operacionId],
      );
      return true;
    });
  }

  /// Marca como vistos los pedidos ya resueltos (cobrados, rechazados o vencidos).
  Future<void> marcarVistos() async {
    await _db.update(
      'cli_pedido',
      {'visto': 1},
      where: "empresa_id = ? AND usuario_id = ? AND visto = 0 AND estado IN ('cobrado', 'rechazado', 'vencido')",
      whereArgs: [_e, _u],
    );
  }

  // ---- Cerrar sesión -------------------------------------------------------------------------------------------------

  /// Al cerrar sesión borra el carrito local, lo recordado (método de pago) y los pedidos ya resueltos o vencidos. Los
  /// pedidos que todavía NO se cobraron (`pendiente` y `enviando`) se CONSERVAN: son compras que el cliente ya aceptó y no
  /// se pueden perder; no llevan datos personales y solo se ven y se envían cuando la misma cuenta vuelve a entrar.
  Future<void> vaciarAlCerrarSesion() {
    return _db.transaction((txn) async {
      await txn.delete('cli_meta', where: 'empresa_id = ? AND usuario_id = ?', whereArgs: [_e, _u]);
      await _vaciarCarrito(txn);
      await txn.delete(
        'cli_pedido',
        where: "empresa_id = ? AND usuario_id = ? AND estado IN ('cobrado', 'rechazado', 'vencido')",
        whereArgs: [_e, _u],
      );
    });
  }

  /// "Borrarlos y salir": quita todo lo de esta persona en este teléfono (también los pedidos sin enviar). Es lo único que
  /// borra pedidos sin cobrar, y solo se llama porque la persona lo eligió.
  Future<void> borrarTodo() {
    return _db.transaction((txn) async {
      await txn.delete('cli_meta', where: 'empresa_id = ? AND usuario_id = ?', whereArgs: [_e, _u]);
      await _vaciarCarrito(txn);
      await txn.delete('cli_pedido', where: 'empresa_id = ? AND usuario_id = ?', whereArgs: [_e, _u]);
    });
  }

  void _exigirMio(int empresaId, int usuarioId) {
    if (empresaId != _e || usuarioId != _u) {
      throw StateError('El dato no corresponde a la empresa y el usuario de esta sesión.');
    }
  }
}
