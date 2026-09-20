import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/catalogo/data/catalogo_repository.dart';
import 'package:mobile/features/catalogo/models/catalogo_detalle.dart';
import 'package:mobile/features/catalogo/models/catalogo_item.dart';
import 'package:mobile/features/catalogo/models/variante_lookup.dart';
import 'package:mobile/features/catalogo/state/catalogo_providers.dart';
import 'package:mobile/features/probador/data/probador_repository.dart';
import 'package:mobile/features/probador/models/activo_probador.dart';
import 'package:mobile/features/probador/state/probador_providers.dart';

/// Catálogo de prueba: Polera A (10: variantes 101 y 102), Camisa B (20: 201 y 202) y un Pantalón C (30) que no admite
/// probador. La Chamarra D (40, variante 401) existe pero NO está en el listado (p. ej. más allá de los primeros 50).
class _CatalogoFalso extends CatalogoRepository {
  _CatalogoFalso() : super(Dio());

  static const _productos = {
    10: ('Polera A', true, [101, 102]),
    20: ('Camisa B', true, [201, 202]),
    30: ('Pantalón C', false, [301]),
  };

  static const _datosPorVariante = {
    101: (10, 'Polera A'),
    102: (10, 'Polera A'),
    201: (20, 'Camisa B'),
    202: (20, 'Camisa B'),
    401: (40, 'Chamarra D'),
  };

  @override
  Future<List<CatalogoItem>> listar({required int pagina, required int tamanio}) async => [
    for (final e in _productos.entries)
      CatalogoItem(
        id: e.key,
        codigo: 'P${e.key}',
        nombre: e.value.$1,
        categoriaId: 1,
        genero: 'hombre',
        precioBase: 100,
        admiteProbador: e.value.$2,
        imagenPrincipal: null,
      ),
  ];

  @override
  Future<CatalogoDetalle> detalle(int productoId) async {
    final (nombre, admite, variantes) = _productos[productoId]!;
    return CatalogoDetalle(
      id: productoId,
      codigo: 'P$productoId',
      nombre: nombre,
      descripcion: null,
      categoriaId: 1,
      materialId: null,
      temporadaId: null,
      coleccionId: null,
      genero: 'hombre',
      precioBase: 100,
      admiteProbador: admite,
      variantes: [
        for (final v in variantes)
          VarianteCatalogo(id: v, tallaId: 1, colorId: 1, sku: 'S$v', precioEfectivo: 100, cantidadDisponible: null),
      ],
      imagenes: const [],
    );
  }

  @override
  Future<List<VarianteLookupItem>> detallePorVariantes(List<int> varianteIds) async => [
    for (final id in varianteIds)
      if (_datosPorVariante[id] case (final productoId, final nombre))
        VarianteLookupItem(
          varianteId: id,
          productoId: productoId,
          productoNombre: nombre,
          imagenPrincipal: null,
          tallaCodigo: 'M',
          colorNombre: 'Azul',
        ),
  ];
}

/// Con overlay validado: 101, 102, 201 y 401. La 202 responde 404 (sin overlay) y la 999 falla como si no hubiera red.
class _ProbadorFalso extends ProbadorRepository {
  _ProbadorFalso() : super(Dio());

  static const _conOverlay = {101, 102, 201, 401};

  @override
  Future<AssetsVariante> obtenerAssets(int varianteId) async {
    final opciones = RequestOptions(path: '/probador/variante/$varianteId/assets');
    if (varianteId == 999) throw DioException(requestOptions: opciones, type: DioExceptionType.connectionError);
    if (!_conOverlay.contains(varianteId)) {
      throw DioException(requestOptions: opciones, response: Response(requestOptions: opciones, statusCode: 404));
    }
    return AssetsVariante(
      overlay: ActivoProbador(
        id: varianteId,
        varianteId: varianteId,
        tipo: 'overlay_2d',
        publicId: 'p$varianteId',
        url: 'https://ejemplo.test/$varianteId.png',
        anclajes: null,
        anchoPx: 100,
        altoPx: 100,
        estado: 'validado',
      ),
      flatlay: null,
    );
  }
}

ProviderContainer _contenedor() {
  final contenedor = ProviderContainer(
    overrides: [
      catalogoRepositoryProvider.overrideWithValue(_CatalogoFalso()),
      probadorRepositoryProvider.overrideWithValue(_ProbadorFalso()),
    ],
  );
  addTearDown(contenedor.dispose);
  return contenedor;
}

Future<List<int>> _variantes(ProviderContainer contenedor, int? varianteInicial) async {
  final proveedor = prendasParaProbadorProvider(varianteInicial);
  contenedor.listen(proveedor, (previo, siguiente) {}); // los autoDispose necesitan un oyente mientras se esperan
  final prendas = await contenedor.read(proveedor.future);
  return [for (final p in prendas) p.varianteId];
}

void main() {
  group('prendasParaProbadorProvider', () {
    test('sin prenda inicial es la lista de siempre: la primera variante de cada producto con overlay', () async {
      expect(await _variantes(_contenedor(), null), [101, 201]);
    });

    test('la prenda inicial va primera y su producto no se repite con otra variante', () async {
      // 102 es otra variante de la Polera A, que ya estaba en la lista como 101.
      expect(await _variantes(_contenedor(), 102), [102, 201]);
    });

    test('si la inicial ya era la de la lista, solo pasa al principio', () async {
      expect(await _variantes(_contenedor(), 201), [201, 101]);
    });

    test('una inicial que no está en el listado se antepone', () async {
      expect(await _variantes(_contenedor(), 401), [401, 101, 201]);
    });

    test('si la variante inicial no tiene overlay (404) el probador abre con su lista de siempre', () async {
      expect(await _variantes(_contenedor(), 202), [101, 201]);
    });

    test('si no se puede resolver la inicial (sin red) tampoco se rompe: lista de siempre', () async {
      expect(await _variantes(_contenedor(), 999), [101, 201]);
    });

    test('la prenda inicial trae el nombre y el producto para poder mostrarla', () async {
      final contenedor = _contenedor();
      final proveedor = prendasParaProbadorProvider(401);
      contenedor.listen(proveedor, (previo, siguiente) {});

      final primera = (await contenedor.read(proveedor.future)).first;

      expect(primera.nombre, 'Chamarra D');
      expect(primera.productoId, 40);
    });
  });

  group('assetsProbadorProvider', () {
    test('devuelve los assets cuando la variante tiene overlay validado', () async {
      final contenedor = _contenedor();
      contenedor.listen(assetsProbadorProvider(101), (previo, siguiente) {});

      final assets = await contenedor.read(assetsProbadorProvider(101).future);

      expect(assets?.overlay.varianteId, 101);
    });

    test('devuelve null (no error) cuando el backend responde 404', () async {
      final contenedor = _contenedor();
      contenedor.listen(assetsProbadorProvider(202), (previo, siguiente) {});

      expect(await contenedor.read(assetsProbadorProvider(202).future), isNull);
    });

    test('un error que no es 404 sí se propaga', () async {
      final contenedor = _contenedor();
      contenedor.listen(assetsProbadorProvider(999), (previo, siguiente) {});

      await expectLater(contenedor.read(assetsProbadorProvider(999).future), throwsA(isA<DioException>()));
    });
  });
}
