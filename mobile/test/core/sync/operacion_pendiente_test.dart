import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/sync/operacion_pendiente.dart';

void main() {
  group('EstadoOperacion: nombres de cable', () {
    test('cada estado usa el nombre que guarda la base y que manda el servidor', () {
      expect(EstadoOperacion.registrada.nombre, 'registrada');
      expect(EstadoOperacion.enviada.nombre, 'enviada');
      expect(EstadoOperacion.confirmada.nombre, 'confirmada');
      expect(EstadoOperacion.rechazada.nombre, 'rechazada');
      expect(EstadoOperacion.enConflicto.nombre, 'en_conflicto');
    });

    test('hay exactamente cinco estados', () {
      expect(EstadoOperacion.values, hasLength(5));
    });

    test('desdeNombre devuelve el estado de cada nombre', () {
      for (final estado in EstadoOperacion.values) {
        expect(EstadoOperacion.desdeNombre(estado.nombre), estado);
      }
    });

    test('desdeNombre devuelve null con un nombre desconocido, vacío o nulo', () {
      expect(EstadoOperacion.desdeNombre('pendiente'), isNull);
      expect(EstadoOperacion.desdeNombre(''), isNull);
      expect(EstadoOperacion.desdeNombre(null), isNull);
      expect(EstadoOperacion.desdeNombre('Registrada'), isNull);
      expect(EstadoOperacion.desdeNombre('enConflicto'), isNull);
    });
  });

  group('EstadoOperacion: esFinal, seEnvia, estaPendiente', () {
    test('solo confirmada y rechazada son finales', () {
      expect(EstadoOperacion.confirmada.esFinal, isTrue);
      expect(EstadoOperacion.rechazada.esFinal, isTrue);
      expect(EstadoOperacion.registrada.esFinal, isFalse);
      expect(EstadoOperacion.enviada.esFinal, isFalse);
      expect(EstadoOperacion.enConflicto.esFinal, isFalse);
    });

    test('solo registrada y enviada se envían', () {
      expect(EstadoOperacion.registrada.seEnvia, isTrue);
      expect(EstadoOperacion.enviada.seEnvia, isTrue);
      expect(EstadoOperacion.confirmada.seEnvia, isFalse);
      expect(EstadoOperacion.rechazada.seEnvia, isFalse);
      expect(EstadoOperacion.enConflicto.seEnvia, isFalse);
    });

    test('estaPendiente es lo contrario de esFinal', () {
      for (final estado in EstadoOperacion.values) {
        expect(estado.estaPendiente, !estado.esFinal, reason: estado.nombre);
      }
    });
  });

  group('EstadoOperacion.puedePasarA: la tabla completa de transiciones', () {
    const validas = <EstadoOperacion, Set<EstadoOperacion>>{
      EstadoOperacion.registrada: {EstadoOperacion.enviada},
      EstadoOperacion.enviada: {
        EstadoOperacion.registrada,
        EstadoOperacion.confirmada,
        EstadoOperacion.rechazada,
        EstadoOperacion.enConflicto,
      },
      EstadoOperacion.enConflicto: {EstadoOperacion.confirmada, EstadoOperacion.rechazada},
      EstadoOperacion.confirmada: <EstadoOperacion>{},
      EstadoOperacion.rechazada: <EstadoOperacion>{},
    };

    for (final origen in EstadoOperacion.values) {
      for (final destino in EstadoOperacion.values) {
        final esperado = validas[origen]!.contains(destino);
        test('${origen.nombre} → ${destino.nombre}: ${esperado ? 'permitida' : 'prohibida'}', () {
          expect(origen.puedePasarA(destino), esperado);
        });
      }
    }

    test('ninguna transición lleva de un estado a sí mismo', () {
      for (final estado in EstadoOperacion.values) {
        expect(estado.puedePasarA(estado), isFalse, reason: estado.nombre);
      }
    });

    test('desde un estado final no se sale a ninguno', () {
      for (final final_ in [EstadoOperacion.confirmada, EstadoOperacion.rechazada]) {
        for (final destino in EstadoOperacion.values) {
          expect(final_.puedePasarA(destino), isFalse);
        }
      }
    });
  });

  group('TipoOperacion', () {
    test('nombres de cable', () {
      expect(TipoOperacion.ventaContado.nombre, 'venta_contado');
      expect(TipoOperacion.reserva.nombre, 'reserva');
    });

    test('desdeNombre', () {
      expect(TipoOperacion.desdeNombre('venta_contado'), TipoOperacion.ventaContado);
      expect(TipoOperacion.desdeNombre('reserva'), TipoOperacion.reserva);
      expect(TipoOperacion.desdeNombre('devolucion'), isNull);
      expect(TipoOperacion.desdeNombre(null), isNull);
    });
  });

  group('OperacionPendiente.codigoCorto', () {
    OperacionPendiente conId(String id) => OperacionPendiente(
      operacionId: id,
      empresaId: 1,
      sucursalId: 1,
      usuarioId: 1,
      tipo: TipoOperacion.ventaContado,
      estado: EstadoOperacion.registrada,
      payload: '{}',
      versionContrato: 1,
      intentos: 0,
      fechaOperacion: DateTime.utc(2026, 10, 31),
      creadaEn: DateTime.utc(2026, 10, 31),
    );

    test('son los primeros ocho caracteres', () {
      expect(conId('0123456789abcdef').codigoCorto, '01234567');
    });

    test('un id corto se devuelve entero', () {
      expect(conId('abc').codigoCorto, 'abc');
      expect(conId('12345678').codigoCorto, '12345678');
    });
  });
}
