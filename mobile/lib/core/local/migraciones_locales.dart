/// Migraciones de la base local: versión destino → sentencias que la construyen a partir de la anterior.
///
/// Una versión nueva se AGREGA aquí (y se sube `versionEsquemaLocal`); jamás se edita el DDL de `esquema_local.dart`.
/// Las migraciones no pueden borrar datos de operaciones pendientes: una venta sin enviar es trabajo de una persona.
/// Hoy solo existe la versión 1, que se crea completa en `onCreate`.
const Map<int, List<String>> migracionesLocales = {};
