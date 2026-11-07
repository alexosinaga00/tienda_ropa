/// Migraciones de la base local del cliente: versión destino → sentencias que la construyen a partir de la anterior.
///
/// Una versión nueva se AGREGA aquí (y se sube `versionEsquemaCliente`); jamás se edita el DDL de `esquema_cliente.dart`.
/// Las migraciones no pueden borrar pedidos sin enviar: un pedido en cola es una compra que la persona ya aceptó.
/// Hoy solo existe la versión 1, que se crea completa en `onCreate`.
const Map<int, List<String>> migracionesCliente = {};
