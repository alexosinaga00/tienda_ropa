/// La URL de la API nunca va hardcodeada: siempre viene de --dart-define.
///
/// Ejemplos:
///   flutter run --dart-define=API_URL=http://10.0.2.2:8000/api/v1
///   flutter build apk --dart-define=API_URL=https://backend-production-0714.up.railway.app/api/v1
///
/// El valor por defecto (10.0.2.2) es el alias que usa el emulador de
/// Android para llegar al localhost de la máquina host; en un dispositivo
/// físico o iOS hay que pasar la URL real explícitamente.
class ApiConfig {
  static const String baseUrl = String.fromEnvironment(
    'API_URL',
    defaultValue: 'http://10.0.2.2:8000/api/v1',
  );
}
