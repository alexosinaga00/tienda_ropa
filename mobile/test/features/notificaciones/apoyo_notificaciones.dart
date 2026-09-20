import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';
import 'package:mobile/features/reservas/data/notificaciones_repository.dart';
import 'package:mobile/features/reservas/models/notificacion_app.dart';
import 'package:mobile/features/reservas/state/reservas_providers.dart' show notificacionesRepositoryProvider;

NotificacionApp notificacion(
  int id, {
  String titulo = 'Aviso',
  String? mensaje,
  String? tipo,
  int? referenciaId,
  bool leida = false,
  Duration hace = const Duration(minutes: 5),
}) => NotificacionApp(
  id: id,
  titulo: titulo,
  mensaje: mensaje,
  tipo: tipo,
  referenciaId: referenciaId,
  leida: leida,
  creadoEn: DateTime.now().subtract(hace),
);

/// El backend en pequeño: guarda las notificaciones, marca como leídas y puede fallar a pedido.
class RepositorioNotificacionesFalso extends NotificacionesRepository {
  RepositorioNotificacionesFalso(this.servidor) : super(Dio());

  List<NotificacionApp> servidor;
  final List<int> marcadas = [];
  int consultas = 0;
  bool fallaListar = false;
  bool fallaMarcar = false;

  @override
  Future<List<NotificacionApp>> listar() async {
    consultas++;
    if (fallaListar) throw Exception('sin red');
    return List.of(servidor);
  }

  @override
  Future<NotificacionApp> marcarLeida(int id) async {
    if (fallaMarcar) throw Exception('sin red');
    marcadas.add(id);
    servidor = [for (final n in servidor) n.id == id ? n.conLeida(true) : n];
    return servidor.firstWhere((n) => n.id == id);
  }
}

/// Un AuthController que no habla con el backend: la sesión se cambia a mano con [poner].
class AuthFalso extends AuthController {
  AuthFalso(super.ref, {bool autenticado = true}) {
    poner(autenticado);
  }

  void poner(bool autenticado) {
    state = AuthState(estado: autenticado ? EstadoSesion.autenticado : EstadoSesion.noAutenticado);
  }
}

List<Override> overridesNotificaciones(RepositorioNotificacionesFalso repositorio, {bool autenticado = true}) => [
  notificacionesRepositoryProvider.overrideWithValue(repositorio),
  authControllerProvider.overrideWith((ref) => AuthFalso(ref, autenticado: autenticado)),
];
