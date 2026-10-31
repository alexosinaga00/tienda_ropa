import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/error_app.dart';
import 'package:mobile/core/network/providers.dart';
import 'package:mobile/features/auth/models/usuario.dart';
import 'package:mobile/features/auth/state/auth_controller.dart';
import 'package:mobile/features/auth/state/auth_state.dart';
import 'package:mobile/features/catalogo/models/catalogo_item.dart';
import 'package:mobile/features/catalogo/models/filtros_catalogo.dart';
import 'package:mobile/features/catalogo/state/catalogo_controller.dart';
import 'package:mobile/features/catalogo/state/catalogo_providers.dart';
import 'package:mobile/features/reservas/models/item_reserva_temporal.dart';
import 'package:mobile/features/reservas/state/carrito_reserva_controller.dart';
import 'package:mobile/features/tienda/models/tienda.dart';
import 'package:mobile/features/tienda/state/tienda_controller.dart';
import 'package:mobile/features/tracking/models/evento.dart';
import 'package:mobile/features/tracking/state/tracking_service.dart';

import '../../helpers/sesion_storage_falso.dart';
import '../../helpers/token_storage_falso.dart';

const _alpha = Tienda(codigo: 'alpha', nombre: 'Alpha Sport');
const _beta = Tienda(codigo: 'beta', nombre: 'Beta Boutique');

const _item = ItemReservaTemporal(
  varianteId: 11,
  productoNombre: 'Polera básica',
  sku: 'POL-001-M-NEGRO',
  tallaCodigo: 'M',
  colorNombre: 'Negro',
);

/// Una petición que llegó al servidor falso.
class _Peticion {
  _Peticion(this.metodo, this.ruta, this.publica);

  final String metodo;
  final String ruta;
  final bool publica;

  @override
  String toString() => '$metodo $ruta${publica ? ' (pública)' : ''}';
}

/// Adaptador HTTP falso: no hay red. Guarda cada petición y responde:
///  - el catálogo (`.../catalogo` y `.../catalogo/buscar`): UN producto cuyo nombre lleva el código de la tienda de la
///    ruta, para ver de qué tienda salieron los datos;
///  - los eventos (`.../ia/eventos`): un error de conexión si [eventosFallan] (el evento queda encolado) o 204;
///  - todo lo demás: una lista vacía.
class _ServidorFalso implements HttpClientAdapter {
  final peticiones = <_Peticion>[];
  bool eventosFallan = false;

  Iterable<String> rutas([String metodo = 'GET']) => peticiones.where((p) => p.metodo == metodo).map((p) => p.ruta);

  @override
  Future<ResponseBody> fetch(RequestOptions options, Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async {
    peticiones.add(_Peticion(options.method, options.path, options.extra['publica'] == true));
    final ruta = options.path;

    if (ruta.endsWith('/ia/eventos')) {
      if (eventosFallan) {
        throw DioException(requestOptions: options, type: DioExceptionType.connectionError);
      }
      return ResponseBody.fromString('', 204);
    }

    final cabeceras = {
      Headers.contentTypeHeader: [Headers.jsonContentType],
    };
    if (ruta.endsWith('/catalogo') || ruta.endsWith('/catalogo/buscar')) {
      final codigo = ruta.split('/')[2];
      final producto =
          '{"id":1,"codigo":"P-1","nombre":"Producto de $codigo","categoria_id":1,"genero":"unisex",'
          '"precio_base":"50.00","admite_probador":false,"imagen_principal":null}';
      return ResponseBody.fromString('[$producto]', 200, headers: cabeceras);
    }
    return ResponseBody.fromString('[]', 200, headers: cabeceras);
  }

  @override
  void close({bool force = false}) {}
}

class _Entorno {
  _Entorno(this.contenedor, this.servidor);

  final ProviderContainer contenedor;
  final _ServidorFalso servidor;

  TiendaController get tiendas => contenedor.read(tiendaControllerProvider.notifier);

