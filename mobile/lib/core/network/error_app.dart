import 'dart:io';

import 'package:dio/dio.dart';

/// Los códigos funcionales que manda el backend (`ErrorFuncional`: `{detail, codigo, mensaje, ...}`).
const codigoPlanNoIncluye = 'plan_no_incluye_funcionalidad';
const codigoSuscripcionNoActiva = 'suscripcion_no_activa';
const codigoLimitePlan = 'limite_plan_excedido';

const _mensajePlanNoIncluye = 'Tu plan no incluye esta función. Consulta con el administrador de tu empresa.';
const _mensajeSuscripcionNoActiva =
    'La suscripción de esta tienda no está activa. Contacta al administrador de la tienda.';
const _mensajeLimitePlan = 'Tu empresa alcanzó el límite de su plan.';
const _mensajeSinConexion = 'Sin conexión. Revisa tu internet e intenta de nuevo.';

enum TipoErrorApp {
  sinConexion,
  noAutorizado,
  prohibido,
  planNoIncluyeFuncionalidad,
  suscripcionNoActiva,
  limitePlanExcedido,
  noEncontrado,
  conflicto,
  validacion,
  servidor,
  desconocido,
}

/// El único error que sale de [ApiClient]: ya traducido a un tipo, con un mensaje en español y sin tecnicismos.
class ErrorApp implements Exception {
  const ErrorApp({
    required this.tipo,
    required this.mensaje,
    this.estado,
    this.codigo,
    this.detalle,
    this.posiblementeRecibido = false,
    this.reintentarDespues,
  });

  final TipoErrorApp tipo;

  /// Lo que el servidor pidió esperar (cabecera `Retry-After`, p. ej. en un 429), si la mandó y se entendió.
  final Duration? reintentarDespues;

  /// La petición pudo haber LLEGADO al servidor aunque no hubo respuesta (se cortó al enviar o al esperar). Con `false` es
  /// seguro que no llegó. Importa para reenviar: una operación con id único se puede reenviar sin duplicarse, pero hay que
  /// saber que "no llegó" no es lo mismo que "no sabemos".
  final bool posiblementeRecibido;

  /// Código HTTP, si el servidor llegó a responder.
  final int? estado;

  /// Código funcional del backend (p. ej. `limite_plan_excedido`), si lo mandó.
  final String? codigo;

  /// Lo que se le puede mostrar a la persona.
  final String mensaje;

  /// El texto de `detail` tal como lo mandó el backend (para quien prefiera su propio mensaje por defecto).
  final String? detalle;

  /// Un error funcional del plan o de la suscripción: tiene un mensaje fijo, igual en toda la app.
  bool get esFuncional =>
      tipo == TipoErrorApp.planNoIncluyeFuncionalidad ||
      tipo == TipoErrorApp.suscripcionNoActiva ||
      tipo == TipoErrorApp.limitePlanExcedido;

