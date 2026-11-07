import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Un aviso push ya entendido: lo que el servidor manda en `notification` (título y cuerpo) y en `data` (tipo, referencia
/// y notificación, todos como texto).
class AvisoPush {
  const AvisoPush({this.tipo, this.referenciaId, this.notificacionId, this.titulo, this.cuerpo});

  /// Arma el aviso con el `data` del mensaje (valores en texto; un número ilegible queda en null).
  factory AvisoPush.desdeDatos(Map<String, dynamic> datos, {String? titulo, String? cuerpo}) {
    String? texto(String clave) {
      final valor = datos[clave];
      if (valor == null) return null;
      final limpio = valor.toString().trim();
      return limpio.isEmpty ? null : limpio;
    }

    final referencia = texto('referencia_id');
    final notificacion = texto('notificacion_id');
    return AvisoPush(
      tipo: texto('tipo'),
      referenciaId: referencia == null ? null : int.tryParse(referencia),
      notificacionId: notificacion == null ? null : int.tryParse(notificacion),
      titulo: titulo,
      cuerpo: cuerpo,
    );
  }

  final String? tipo;
  final int? referenciaId;
  final int? notificacionId;
  final String? titulo;
  final String? cuerpo;
}

/// La puerta a las notificaciones push del sistema (Firebase Cloud Messaging). Es la interfaz que el resto de la app usa
/// y que las pruebas reemplazan por un falso: ninguna pantalla ni caso de uso conoce a Firebase.
///
/// NINGÚN método lanza: si Firebase no está disponible (sin Play Services, sin configuración) cada uno responde "no hay
/// nada" y la app sigue igual.
abstract interface class ServicioPush {
  /// Prepara el servicio (inicia Firebase y se suscribe a los mensajes). Seguro de llamar varias veces. Si la app se abrió
  /// tocando un aviso con la app cerrada, ese aviso sale por [alAbrirAviso] al terminar.
  Future<void> iniciar();

  /// Si la persona ya concedió el permiso de notificaciones (en Android 12 o menos viene concedido). No pregunta nada.
  Future<bool> permisoConcedido();

  /// Pide el permiso de notificaciones (Android 13+ muestra el diálogo del sistema). Devuelve si quedó concedido.
  Future<bool> solicitarPermiso();

  /// El token de este dispositivo, o null si no hay (sin permiso, sin Firebase o sin red la primera vez).
  Future<String?> obtenerToken();

  /// Cada vez que Firebase cambia el token del dispositivo.
  Stream<String> get alRefrescarToken;

  /// La persona tocó un aviso del sistema (con la app en segundo plano o cerrada).
  Stream<AvisoPush> get alAbrirAviso;

  /// Llegó un aviso con la app abierta (Android no lo muestra solo).
  Stream<AvisoPush> get alRecibirEnPrimerPlano;
}

/// El servicio por defecto: no hace nada. `main.dart` lo reemplaza por el real, así las pruebas y cualquier contenedor sin
/// configurar nunca tocan Firebase.
class ServicioPushInactivo implements ServicioPush {
  const ServicioPushInactivo();

  @override
  Future<void> iniciar() async {}

  @override
  Future<bool> permisoConcedido() async => false;

  @override
  Future<bool> solicitarPermiso() async => false;

  @override
  Future<String?> obtenerToken() async => null;

  @override
  Stream<String> get alRefrescarToken => const Stream<String>.empty();

  @override
  Stream<AvisoPush> get alAbrirAviso => const Stream<AvisoPush>.empty();

  @override
  Stream<AvisoPush> get alRecibirEnPrimerPlano => const Stream<AvisoPush>.empty();
}

final servicioPushProvider = Provider<ServicioPush>((ref) => const ServicioPushInactivo());
