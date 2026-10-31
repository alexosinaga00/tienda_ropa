import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/network/providers.dart';
import '../../auth/state/auth_controller.dart';
import '../data/voz_repository.dart';

/// Sin sesión usa la ruta pública de la tienda elegida; con sesión, la empresa sale del token.
final vozRepositoryProvider = Provider<VozRepository>((ref) {
  final invitado = !ref.watch(authControllerProvider.select((s) => s.estaAutenticado));
  return VozRepository(ref.watch(apiClientProvider), invitado: invitado);
});
