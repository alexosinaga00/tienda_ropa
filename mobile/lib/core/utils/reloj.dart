import 'package:flutter_riverpod/flutter_riverpod.dart';

/// La hora actual. Todo lo que depende del tiempo (vigencia de los datos, reintentos) la pide aquí y no a `DateTime.now()`,
/// para fijarla en las pruebas. Siempre en UTC.
abstract interface class Reloj {
  DateTime ahora();
}

class RelojSistema implements Reloj {
  const RelojSistema();

  @override
  DateTime ahora() => DateTime.now().toUtc();
}

final relojProvider = Provider<Reloj>((ref) => const RelojSistema());
