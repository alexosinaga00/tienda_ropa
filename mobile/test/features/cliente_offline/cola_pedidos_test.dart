import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/cliente_offline/config/cliente_offline_config.dart';
import 'package:mobile/features/cliente_offline/models/pedido_diferido_api.dart';
import 'package:mobile/features/cliente_offline/models/pedido_sin_conexion.dart';
import 'package:mobile/features/cliente_offline/state/cola_pedidos.dart';

import '../../helpers/cliente_offline_apoyo.dart';

/// Deja que la cola termine todos sus ciclos y entrega los avisos pendientes.
Future<void> asentar(MundoCola m) async {
  await m.cola.esperarCiclos();
  await Future<void>.delayed(Duration.zero);
}

/// Un ciclo completo: dispara y espera.
Future<void> enviar(MundoCola m, {bool manual = false}) async {
  await m.cola.procesar(manual: manual);
  await asentar(m);
}

/// Espera (con la base real en un hilo aparte) a que se cumpla [condicion].
Future<void> esperarHasta(bool Function() condicion) async {
  for (var i = 0; i < 400 && !condicion(); i++) {
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
  expect(condicion(), isTrue, reason: 'no se cumplió la condición a tiempo');
}

void main() {
  late MundoCola m;

  setUp(() async {
    m = await MundoCola.crear();
  });

  tearDown(() async {
    m.cola.dispose();
    await m.db.close();
  });

  group('envío correcto', () {
    test('manda el pedido con su operacion_id, el tope en texto y la fecha en UTC, y guarda lo cobrado', () async {
      await m.sembrar(pedidoDePrueba());

      await enviar(m);

      expect(m.api.enviados, hasLength(1));
      final cuerpo = m.api.enviados.single.toJson();
      expect(cuerpo['operacion_id'], idOperacion(1));
      expect(cuerpo['sucursal_id'], 3);
      expect(cuerpo['costo_envio'], '0.00');
      expect(cuerpo['lineas'], [
        {'variante_id': 10, 'cantidad': 2},
      ]);
      expect(cuerpo['total_maximo'], '398.00');
      expect(cuerpo['fecha_pedido'], endsWith('Z'));
      expect(cuerpo.keys.toSet(), {
        'operacion_id',
        'sucursal_id',
        'costo_envio',
        'lineas',
        'total_maximo',
        'fecha_pedido',
      });

      final p = await m.pedido(1);
      expect(p.estado, EstadoPedidoLocal.cobrado);
      expect(p.ventaId, 55);
      expect(p.codigoVenta, 'V-0055');
      expect(p.totalCentavos, 39800);
      expect(p.totalUsd, '57.18');
      expect(p.intentos, 1);
      expect(p.visto, isFalse);
      expect(m.cola.estado.fase, FaseCola.inactiva);
      expect(m.resueltos.map((r) => r.codigoVenta), ['V-0055']);
    });

    test('un pedido cobrado no se vuelve a enviar nunca', () async {
      await m.sembrar(pedidoDePrueba());
      await enviar(m);

      await enviar(m);
      await enviar(m, manual: true);

      expect(m.api.enviados, hasLength(1));
    });

    test('un rechazo del servidor se guarda con su motivo y su mensaje, y es final', () async {
      await m.sembrar(pedidoDePrueba());
      m.api.responder(respuestaRechazada(idOperacion(1), 'stock_insuficiente', mensaje: 'Ya no queda esa talla.'));

      await enviar(m);

      final p = await m.pedido(1);
      expect(p.estado, EstadoPedidoLocal.rechazado);
      expect(p.motivo, 'stock_insuficiente');
      expect(p.mensaje, 'Ya no queda esa talla.');
      expect(p.ventaId, isNull);
      expect(m.resueltos.single.estado, EstadoPedidoLocal.rechazado);
      await enviar(m, manual: true);
      expect(m.api.enviados, hasLength(1), reason: 'un rechazo es final: no se reabre');
    });

    test('sin_metodo_pago avisa para que se olvide el PayPal recordado', () async {
      await m.sembrar(pedidoDePrueba());
      m.api.responder(respuestaRechazada(idOperacion(1), motivoSinMetodoPago));

      await enviar(m);

      expect(m.vecesSinMetodoPago, 1);
    });

    test('el motivo pedido_vencido del servidor se muestra con el mensaje amable', () async {
      await m.sembrar(pedidoDePrueba());
      m.api.responder(respuestaRechazada(idOperacion(1), motivoPedidoVencido, mensaje: 'texto técnico'));

      await enviar(m);

      final p = await m.pedido(1);
      expect(p.estado, EstadoPedidoLocal.rechazado);
      expect(p.mensaje, mensajePedidoVencidoServidor);
      expect(p.mensaje, contains('7 días'));
    });
  });

  group('fallos temporales: se reintenta con la MISMA operacion_id', () {
    test('503: vuelve a pendiente con espera, y el reintento usa la misma operacion_id y no duplica', () async {
      await m.sembrar(pedidoDePrueba());
      m.api
        ..responder(errorHttp(503, codigo: 'paypal_no_disponible'))
        ..responder(respuestaCobrada(idOperacion(1)));

      await enviar(m);

      var p = await m.pedido(1);
      expect(p.estado, EstadoPedidoLocal.pendiente);
      expect(p.ultimoError, 'paypal_no_disponible');
      expect(p.intentos, 1);
      expect(p.proximoIntentoEn, m.reloj.actual.add(const Duration(seconds: 10)));
      expect(m.cola.estado.fase, FaseCola.esperandoReintento);
      expect(m.temporizador.activos, 1);
      expect(m.temporizador.ultimaEspera, const Duration(seconds: 10, milliseconds: 25));

      // El temporizador despierta cuando ya pasó la espera.
      m.reloj.avanzar(const Duration(seconds: 11));
      m.temporizador.dispararUltimo();
      await asentar(m);

      p = await m.pedido(1);
      expect(p.estado, EstadoPedidoLocal.cobrado);
      expect(p.intentos, 2);
      expect(m.api.idsEnviados, [idOperacion(1), idOperacion(1)]);
      expect(m.cola.estado.fase, FaseCola.inactiva);
    });

    test('un disparo automático ANTES de que termine la espera no envía', () async {
      await m.sembrar(pedidoDePrueba());
      m.api
        ..responder(errorHttp(500))
        ..responder(respuestaCobrada(idOperacion(1)));
      await enviar(m);
      expect(m.api.enviados, hasLength(1));

      m.reloj.avanzar(const Duration(seconds: 3));
      await enviar(m);

      expect(m.api.enviados, hasLength(1), reason: 'todavía falta espera');
      expect((await m.pedido(1)).estado, EstadoPedidoLocal.pendiente);
      expect(m.cola.estado.fase, FaseCola.esperandoReintento);
    });

    test('"Enviar ahora" ignora la espera', () async {
      await m.sembrar(pedidoDePrueba());
      m.api
        ..responder(errorHttp(500))
        ..responder(respuestaCobrada(idOperacion(1)));
      await enviar(m);

      await enviar(m, manual: true);

      expect(m.api.enviados, hasLength(2));
      expect((await m.pedido(1)).estado, EstadoPedidoLocal.cobrado);
    });

    test('429 respeta Retry-After', () async {
      await m.sembrar(pedidoDePrueba());
      m.api.responder(errorHttp(429, reintentar: const Duration(seconds: 90)));

      await enviar(m);

      final p = await m.pedido(1);
      expect(p.estado, EstadoPedidoLocal.pendiente);
      expect(p.ultimoError, 'http_429');
      expect(p.proximoIntentoEn, m.reloj.actual.add(const Duration(seconds: 90)));
      expect(m.temporizador.ultimaEspera, const Duration(seconds: 90, milliseconds: 25));
    });

    test('la espera crece con cada fallo seguido', () async {
      await m.sembrar(pedidoDePrueba());
      m.api.responder(errorHttp(500));

      await enviar(m);
      expect(m.temporizador.ultimaEspera, const Duration(seconds: 10, milliseconds: 25));
      m.reloj.avanzar(const Duration(seconds: 11));
      await enviar(m);
      expect(m.temporizador.ultimaEspera, const Duration(seconds: 20, milliseconds: 25));
      m.reloj.avanzar(const Duration(seconds: 21));
      await enviar(m);
      expect(m.temporizador.ultimaEspera, const Duration(seconds: 30, milliseconds: 25));
    });

    test('tiempo agotado: vuelve a pendiente con la misma operacion_id', () async {
      m.cola.dispose();
      m.cola = m.nuevaCola(tiempoLimite: const Duration(milliseconds: 40));
      await m.sembrar(pedidoDePrueba());
      m.api.responder((PedidoDiferidoCrear _) => Completer<PedidoDiferidoRespuesta>().future);

      await enviar(m);

      final p = await m.pedido(1);
      expect(p.estado, EstadoPedidoLocal.pendiente);
      expect(p.ultimoError, 'timeout');
      expect(p.intentos, 1);
    });

    test('un fallo de red con la conexión aún en pie reintenta con espera', () async {
      await m.sembrar(pedidoDePrueba());
      m.api.responder(errorSinRed);

      await enviar(m);

      final p = await m.pedido(1);
      expect(p.estado, EstadoPedidoLocal.pendiente);
      expect(p.ultimoError, 'sin_conexion');
      expect(p.proximoIntentoEn, isNotNull);
      expect(m.cola.estado.fase, FaseCola.esperandoReintento);
    });

    test('una respuesta que no se entiende se trata como fallo temporal, no como decisión', () async {
      await m.sembrar(pedidoDePrueba());
      m.api.responder(errorHttp(200));

      await enviar(m);

      final p = await m.pedido(1);
      expect(p.estado, EstadoPedidoLocal.pendiente);
      expect(p.ultimoError, 'http_200');
    });

    test('tras 8 fallos seguidos se detiene y espera el botón "Reintentar"', () async {
      m.cola.dispose();
      m.cola = m.nuevaCola(espera: (_) => Duration.zero);
      await m.sembrar(pedidoDePrueba());
      m.api.responder(errorHttp(500));

      for (var i = 1; i < fallosAutomaticosMax; i++) {
        await enviar(m);
        expect(m.cola.estado.fase, FaseCola.esperandoReintento, reason: 'fallo $i');
      }
      await enviar(m);

      expect(m.api.enviados, hasLength(fallosAutomaticosMax));
      expect(m.cola.estado.fase, FaseCola.detenidaPorFallos);
      expect(m.cola.estado.motivoPausa, motivoDetenidaPorFallos);
      expect(m.temporizador.activos, 0, reason: 'detenida: no hay reintento programado');
      expect((await m.pedido(1)).estado, EstadoPedidoLocal.pendiente);

      // Los disparos automáticos no insisten...
      await enviar(m);
      m.cola.alVolverConexion();
      await asentar(m);
      expect(m.api.enviados, hasLength(fallosAutomaticosMax + 1), reason: 'volver la red SÍ levanta la detención');

      // ... y "Reintentar" sí.
      await enviar(m, manual: true);
      expect(m.api.enviados, hasLength(fallosAutomaticosMax + 2));
    });
  });

  group('sesión vencida y tienda sin permiso', () {
    test('401 pausa la cola, conserva el pedido y no rechaza nada', () async {
      await m.sembrar(pedidoDePrueba());
      m.api.responder(errorHttp(401));

      await enviar(m);

      final p = await m.pedido(1);
      expect(p.estado, EstadoPedidoLocal.pendiente);
      expect(p.ultimoError, 'sesion_vencida');
      expect(m.cola.estado.fase, FaseCola.pausadaSesion);
      expect(m.cola.estado.motivoPausa, motivoPausadaPorSesion);
      expect(m.temporizador.activos, 0);

      // Ni la red ni "Enviar ahora" levantan una sesión vencida.
      await enviar(m, manual: true);
      m.cola.alVolverConexion();
      await asentar(m);
      expect(m.api.enviados, hasLength(1));
      expect(m.cola.estado.fase, FaseCola.pausadaSesion);
    });

    test('se reanuda cuando la MISMA persona vuelve a iniciar sesión', () async {
      await m.sembrar(pedidoDePrueba());
      m.api
        ..responder(errorHttp(401))
        ..responder(respuestaCobrada(idOperacion(1)));
      m.cola.alCambiarAlcance(alcanceAna);
      await asentar(m);
      expect(m.cola.estado.fase, FaseCola.pausadaSesion);

      // Se cierra la sesión (forzada): la cola sigue pausada.
      m.alcance = null;
      m.cola.alCambiarAlcance(null);
      await asentar(m);
      expect(m.cola.estado.fase, FaseCola.pausadaSesion);

      // La misma persona entra otra vez.
      m.alcance = alcanceAna;
      m.cola.alCambiarAlcance(alcanceAna);
      await asentar(m);

      expect((await m.pedido(1)).estado, EstadoPedidoLocal.cobrado);
      expect(m.api.idsEnviados, [idOperacion(1), idOperacion(1)]);
      expect(m.cola.estado.fase, FaseCola.inactiva);
    });

    test('otra persona que entra NO reanuda ni envía los pedidos de la primera', () async {
      await m.sembrar(pedidoDePrueba());
      m.api.responder(errorHttp(401));
      m.cola.alCambiarAlcance(alcanceAna);
      await asentar(m);

      m.alcance = alcanceLuis;
      m.cola.alCambiarAlcance(alcanceLuis);
      await asentar(m);

      expect(m.api.enviados, hasLength(1), reason: 'Luis no tiene pedidos y los de Ana no son suyos');
      expect(m.cola.estado.fase, FaseCola.inactiva);
      expect((await m.repo(alcanceAna).pedido(idOperacion(1)))!.estado, EstadoPedidoLocal.pendiente);
    });

    test('403 pausa SIN rechazar el pedido, y "Reintentar" lo vuelve a intentar', () async {
      await m.sembrar(pedidoDePrueba());
      m.api
        ..responder(errorHttp(403, codigo: 'suscripcion_no_activa'))
        ..responder(respuestaCobrada(idOperacion(1)));

      await enviar(m);

      final p = await m.pedido(1);
      expect(p.estado, EstadoPedidoLocal.pendiente);
      expect(p.ultimoError, 'suscripcion_no_activa');
      expect(m.cola.estado.fase, FaseCola.pausada);
      expect(m.cola.estado.motivoPausa, contains('no puede recibir pedidos'));

      await enviar(m);
      expect(m.api.enviados, hasLength(1), reason: 'pausada: el temporizador no insiste');

      await enviar(m, manual: true);
      expect((await m.pedido(1)).estado, EstadoPedidoLocal.cobrado);
    });

    test('400 y 422 rechazan localmente con pedido_invalido y siguen con los demás', () async {
      await m.sembrar(pedidoDePrueba(n: 1, creadoEn: DateTime.utc(2026, 11, 6, 9)));
      await m.sembrar(pedidoDePrueba(n: 2, creadoEn: DateTime.utc(2026, 11, 6, 10)));
      await m.sembrar(pedidoDePrueba(n: 3, creadoEn: DateTime.utc(2026, 11, 6, 11)));
      m.api
        ..responder(errorHttp(422))
        ..responder(errorHttp(400))
        ..responder(respuestaCobrada(idOperacion(3)));

      await enviar(m);

      expect(m.api.idsEnviados, [idOperacion(1), idOperacion(2), idOperacion(3)]);
      final p1 = await m.pedido(1);
      expect(p1.estado, EstadoPedidoLocal.rechazado);
      expect(p1.motivo, motivoPedidoInvalido);
      expect(p1.mensaje, mensajePedidoInvalido);
      expect((await m.pedido(2)).motivo, motivoPedidoInvalido);
      expect((await m.pedido(3)).estado, EstadoPedidoLocal.cobrado);
    });
  });

  group('orden y un solo ciclo a la vez', () {
    test('los pedidos salen uno a uno, el más antiguo primero', () async {
      await m.sembrar(pedidoDePrueba(n: 1, creadoEn: DateTime.utc(2026, 11, 6, 11)));
      await m.sembrar(pedidoDePrueba(n: 2, creadoEn: DateTime.utc(2026, 11, 6, 10)));
      await m.sembrar(pedidoDePrueba(n: 3, creadoEn: DateTime.utc(2026, 11, 6, 9)));

      await enviar(m);

      expect(m.api.idsEnviados, [idOperacion(3), idOperacion(2), idOperacion(1)]);
      expect(m.api.maximoSimultaneos, 1);
    });

    test('si el más antiguo falla por algo temporal, los demás esperan su turno', () async {
      await m.sembrar(pedidoDePrueba(n: 1, creadoEn: DateTime.utc(2026, 11, 6, 9)));
      await m.sembrar(pedidoDePrueba(n: 2, creadoEn: DateTime.utc(2026, 11, 6, 10)));
      m.api.responder(errorHttp(503));

      await enviar(m);

      expect(m.api.idsEnviados, [idOperacion(1)]);
      expect((await m.pedido(2)).intentos, 0);
      expect((await m.pedido(2)).estado, EstadoPedidoLocal.pendiente);
    });

    test('un disparo durante un envío NO envía en paralelo: hace otro ciclo al terminar', () async {
      await m.sembrar(pedidoDePrueba(n: 1, creadoEn: DateTime.utc(2026, 11, 6, 9)));
      final compuerta = Completer<PedidoDiferidoRespuesta>();
      m.api
        ..responder((PedidoDiferidoCrear _) => compuerta.future)
        ..responder(respuestaCobrada(idOperacion(2)));

      final primero = m.cola.procesar();
      await esperarHasta(() => m.api.enviados.length == 1);

      // Mientras el primero está en el aire llegan más disparos y un pedido nuevo.
      final segundo = m.cola.procesar();
      final tercero = m.cola.procesar(manual: true);
      await m.sembrar(pedidoDePrueba(n: 2, creadoEn: DateTime.utc(2026, 11, 6, 10)));
      m.cola.alVolverConexion();
      expect(m.api.enviados, hasLength(1), reason: 'sigue habiendo un solo envío');

      compuerta.complete(respuestaCobrada(idOperacion(1)));
      await Future.wait([primero, segundo, tercero]);
      await asentar(m);

      expect(m.api.idsEnviados, [idOperacion(1), idOperacion(2)]);
      expect(m.api.maximoSimultaneos, 1);
      expect((await m.pedido(1)).estado, EstadoPedidoLocal.cobrado);
      expect((await m.pedido(2)).estado, EstadoPedidoLocal.cobrado);
    });

    test('solo se envían los pedidos de la persona de la sesión', () async {
      await m.sembrar(pedidoDePrueba(n: 1, alcance: alcanceAna));
      await m.sembrar(pedidoDePrueba(n: 2, alcance: alcanceLuis));
      await m.sembrar(pedidoDePrueba(n: 3, alcance: alcanceOtraEmpresa));

      await enviar(m);

      expect(m.api.idsEnviados, [idOperacion(1)]);
      expect((await m.repo(alcanceLuis).pedido(idOperacion(2)))!.estado, EstadoPedidoLocal.pendiente);
      expect((await m.repo(alcanceOtraEmpresa).pedido(idOperacion(3)))!.estado, EstadoPedidoLocal.pendiente);
    });

    test('un pedido "enviando" huérfano (más de 120 s) se reenvía; uno reciente no', () async {
      final ahora = m.reloj.actual;
      await m.sembrar(
        pedidoDePrueba(
          n: 1,
          estado: EstadoPedidoLocal.enviando,
          intentos: 1,
          ultimoIntentoEn: ahora.subtract(const Duration(seconds: 121)),
          creadoEn: DateTime.utc(2026, 11, 6, 9),
        ),
      );
      await m.sembrar(
        pedidoDePrueba(
          n: 2,
          estado: EstadoPedidoLocal.enviando,
          intentos: 1,
          ultimoIntentoEn: ahora.subtract(const Duration(seconds: 30)),
          creadoEn: DateTime.utc(2026, 11, 6, 10),
        ),
      );

      await enviar(m);

      expect(m.api.idsEnviados, [idOperacion(1)]);
      final p1 = await m.pedido(1);
      expect(p1.estado, EstadoPedidoLocal.cobrado);
      expect(p1.intentos, 2);
      expect((await m.pedido(2)).estado, EstadoPedidoLocal.enviando);
    });
  });

  group('sin conexión', () {
    test('no envía, deja el pedido intacto y se reanuda al volver la conexión', () async {
      m.conectividad.emitir(false);
      await m.sembrar(pedidoDePrueba());

      await enviar(m);

      expect(m.api.enviados, isEmpty);
      final p = await m.pedido(1);
      expect(p.estado, EstadoPedidoLocal.pendiente);
      expect(p.intentos, 0);
      expect(m.cola.estado.fase, FaseCola.sinConexion);

      m.conectividad.emitir(true);
      m.cola.alVolverConexion();
      await asentar(m);

      expect((await m.pedido(1)).estado, EstadoPedidoLocal.cobrado);
      expect(m.cola.estado.fase, FaseCola.inactiva);
    });

    test('sin pedidos por enviar no muestra "sin conexión"', () async {
      m.conectividad.emitir(false);

      await enviar(m);

      expect(m.cola.estado.fase, FaseCola.inactiva);
    });

    test('si se corta la red a mitad del envío no se castiga al pedido ni se programa reintento', () async {
      await m.sembrar(pedidoDePrueba());
      m.api.responder((PedidoDiferidoCrear _) {
        m.conectividad.emitir(false);
        throw errorSinRed;
      });

      await enviar(m);

      final p = await m.pedido(1);
      expect(p.estado, EstadoPedidoLocal.pendiente);
      expect(p.ultimoError, 'sin_conexion');
      expect(p.proximoIntentoEn, isNull);
      expect(m.cola.estado.fase, FaseCola.sinConexion);
      expect(m.temporizador.activos, 0);
    });
  });

  group('caducidad a los 7 días', () {
    test('la constante vive en un solo lugar y vale 7 días', () {
      expect(pedidoCaducaDias, 7);
      expect(pedidoCaduca, const Duration(days: 7));
    });

    test('un pendiente con más de 7 días NO se envía: pasa a vencido y no cuenta como pendiente', () async {
      final viejo = m.reloj.actual.subtract(const Duration(days: 7, minutes: 1));
      await m.sembrar(pedidoDePrueba(creadoEn: viejo));

      await enviar(m);

      expect(m.api.enviados, isEmpty);
      final p = await m.pedido(1);
      expect(p.estado, EstadoPedidoLocal.vencido);
      expect(p.motivo, motivoPedidoVencido);
      expect(p.mensaje, mensajePedidoVencido);
      expect(p.mensaje, 'Venció: pasaron más de 7 días sin conexión');
      expect(p.resueltoEn, m.reloj.actual);
      expect(p.visto, isFalse);
      expect(await m.cola.contarSinEnviar(), 0);
      expect(m.resueltos, isEmpty, reason: 'un vencimiento local no es una respuesta del servidor');
    });

    test('exactamente 7 días todavía se envía; el límite es inclusivo', () async {
      await m.sembrar(pedidoDePrueba(creadoEn: m.reloj.actual.subtract(const Duration(days: 7))));

      await enviar(m);

      expect(m.api.enviados, hasLength(1));
      expect((await m.pedido(1)).estado, EstadoPedidoLocal.cobrado);
    });

    test('también vence sin conexión, al inicio del ciclo', () async {
      m.conectividad.emitir(false);
      await m.sembrar(pedidoDePrueba(creadoEn: m.reloj.actual.subtract(const Duration(days: 8))));

      await enviar(m);

      expect((await m.pedido(1)).estado, EstadoPedidoLocal.vencido);
      expect(m.cola.estado.fase, FaseCola.inactiva, reason: 'ya no hay pedidos por enviar');
    });

    test('se revisa ANTES de cada envío: un ciclo largo puede hacer vencer al siguiente', () async {
      final limite = m.reloj.actual.subtract(const Duration(days: 7));
      await m.sembrar(pedidoDePrueba(n: 1, creadoEn: limite.add(const Duration(seconds: 5))));
      await m.sembrar(pedidoDePrueba(n: 2, creadoEn: limite.add(const Duration(seconds: 6))));
      m.api.responder((PedidoDiferidoCrear c) {
        m.reloj.avanzar(const Duration(seconds: 10));
        return respuestaCobrada(c.operacionId);
      });

      await enviar(m);

      expect(m.api.idsEnviados, [idOperacion(1)]);
      expect((await m.pedido(1)).estado, EstadoPedidoLocal.cobrado);
      expect((await m.pedido(2)).estado, EstadoPedidoLocal.vencido);
    });

    test('solo vence el "pendiente": un "enviando" muy viejo y reciente no se toca', () async {
      final ahora = m.reloj.actual;
      await m.sembrar(
        pedidoDePrueba(
          estado: EstadoPedidoLocal.enviando,
          creadoEn: ahora.subtract(const Duration(days: 30)),
          intentos: 1,
          ultimoIntentoEn: ahora.subtract(const Duration(seconds: 10)),
        ),
      );

      await enviar(m);

      expect(m.api.enviados, isEmpty);
      expect((await m.pedido(1)).estado, EstadoPedidoLocal.enviando);
    });

    test('un "enviando" huérfano muy viejo se reenvía (el servidor es idempotente), no vence', () async {
      final ahora = m.reloj.actual;
      await m.sembrar(
        pedidoDePrueba(
          estado: EstadoPedidoLocal.enviando,
          creadoEn: ahora.subtract(const Duration(days: 30)),
          intentos: 1,
          ultimoIntentoEn: ahora.subtract(const Duration(minutes: 10)),
        ),
      );

      await enviar(m);

      expect(m.api.enviados, hasLength(1));
      expect((await m.pedido(1)).estado, EstadoPedidoLocal.cobrado);
    });

    test('un vencido se puede descartar', () async {
      await m.sembrar(pedidoDePrueba(creadoEn: m.reloj.actual.subtract(const Duration(days: 9))));
      await enviar(m);

      expect(await m.cola.descartar(idOperacion(1)), isTrue);

      expect(await m.cola.pedidos(), isEmpty);
    });
  });

  group('encolar, descartar y borrar', () {
    test('encolar guarda el pedido, vacía el carrito local y, con red, lo envía', () async {
      await m.repo().agregarLinea(lineaCarrito(varianteId: 10, cantidad: 2, precio: 19900), maximo: 20);
      await m.repo().agregarLinea(lineaCarrito(varianteId: 11, cantidad: 1, precio: 4950), maximo: 20);
      final lineas = await m.repo().carrito();

      final pedido = await m.cola.encolar(EntradaPedido(sucursalId: 3, sucursalNombre: 'Centro', lineas: lineas));
      await asentar(m);

      expect(pedido, isNotNull);
      expect(pedido!.operacionId, idOperacion(1));
      expect(pedido.totalMaximoCentavos, 2 * 19900 + 4950);
      expect(pedido.costoEnvioCentavos, 0);
      expect(pedido.fechaPedido, endsWith('Z'));
      expect(await m.repo().carrito(), isEmpty, reason: 'el carrito local se vació en la misma transacción');
      expect(m.api.enviados.single.toJson()['total_maximo'], '447.50');
      expect((await m.pedido(1)).estado, EstadoPedidoLocal.cobrado);
    });

    test('sin conexión el pedido queda en la cola, pendiente, con el carrito vacío', () async {
      m.conectividad.emitir(false);
      await m.repo().agregarLinea(lineaCarrito(), maximo: 20);

      final pedido = await m.cola.encolar(
        EntradaPedido(sucursalId: 3, sucursalNombre: 'Centro', lineas: await m.repo().carrito()),
      );
      await asentar(m);

      expect(pedido!.estado, EstadoPedidoLocal.pendiente);
      expect(m.api.enviados, isEmpty);
      expect(await m.repo().carrito(), isEmpty);
      expect(await m.cola.contarSinEnviar(), 1);
    });

    test('el total es exacto en centavos enteros (nada de coma flotante)', () async {
      m.conectividad.emitir(false);
      // 3 x Bs 0.10 + 1 x Bs 0.20 sería 0.30000000000000004 con doubles.
      final lineas = [
        lineaCarrito(varianteId: 1, cantidad: 3, precio: 10),
        lineaCarrito(varianteId: 2, cantidad: 1, precio: 20),
      ];

      final pedido = await m.cola.encolar(EntradaPedido(sucursalId: 3, sucursalNombre: 'Centro', lineas: lineas));
      await asentar(m);

      expect(pedido!.totalMaximoCentavos, 50);
    });

    test('un carrito vacío o demasiado grande no se encola', () async {
      final sinPrendas = await m.cola.encolar(const EntradaPedido(sucursalId: 3, sucursalNombre: 'Centro', lineas: []));
      final demasiadas = await m.cola.encolar(
        EntradaPedido(
          sucursalId: 3,
          sucursalNombre: 'Centro',
          lineas: [for (var i = 1; i <= maxLineasPedido + 1; i++) lineaCarrito(varianteId: i)],
        ),
      );

      expect(sinPrendas, isNull);
      expect(demasiadas, isNull);
      expect(await m.cola.pedidos(), isEmpty);
    });

    test('sin sesión de cliente no se encola nada', () async {
      m.alcance = null;

      final pedido = await m.cola.encolar(
        EntradaPedido(sucursalId: 3, sucursalNombre: 'Centro', lineas: [lineaCarrito()]),
      );

      expect(pedido, isNull);
    });

    test('descartar quita un pendiente; un cobrado, un rechazado o uno enviándose no se pueden quitar', () async {
      await m.sembrar(pedidoDePrueba(n: 1));
      await m.sembrar(pedidoDePrueba(n: 2, estado: EstadoPedidoLocal.cobrado));
      await m.sembrar(pedidoDePrueba(n: 3, estado: EstadoPedidoLocal.rechazado));
      await m.sembrar(pedidoDePrueba(n: 4, estado: EstadoPedidoLocal.enviando));

      expect(await m.cola.descartar(idOperacion(1)), isTrue);
      expect(await m.cola.descartar(idOperacion(2)), isFalse);
      expect(await m.cola.descartar(idOperacion(3)), isFalse);
      expect(await m.cola.descartar(idOperacion(4)), isFalse);
      expect(await m.cola.descartar(idOperacion(99)), isFalse);

      expect(
        (await m.cola.pedidos()).map((p) => p.operacionId),
        unorderedEquals([idOperacion(2), idOperacion(3), idOperacion(4)]),
      );
    });

    test('borrarTodoDeEstaCuenta quita los pedidos sin enviar, el carrito y lo recordado de ESA persona', () async {
      await m.sembrar(pedidoDePrueba(n: 1));
      await m.sembrar(pedidoDePrueba(n: 2, alcance: alcanceLuis));
      await m.repo().agregarLinea(lineaCarrito(), maximo: 20);
      await m.repo().guardarMeta('metodo_pago', '{}');

      expect(await m.cola.borrarTodoDeEstaCuenta(), isTrue);

      expect(await m.cola.pedidos(), isEmpty);
      expect(await m.repo().carrito(), isEmpty);
      expect(await m.repo().leerMeta('metodo_pago'), isNull);
      expect(await m.repo(alcanceLuis).pedidos(), hasLength(1), reason: 'los de otra persona no se tocan');
    });

    test('marcarVistos marca los resueltos y los vencidos, no los pendientes', () async {
      await m.sembrar(pedidoDePrueba(n: 1, estado: EstadoPedidoLocal.cobrado));
      await m.sembrar(pedidoDePrueba(n: 2, estado: EstadoPedidoLocal.vencido));
      await m.sembrar(pedidoDePrueba(n: 3));

      await m.cola.marcarVistos();

      expect((await m.pedido(1)).visto, isTrue);
      expect((await m.pedido(2)).visto, isTrue);
      expect((await m.pedido(3)).visto, isFalse);
    });

    test('cada cambio de la lista avisa por el flujo de cambios', () async {
      var avisos = 0;
      final sub = m.cola.cambios.listen((_) => avisos++);
      await m.sembrar(pedidoDePrueba());

      await enviar(m);
      await sub.cancel();

      expect(avisos, greaterThan(0));
    });
  });
}
