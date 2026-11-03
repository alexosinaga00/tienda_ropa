import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../features/auth/models/usuario.dart';
import '../../features/auth/state/auth_controller.dart';
import '../../features/vendedor/state/sincronizacion_providers.dart';
import '../conectividad/conectividad_service.dart';
import '../router/app_router.dart';
import 'motor_sincronizacion.dart';
import 'operacion_pendiente.dart';

/// Para mostrar un aviso desde fuera de cualquier pantalla (el resultado de una sincronización automática).
final GlobalKey<ScaffoldMessengerState> mensajeroGlobal = GlobalKey<ScaffoldMessengerState>();

/// Cuánto se espera tras volver la conexión antes de sincronizar (la red recién vuelta suele ser inestable).
const esperaTrasRecuperarConexion = Duration(seconds: 3);

/// Cada cuánto se reintenta mientras haya pendientes y la app esté abierta (el motor respeta la espera de cada operación).
const intervaloTemporizador = Duration(seconds: 60);

/// El texto del aviso tras una sincronización AUTOMÁTICA, o null si no hay nada que decir.
String? textoDelResumen(ResumenSync resumen) {
  if (!resumen.intentado || !resumen.huboCambios) return null;
  final atencion = resumen.rechazadas + resumen.enConflicto;
  if (atencion > 0) {
    return atencion == 1 ? '1 operación necesita atención' : '$atencion operaciones necesitan atención';
  }
  if (resumen.confirmadas > 0) {
    return resumen.confirmadas == 1 ? '1 operación sincronizada' : '${resumen.confirmadas} operaciones sincronizadas';
  }
  return null;
}

/// Dispara la sincronización sin que la persona haga nada. Solo actúa con una sesión del personal. Cinco disparadores:
/// (a) la conexión pasa de sin red a en línea (con una espera de 3 s), (b) la app vuelve al primer plano, (c) se registra una
/// operación nueva, (d) cada 60 s mientras haya pendientes. El botón "Sincronizar ahora" es el quinto, manual, y vive en la
/// pantalla de operaciones. Todos comparten el candado del motor: un disparo durante otra sincronización no hace otra petición.
///
/// NO se usa WorkManager (sincronizar con la app cerrada): exige un plugin y repetir la inicialización de la base, el
/// almacenamiento seguro y el refresh en un aislado aparte, y Android limita esas tareas a 15 minutos. El examen pide sincronizar
/// "al restablecerse Internet", que esto cumple con la app abierta o recién pasada a segundo plano.
class DisparadorSincronizacion extends ConsumerStatefulWidget {
  const DisparadorSincronizacion({
    super.key,
    required this.child,
    this.esperaConexion = esperaTrasRecuperarConexion,
    this.intervalo = intervaloTemporizador,
  });

  final Widget child;
  final Duration esperaConexion;
  final Duration intervalo;

  @override
  ConsumerState<DisparadorSincronizacion> createState() => _DisparadorSincronizacionState();
}

class _DisparadorSincronizacionState extends ConsumerState<DisparadorSincronizacion> with WidgetsBindingObserver {
  Timer? _esperaConexion;
  Timer? _temporizador;
  int _registradasAntes = 0;

  bool get _activo {
    final auth = ref.read(authControllerProvider);
    return auth.estaAutenticado && auth.usuario?.modo == ModoApp.vendedor;
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _temporizador = Timer.periodic(widget.intervalo, (_) => _alTemporizador());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _esperaConexion?.cancel();
    _temporizador?.cancel();
    super.dispose();
  }

  // (b) La app vuelve al primer plano.
  @override
  void didChangeAppLifecycleState(AppLifecycleState estado) {
    if (estado == AppLifecycleState.resumed) unawaited(_disparar(Disparador.primerPlano));
  }

  // (d) Mientras haya pendientes y la app esté abierta.
  void _alTemporizador() {
    if (!_activo) return;
    final conteo = ref.read(conteoOperacionesProvider).valueOrNull;
    if (conteo == null || porEnviar(conteo) == 0) return;
    unawaited(_disparar(Disparador.temporizador));
  }

  Future<void> _disparar(Disparador disparador) async {
    if (!mounted || !_activo) return;
    try {
      final resumen = await sincronizarAhora(ref, disparador: disparador);
      if (resumen != null) _avisar(resumen);
    } catch (_) {
      // Sincronizar de forma automática nunca debe tumbar la app: la cola se conserva y se reintenta.
    }
  }

  void _avisar(ResumenSync resumen) {
    final texto = textoDelResumen(resumen);
    final mensajero = mensajeroGlobal.currentState;
    if (texto == null || mensajero == null) return;
    final necesitaAtencion = resumen.rechazadas + resumen.enConflicto > 0;
    mensajero
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text(texto),
          action: necesitaAtencion
              ? SnackBarAction(
                  label: 'Ver',
                  onPressed: () => unawaited(ref.read(routerProvider).push('/vendedor/operaciones')),
                )
              : null,
        ),
      );
  }

  @override
  Widget build(BuildContext context) {
    // (a) La conexión vuelve: se espera unos segundos y se sincroniza.
    ref.listen<AsyncValue<bool>>(enLineaProvider, (anterior, actual) {
      if (actual.valueOrNull != true || anterior?.valueOrNull != false) return;
      _esperaConexion?.cancel();
      _esperaConexion = Timer(widget.esperaConexion, () => unawaited(_disparar(Disparador.conexionRecuperada)));
    });

    // (c) Se registró una operación nueva: sube la cantidad de 'registrada'.
    ref.listen<AsyncValue<Map<EstadoOperacion, int>>>(conteoOperacionesProvider, (anterior, actual) {
      final registradas = actual.valueOrNull?[EstadoOperacion.registrada] ?? 0;
      final subio = registradas > _registradasAntes;
      _registradasAntes = registradas;
      if (subio) unawaited(_disparar(Disparador.registro));
    });

    // Al entrar o salir de una sesión del personal se reinicia la cuenta de "nuevas".
    ref.listen(authControllerProvider.select((s) => s.usuario?.id), (_, _) => _registradasAntes = 0);

    return widget.child;
  }
}