  Future<void> elegir(Tienda tienda) async {
    await tiendas.elegir(tienda);
    await pumpEventQueue();
  }
}

/// Arma el contenedor con la tienda [inicial] ya leída y un Dio cuyo adaptador es el [_ServidorFalso]. Todo lo demás
/// (apiClientProvider, repositorios, controladores) es el real.
Future<_Entorno> _entorno({Tienda? inicial = _alpha}) async {
  final servidor = _ServidorFalso();
  final dio = Dio(BaseOptions(baseUrl: 'http://servidor.falso'))..httpClientAdapter = servidor;
  final contenedor = ProviderContainer(
    overrides: [
      dioProvider.overrideWithValue(dio),
      tokenStorageProvider.overrideWithValue(TokenStorageFalso()),
      sesionStorageProvider.overrideWithValue(SesionStorageFalso(tienda: inicial)),
    ],
  );
  addTearDown(contenedor.dispose);
  await contenedor.read(tiendaControllerProvider.notifier).cargadaFuture;
  return _Entorno(contenedor, servidor);
}

/// Un [AuthController] que arranca en el estado dado (para la prueba con sesión).
class _AuthFalso extends AuthController {
  _AuthFalso(super.ref, AuthState inicial) {
    state = inicial;
  }
}

void main() {
  group('apiClientProvider', () {
    test('entrega una instancia NUEVA al cambiar de tienda', () async {
      final e = await _entorno();
      final antes = e.contenedor.read(apiClientProvider);
      expect(e.contenedor.read(apiClientProvider), same(antes), reason: 'sin cambios es la misma');

      await e.elegir(_beta);

      expect(e.contenedor.read(apiClientProvider), isNot(same(antes)));
    });

    test('elegir la MISMA tienda otra vez no lo reconstruye', () async {
      final e = await _entorno();
      final antes = e.contenedor.read(apiClientProvider);

      await e.elegir(_alpha);

      expect(e.contenedor.read(apiClientProvider), same(antes));
    });

    test('elegir el mismo código con otro nombre o color (branding) tampoco lo reconstruye', () async {
      final e = await _entorno();
      final api = e.contenedor.read(apiClientProvider);
      final catalogo = e.contenedor.read(catalogoControllerProvider.notifier);
      final tracking = e.contenedor.read(trackingServiceProvider);

      await e.elegir(const Tienda(codigo: 'alpha', nombre: 'Alpha Sport Renovada', colorAcento: '#112233'));

      expect(e.contenedor.read(tiendaActualProvider)?.nombre, 'Alpha Sport Renovada');
      expect(e.contenedor.read(apiClientProvider), same(api));
      expect(e.contenedor.read(catalogoControllerProvider.notifier), same(catalogo));
      expect(e.contenedor.read(trackingServiceProvider), same(tracking));
    });

    test('olvidar la tienda también lo reconstruye', () async {
      final e = await _entorno();
      final antes = e.contenedor.read(apiClientProvider);

      await e.tiendas.olvidar();
      await pumpEventQueue();

      expect(e.contenedor.read(tiendaCodigoProvider), isNull);
      expect(e.contenedor.read(apiClientProvider), isNot(same(antes)));
    });
  });

  group('rutas públicas tras el cambio', () {
    test('antes del cambio la petición pública va a /public/alpha/...', () async {
      final e = await _entorno();

      await e.contenedor.read(apiClientProvider).getLista<CatalogoItem>('/catalogo', desde: CatalogoItem.fromJson, publica: true);

      expect(e.servidor.rutas(), ['/public/alpha/catalogo']);
    });

    test('después de cambiar, la petición pública va a /public/beta/... y nunca a la tienda anterior', () async {
      final e = await _entorno();
      await e.elegir(_beta);

      await e.contenedor.read(apiClientProvider).getLista<CatalogoItem>('/catalogo', desde: CatalogoItem.fromJson, publica: true);

      expect(e.servidor.rutas(), contains('/public/beta/catalogo'));
      expect(e.servidor.rutas().where((r) => r.contains('alpha')), isEmpty);
    });

    test('una petición privada no lleva código de tienda (la empresa sale del token)', () async {
      final e = await _entorno();
      await e.elegir(_beta);

      await e.contenedor.read(apiClientProvider).getLista<CatalogoItem>('/favoritos', desde: CatalogoItem.fromJson);

      expect(e.servidor.rutas(), ['/favoritos']);
    });

    test('sin tienda elegida una petición pública falla con "Elige una tienda" y no sale a la red', () async {
      final e = await _entorno(inicial: null);

      final futuro = e.contenedor.read(apiClientProvider).getLista<CatalogoItem>(
        '/catalogo',
        desde: CatalogoItem.fromJson,
        publica: true,
      );

      await expectLater(
        futuro,
        throwsA(isA<ErrorApp>().having((error) => error.mensaje, 'mensaje', contains('Elige una tienda'))),
      );
      expect(e.servidor.peticiones, isEmpty);
    });
  });

  group('catalogoControllerProvider', () {
    test('se reconstruye: otro controlador, con el estado inicial y sin filtros', () async {
      final e = await _entorno();
      final viejo = e.contenedor.read(catalogoControllerProvider.notifier);
      await pumpEventQueue();
      await viejo.aplicarFiltros(const FiltrosCatalogo(texto: 'polera', genero: 'hombre'));
      expect(e.contenedor.read(catalogoControllerProvider).filtros.tieneFiltros, isTrue);
      expect(e.contenedor.read(catalogoControllerProvider).items, hasLength(1));

      // El cambio llega con el catálogo ya cargado y filtrado; justo después de leer, el estado es el de recién creado.
      await e.tiendas.elegir(_beta);
      final nuevo = e.contenedor.read(catalogoControllerProvider.notifier);
      final estadoRecienCreado = e.contenedor.read(catalogoControllerProvider);

      expect(nuevo, isNot(same(viejo)));
      expect(viejo.mounted, isFalse, reason: 'el controlador de la tienda anterior se descarta');
      expect(estadoRecienCreado.filtros.tieneFiltros, isFalse);
      expect(estadoRecienCreado.items, isEmpty);
      expect(estadoRecienCreado.pagina, 1);
      expect(estadoRecienCreado.etiquetasVoz, isEmpty);
      expect(estadoRecienCreado.cargandoPrimeraPagina, isTrue);

      // Se deja terminar la carga de la tienda nueva: soltar el contenedor con una petición en vuelo hace que el
      // controlador escriba su estado ya descartado (ver el informe: CatalogoController no revisa `mounted`).
      await pumpEventQueue();
      expect(e.contenedor.read(catalogoControllerProvider).items.single.nombre, 'Producto de beta');
    });

    test('carga el catálogo de la tienda nueva, no el de la anterior', () async {
      final e = await _entorno();
      e.contenedor.read(catalogoControllerProvider);
      await pumpEventQueue();
      expect(e.contenedor.read(catalogoControllerProvider).items.single.nombre, 'Producto de alpha');

      await e.tiendas.elegir(_beta);
      e.contenedor.read(catalogoControllerProvider);
      await pumpEventQueue();

      final estado = e.contenedor.read(catalogoControllerProvider);
      expect(estado.items, hasLength(1));
      expect(estado.items.single.nombre, 'Producto de beta');
      expect(estado.cargandoPrimeraPagina, isFalse);
      expect(e.servidor.rutas(), containsAllInOrder(['/public/alpha/catalogo', '/public/beta/catalogo']));
    });

    test('con la misma tienda conserva el controlador, los filtros y los items', () async {
      final e = await _entorno();
      final controlador = e.contenedor.read(catalogoControllerProvider.notifier);
      await pumpEventQueue();
      await controlador.aplicarFiltros(const FiltrosCatalogo(texto: 'polera'));
      final estado = e.contenedor.read(catalogoControllerProvider);

      await e.elegir(_alpha);

      expect(e.contenedor.read(catalogoControllerProvider.notifier), same(controlador));
      expect(e.contenedor.read(catalogoControllerProvider), same(estado));
      expect(e.contenedor.read(catalogoControllerProvider).filtros.texto, 'polera');
    });

    test('quien escucha el estado recibe el estado inicial de la tienda nueva (no se queda con el viejo)', () async {
      final e = await _entorno();
      final recibidos = <CatalogoState>[];
      e.contenedor.listen(catalogoControllerProvider, (_, estado) => recibidos.add(estado), fireImmediately: true);
      await pumpEventQueue();
      final antes = recibidos.length;

      await e.elegir(_beta);

      expect(recibidos.length, greaterThan(antes));
      expect(recibidos.any((s) => s.items.any((i) => i.nombre.contains('beta'))), isTrue);
      expect(e.contenedor.read(catalogoControllerProvider).items.single.nombre, 'Producto de beta');
    });
  });

  group('repositorios', () {
    test('catalogoRepositoryProvider y referenciaRepositoryProvider se reconstruyen', () async {
      final e = await _entorno();
      final catalogo = e.contenedor.read(catalogoRepositoryProvider);
      final referencia = e.contenedor.read(referenciaRepositoryProvider);

      await e.elegir(_beta);

      expect(e.contenedor.read(catalogoRepositoryProvider), isNot(same(catalogo)));
      expect(e.contenedor.read(referenciaRepositoryProvider), isNot(same(referencia)));
    });

    test('con la misma tienda los repositorios siguen siendo los mismos', () async {
      final e = await _entorno();
      final catalogo = e.contenedor.read(catalogoRepositoryProvider);
      final referencia = e.contenedor.read(referenciaRepositoryProvider);

      await e.elegir(_alpha);

      expect(e.contenedor.read(catalogoRepositoryProvider), same(catalogo));
      expect(e.contenedor.read(referenciaRepositoryProvider), same(referencia));
    });

    test('los catálogos de referencia en caché se vuelven a pedir a la tienda nueva', () async {
      final e = await _entorno();
      await e.contenedor.read(categoriasRefProvider.future);
      await e.contenedor.read(tallasRefProvider.future);
      expect(e.servidor.rutas(), containsAll(['/public/alpha/categorias', '/public/alpha/tallas']));

      await e.elegir(_beta);
      await e.contenedor.read(categoriasRefProvider.future);
      await e.contenedor.read(tallasRefProvider.future);

      expect(e.servidor.rutas(), containsAll(['/public/beta/categorias', '/public/beta/tallas']));
    });

    test('el detalle de un producto en caché también se vuelve a pedir a la tienda nueva', () async {
      final e = await _entorno();
      final repoAlpha = e.contenedor.read(catalogoRepositoryProvider);

      await e.elegir(_beta);

      // `detalleProductoProvider` lee el repositorio con `watch`: depende de la tienda a través de él.
      expect(e.contenedor.read(catalogoRepositoryProvider), isNot(same(repoAlpha)));
      e.contenedor.listen(detalleProductoProvider(1), (_, _) {}, fireImmediately: true);
      await pumpEventQueue();
      expect(e.servidor.rutas().where((r) => r.contains('/catalogo/1')), everyElement(startsWith('/public/beta/')));
    });
  });

  group('carritoReservaProvider', () {
    test('se vacía al cambiar de tienda', () async {
      final e = await _entorno();
      e.contenedor.read(carritoReservaProvider.notifier).agregar(_item);
      expect(e.contenedor.read(carritoReservaProvider), hasLength(1));
      final viejo = e.contenedor.read(carritoReservaProvider.notifier);

      await e.elegir(_beta);

      expect(e.contenedor.read(carritoReservaProvider), isEmpty);
      expect(e.contenedor.read(carritoReservaProvider.notifier), isNot(same(viejo)));
    });

    test('con la misma tienda conserva lo agregado', () async {
      final e = await _entorno();
      e.contenedor.read(carritoReservaProvider.notifier).agregar(_item);

      await e.elegir(_alpha);

      expect(e.contenedor.read(carritoReservaProvider), hasLength(1));
      expect(e.contenedor.read(carritoReservaProvider).single.varianteId, 11);
    });

    test('se vacía también al iniciar o cerrar sesión (ya no es la misma persona)', () async {
      const usuario = Usuario(
        id: 1,
        nombre: 'Ana',
        apellido: 'Rojas',
        email: 'ana@example.com',
        telefono: null,
        activo: true,
        roles: ['cliente'],
        permisos: [],
        empresaCodigo: 'alpha',
      );
      final servidor = _ServidorFalso();
      final dio = Dio(BaseOptions(baseUrl: 'http://servidor.falso'))..httpClientAdapter = servidor;
      final contenedor = ProviderContainer(
        overrides: [
          dioProvider.overrideWithValue(dio),
          tokenStorageProvider.overrideWithValue(TokenStorageFalso()),
          sesionStorageProvider.overrideWithValue(SesionStorageFalso(tienda: _alpha)),
          authControllerProvider.overrideWith(
            (ref) => _AuthFalso(ref, const AuthState(estado: EstadoSesion.autenticado, usuario: usuario)),
          ),
        ],
      );
      addTearDown(contenedor.dispose);
      await contenedor.read(tiendaControllerProvider.notifier).cargadaFuture;
      contenedor.read(carritoReservaProvider.notifier).agregar(_item);
      expect(contenedor.read(carritoReservaProvider), hasLength(1));

      await contenedor.read(authControllerProvider.notifier).logout();

      expect(contenedor.read(carritoReservaProvider), isEmpty);
    });
  });

  group('trackingServiceProvider', () {
    test('entrega una instancia nueva con la cola vacía al cambiar de tienda', () async {
      final e = await _entorno();
      e.servidor.eventosFallan = true;
      final viejo = e.contenedor.read(trackingServiceProvider);
      viejo.track(tipo: TipoEvento.vista, productoId: 3);
      await pumpEventQueue();
      expect(viejo.eventosEncolados, 1, reason: 'sin red el evento queda encolado');

      await e.elegir(_beta);

      final nuevo = e.contenedor.read(trackingServiceProvider);
      expect(nuevo, isNot(same(viejo)));
      expect(nuevo.eventosEncolados, 0);
    });

    test('los eventos de la tienda nueva van a /public/beta/ia/eventos', () async {
      final e = await _entorno();
      await e.elegir(_beta);

      e.contenedor.read(trackingServiceProvider).track(tipo: TipoEvento.busqueda, texto: 'polera');
      await pumpEventQueue();

      expect(e.servidor.rutas('POST'), ['/public/beta/ia/eventos']);
    });

    test('un evento encolado de la tienda anterior no se envía a la nueva', () async {
      final e = await _entorno();
      e.servidor.eventosFallan = true;
      e.contenedor.read(trackingServiceProvider).track(tipo: TipoEvento.vista, productoId: 3);
      await pumpEventQueue();

      await e.elegir(_beta);
      e.servidor.eventosFallan = false;
      e.contenedor.read(trackingServiceProvider).track(tipo: TipoEvento.vista, productoId: 9);
      await pumpEventQueue();

      final posts = e.servidor.peticiones.where((p) => p.metodo == 'POST').toList();
      expect(posts.where((p) => p.ruta.contains('beta')), hasLength(1));
      expect(posts.last.ruta, '/public/beta/ia/eventos');
    });

    test('con la misma tienda conserva la instancia (y su cola)', () async {
      final e = await _entorno();
      final servicio = e.contenedor.read(trackingServiceProvider);

      await e.elegir(_alpha);

      expect(e.contenedor.read(trackingServiceProvider), same(servicio));
    });
  });
}
