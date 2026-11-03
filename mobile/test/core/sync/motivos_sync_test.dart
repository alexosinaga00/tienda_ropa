import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/sync/motivos_sync.dart';

/// Los códigos de `motivo` que el backend puede mandar (backend/app/sincronizacion/politicas.py) y que la app trata con texto
/// propio.
const _codigosConTexto = [
  'suscripcion_no_activa',
  'plan_sin_operacion_offline',
  'sucursal_no_autorizada',
  'sucursal_inexistente',
  'usuario_no_es_empleado',
  'variante_inexistente',
  'variante_inactiva',
  'cliente_inexistente',
  'payload_invalido',
  'tipo_no_soportado',
  'total_inconsistente',
  'total_invalido',
  'metodo_pago_no_permitido',
  'monto_insuficiente',
  'fecha_futura',
  'reserva_fuera_de_horario',
  'reserva_vencida',
  'stock_insuficiente',
];

/// Códigos del backend que la app todavía no traduce: deben degradar sin romper.
const _codigosSinTextoPropio = ['permiso_denegado', 'regla_de_negocio', 'rechazada_por_encargado', 'operador_inactivo'];

/// Formas de voseo (la app habla de "tú").
final _voseo = RegExp(
  r'(?<!\p{L})(tenés|podés|hacé|querés|sabés|andá|mirá|avisá|revisá|elegí|registrá|actualizá|consultá|contactá|intentá|volvé|pedí|decí|fijate|vos|sos|usá|esperá|probá)(?!\p{L})',
  caseSensitive: false,
  unicode: true,
);

void main() {
  group('textos de cada código del backend', () {
    for (final codigo in _codigosConTexto) {
      test('$codigo tiene título, qué pasó y qué hacer', () {
        final m = motivoDe(codigo);
        expect(m.titulo.trim(), isNotEmpty);
        expect(m.quePaso.trim(), isNotEmpty);
        expect(m.queHacer.trim(), isNotEmpty);
      });

      test('$codigo es un código que la app declara conocer', () {
        expect(codigosDeMotivoConocidos, contains(codigo));
      });

      test('$codigo no usa voseo ni segunda persona del voseo', () {
        final m = motivoDe(codigo);
        for (final texto in [m.titulo, m.quePaso, m.queHacer]) {
          expect(_voseo.hasMatch(texto), isFalse, reason: 'voseo en "$texto"');
        }
      });

      test('$codigo no queda con texto genérico', () {
        expect(motivoDe(codigo).titulo, isNot(motivoDe('codigo_que_no_existe').titulo));
      });
    }

    test('la app conoce todos los códigos de la lista', () {
      expect(codigosDeMotivoConocidos.toSet().containsAll(_codigosConTexto), isTrue);
    });

    test('ningún título, qué pasó o qué hacer queda vacío ni con espacios sobrantes', () {
      for (final codigo in codigosDeMotivoConocidos) {
        final m = motivoDe(codigo);
        for (final texto in [m.titulo, m.quePaso, m.queHacer]) {
          expect(texto, isNotEmpty, reason: codigo);
          expect(texto, texto.trim(), reason: codigo);
        }
      }
    });

    test('los títulos son distintos entre sí (no hay dos códigos con el mismo título)', () {
      final titulos = [for (final c in codigosDeMotivoConocidos) motivoDe(c).titulo];
      expect(titulos.toSet().length, titulos.length);
    });

    test('las frases terminan en punto (o signo de cierre), no cortadas', () {
      for (final codigo in codigosDeMotivoConocidos) {
        final m = motivoDe(codigo);
        for (final texto in [m.quePaso, m.queHacer]) {
          expect(RegExp(r'[.!?]$').hasMatch(texto), isTrue, reason: '$codigo: "$texto"');
        }
      }
    });

    test('stock_insuficiente manda al encargado', () {
      expect(motivoDe('stock_insuficiente').queHacer, contains('encargado'));
    });

    test('un error de plan o de suscripción manda al administrador de la empresa', () {
      expect(motivoDe('suscripcion_no_activa').queHacer, contains('administrador'));
      expect(motivoDe('plan_sin_operacion_offline').queHacer, contains('administrador'));
    });

    test('esas operaciones no se dan por perdidas', () {
      expect(motivoDe('suscripcion_no_activa').queHacer, contains('no se ha perdido'));
    });
  });

  group('códigos desconocidos', () {
    test('usan el mensaje del servidor como "qué pasó"', () {
      final m = motivoDe('motivo_nuevo', mensajeServidor: 'El cliente está bloqueado');
      expect(m.quePaso, 'El cliente está bloqueado');
      expect(m.titulo, isNotEmpty);
      expect(m.queHacer, isNotEmpty);
    });

    test('el mensaje del servidor se recorta', () {
      expect(motivoDe('motivo_nuevo', mensajeServidor: '  hola  ').quePaso, 'hola');
    });

    test('sin mensaje usan el texto genérico', () {
      final m = motivoDe('motivo_nuevo');
      expect(m.titulo, 'Operación no aceptada');
      expect(m.quePaso, 'El servidor no pudo aceptar esta operación.');
      expect(m.queHacer, contains('encargado'));
    });

    test('con mensaje vacío o solo espacios usan el genérico', () {
      expect(motivoDe('motivo_nuevo', mensajeServidor: '').quePaso, 'El servidor no pudo aceptar esta operación.');
      expect(motivoDe('motivo_nuevo', mensajeServidor: '   ').quePaso, 'El servidor no pudo aceptar esta operación.');
    });

    test('un código nulo cuenta como desconocido', () {
      expect(motivoDe(null).titulo, 'Operación no aceptada');
      expect(motivoDe(null, mensajeServidor: 'Falló algo').quePaso, 'Falló algo');
    });

    test('un código vacío cuenta como desconocido', () {
      expect(motivoDe('').titulo, 'Operación no aceptada');
    });

    test('un código conocido ignora el mensaje del servidor (el texto de la app manda)', () {
      final m = motivoDe('stock_insuficiente', mensajeServidor: 'Not enough stock for variant 3');
      expect(m.quePaso, isNot(contains('Not enough')));
      expect(m.titulo, 'Falta stock');
    });

    test('el texto genérico tampoco usa voseo', () {
      final m = motivoDe(null);
      for (final texto in [m.titulo, m.quePaso, m.queHacer]) {
        expect(_voseo.hasMatch(texto), isFalse);
      }
    });

    for (final codigo in _codigosSinTextoPropio) {
      test('$codigo (del backend, sin texto propio todavía) no rompe y muestra el mensaje del servidor', () {
        final m = motivoDe(codigo, mensajeServidor: 'Mensaje del servidor');
        expect(m.titulo, isNotEmpty);
        expect(m.queHacer, isNotEmpty);
        expect(m.quePaso, isNotEmpty);
      });
    }
  });

  group('MotivoSync', () {
    test('es un valor constante con sus tres textos', () {
      const m = MotivoSync(titulo: 'a', quePaso: 'b', queHacer: 'c');
      expect(m.titulo, 'a');
      expect(m.quePaso, 'b');
      expect(m.queHacer, 'c');
    });
  });
}
