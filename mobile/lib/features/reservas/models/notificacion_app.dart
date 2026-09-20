import '../../../core/utils/fecha_servidor.dart';

class NotificacionApp {
  const NotificacionApp({
    required this.id,
    required this.titulo,
    required this.mensaje,
    required this.tipo,
    required this.referenciaId,
    required this.leida,
    required this.creadoEn,
  });

  factory NotificacionApp.fromJson(Map<String, dynamic> json) => NotificacionApp(
    id: json['id'] as int,
    titulo: json['titulo'] as String,
    mensaje: json['mensaje'] as String?,
    tipo: json['tipo'] as String?,
    referenciaId: json['referencia_id'] as int?,
    leida: json['leida'] as bool,
    creadoEn: fechaDelServidor(json['creado_en'] as String),
  );

  final int id;
  final String titulo;
  final String? mensaje;
  final String? tipo;
  final int? referenciaId;
  final bool leida;
  final DateTime creadoEn;

  NotificacionApp conLeida(bool valor) => NotificacionApp(
    id: id,
    titulo: titulo,
    mensaje: mensaje,
    tipo: tipo,
    referenciaId: referenciaId,
    leida: valor,
    creadoEn: creadoEn,
  );
}
