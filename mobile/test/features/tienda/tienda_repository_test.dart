import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/tienda/data/tienda_repository.dart';

import '../../helpers/api_client_falso.dart';

const _tiendas = [
  {'codigo': 'chaski', 'nombre': 'Chaski Sport', 'logo_url': null, 'color_acento': '#112233'},
  {'codigo': 'andina', 'nombre': 'Boutique Andina', 'logo_url': 'https://img.test/a.png', 'color_acento': null},
];

void main() {
  group('TiendaRepository.listar', () {
    test('sin búsqueda manda pagina y tamanio=50, y no manda q', () async {
      final api = ApiClientFalso()..responder('GET', '/public/tiendas', _tiendas);

      final tiendas = await TiendaRepository(api).listar();

      final llamada = api.llamadas.single;
      expect(llamada.ruta, '/public/tiendas');
      expect(llamada.publica, isTrue);
      expect(llamada.query, {'pagina': 1, 'tamanio': 50});
      expect(llamada.query!.containsKey('q'), isFalse);
      expect(tiendas.map((t) => t.codigo), ['chaski', 'andina']);
      expect(tiendas.first.nombre, 'Chaski Sport');
      expect(tiendas.first.colorAcento, '#112233');
      expect(tiendas.last.logoUrl, 'https://img.test/a.png');
    });

    test('con texto manda q recortado', () async {
      final api = ApiClientFalso()..responder('GET', '/public/tiendas', _tiendas);

      await TiendaRepository(api).listar(q: '  chaski  ');

      expect(api.llamadas.single.query, {'pagina': 1, 'tamanio': 50, 'q': 'chaski'});
    });

    test('un texto vacío o solo de espacios no manda q', () async {
      final api = ApiClientFalso()..responder('GET', '/public/tiendas', const <Map<String, Object?>>[]);
      final repositorio = TiendaRepository(api);

      await repositorio.listar(q: '');
      await repositorio.listar(q: '   ');
      await repositorio.listar(q: null);

      expect(api.llamadas, hasLength(3));
      for (final llamada in api.llamadas) {
        expect(llamada.query, {'pagina': 1, 'tamanio': 50});
      }
    });

    test('manda la página pedida', () async {
      final api = ApiClientFalso()..responder('GET', '/public/tiendas', const <Map<String, Object?>>[]);

      final tiendas = await TiendaRepository(api).listar(pagina: 3, q: 'x');

      expect(api.llamadas.single.query, {'pagina': 3, 'tamanio': 50, 'q': 'x'});
      expect(tiendas, isEmpty);
    });

    test('el tamaño de página es el máximo que admite el backend', () {
      expect(TiendaRepository.tamanioPagina, 50);
    });
  });

  group('TiendaRepository.obtener', () {
    Map<String, dynamic> detalle(String codigo) => {
      'codigo': codigo,
      'nombre': 'Chaski Sport',
      'logo_url': null,
      'color_acento': null,
      'disponible': false,
    };

    test('pide /public/{codigo}/tienda como ruta pública y lee disponible', () async {
      final api = ApiClientFalso()..responder('GET', '/public/chaski/tienda', detalle('chaski'));

      final tienda = await TiendaRepository(api).obtener('chaski');

      final llamada = api.llamadas.single;
      expect(llamada.ruta, '/public/chaski/tienda');
      expect(llamada.publica, isTrue);
      expect(tienda.codigo, 'chaski');
      expect(tienda.disponible, isFalse);
    });

    test('normaliza el código: recorta y pasa a minúsculas', () async {
      final api = ApiClientFalso()..responder('GET', '/public/chaski-sport/tienda', detalle('chaski-sport'));

      await TiendaRepository(api).obtener('  Chaski-SPORT ');

      expect(api.llamadas.single.ruta, '/public/chaski-sport/tienda');
    });

    test('codifica el código para que no altere la ruta', () async {
      final api = ApiClientFalso()
        ..responder('GET', '/public/a%2Fb%3Fc/tienda', detalle('x'))
        ..responder('GET', '/public/chaski%20sport/tienda', detalle('x'));
      final repositorio = TiendaRepository(api);

      await repositorio.obtener('A/B?C');
      await repositorio.obtener('Chaski Sport');

      expect(api.llamadas.map((l) => l.ruta), ['/public/a%2Fb%3Fc/tienda', '/public/chaski%20sport/tienda']);
    });

    test('una tienda sin el campo disponible se considera disponible', () async {
      final api = ApiClientFalso()
        ..responder('GET', '/public/chaski/tienda', {'codigo': 'chaski', 'nombre': 'Chaski Sport'});

      final tienda = await TiendaRepository(api).obtener('chaski');

      expect(tienda.disponible, isTrue);
    });
  });
}
