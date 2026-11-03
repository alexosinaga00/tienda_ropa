import 'package:uuid/uuid.dart';

/// Genera los identificadores de operación (UUID v4, en minúscula). Se inyecta para fijarlos en las pruebas.
abstract interface class GeneradorUuid {
  String nuevo();
}

class GeneradorUuidV4 implements GeneradorUuid {
  const GeneradorUuidV4();

  @override
  String nuevo() => const Uuid().v4().toLowerCase();
}