  /// Traduce cualquier excepción. Un [ErrorApp] se devuelve tal cual.
  factory ErrorApp.desde(Object error) {
    if (error is ErrorApp) return error;
    if (error is! DioException) {
      return const ErrorApp(tipo: TipoErrorApp.desconocido, mensaje: 'Ocurrió un error inesperado. Intenta de nuevo.');
    }

    final respuesta = error.response;
    if (respuesta == null) {
      final sinRed = switch (error.type) {
        DioExceptionType.connectionError ||
        DioExceptionType.connectionTimeout ||
        DioExceptionType.sendTimeout ||
        DioExceptionType.receiveTimeout => true,
        _ => error.error is SocketException,
      };
      // Pudo haber llegado: se cortó al ENVIAR o al ESPERAR la respuesta, o falló la red a mitad de camino. Un error al
      // CONECTAR (connectionError / connectionTimeout) en cambio asegura que nunca llegó.
      final posiblementeRecibido = switch (error.type) {
        DioExceptionType.connectionError || DioExceptionType.connectionTimeout => false,
        _ => true,
      };
      return sinRed
          ? ErrorApp(
              tipo: TipoErrorApp.sinConexion,
              mensaje: _mensajeSinConexion,
              posiblementeRecibido: posiblementeRecibido,
            )
          : const ErrorApp(tipo: TipoErrorApp.desconocido, mensaje: 'Ocurrió un error inesperado. Intenta de nuevo.');
    }

    final estado = respuesta.statusCode ?? 0;
    final datos = respuesta.data;
    final detail = datos is Map ? datos['detail'] : null;
    final detalleTexto = detail is String && detail.isNotEmpty ? detail : null;
    final codigoMapa = datos is Map ? datos['codigo'] : null;
    final mensajeMapa = datos is Map ? datos['mensaje'] : null;

    // El código puede venir en `codigo` o ser el propio `detail`.
    final codigo = codigoMapa is String && codigoMapa.isNotEmpty
        ? codigoMapa
        : (detalleTexto != null && _funcionales.contains(detalleTexto) ? detalleTexto : null);
    final textoBackend = mensajeMapa is String && mensajeMapa.isNotEmpty ? mensajeMapa : detalleTexto;

    TipoErrorApp tipo;
    if (codigo == codigoPlanNoIncluye) {
      tipo = TipoErrorApp.planNoIncluyeFuncionalidad;
    } else if (codigo == codigoSuscripcionNoActiva) {
      tipo = TipoErrorApp.suscripcionNoActiva;
    } else if (codigo == codigoLimitePlan) {
      tipo = TipoErrorApp.limitePlanExcedido;
    } else if (estado == 401) {
      tipo = TipoErrorApp.noAutorizado;
    } else if (estado == 403) {
      tipo = TipoErrorApp.prohibido;
    } else if (estado == 404) {
      tipo = TipoErrorApp.noEncontrado;
    } else if (estado == 409) {
      tipo = TipoErrorApp.conflicto;
    } else if (estado == 422) {
      tipo = TipoErrorApp.validacion;
    } else if (estado >= 500) {
      tipo = TipoErrorApp.servidor;
    } else {
      tipo = TipoErrorApp.desconocido;
    }

    final mensaje = switch (tipo) {
      TipoErrorApp.planNoIncluyeFuncionalidad => _mensajePlanNoIncluye,
      TipoErrorApp.suscripcionNoActiva => _mensajeSuscripcionNoActiva,
      TipoErrorApp.limitePlanExcedido => _mensajeLimitePlan,
      TipoErrorApp.noAutorizado => 'Tu sesión venció. Inicia sesión de nuevo.',
      TipoErrorApp.prohibido => textoBackend ?? 'No tienes permiso para hacer esto.',
      TipoErrorApp.noEncontrado => textoBackend ?? 'No encontramos lo que buscabas.',
      TipoErrorApp.conflicto => textoBackend ?? 'La operación no se pudo completar. Intenta de nuevo.',
      // En un 422 `detail` suele ser la lista técnica de campos: no se muestra.
      TipoErrorApp.validacion => 'Revisa los datos e intenta de nuevo.',
      TipoErrorApp.servidor => 'El servidor no pudo responder. Intenta de nuevo en unos minutos.',
      _ => textoBackend ?? 'Ocurrió un error inesperado. Intenta de nuevo.',
    };

    return ErrorApp(
      tipo: tipo,
      estado: estado,
      codigo: codigo,
      mensaje: mensaje,
      detalle: detalleTexto,
      reintentarDespues: _leerRetryAfter(respuesta.headers.value('retry-after')),
    );
  }

  /// `Retry-After` en segundos ("30"). Una fecha HTTP o un valor ilegible se ignoran (el llamador usa su propia espera).
  /// Se acota a 1 hora para que un valor absurdo no deje un pedido dormido.
  static Duration? _leerRetryAfter(String? valor) {
    final segundos = int.tryParse(valor?.trim() ?? '');
    if (segundos == null || segundos < 0) return null;
    return Duration(seconds: segundos > 3600 ? 3600 : segundos);
  }

  @override
  String toString() => 'ErrorApp($tipo, estado: $estado, codigo: $codigo)';
}

const _funcionales = {codigoPlanNoIncluye, codigoSuscripcionNoActiva, codigoLimitePlan};
