// El asistente es el bot de Botpress que ya usa la web. Estas son las mismas dos URLs que `web/src/index.html`
// (el `inject.js` y el archivo de configuración con el botId/clientId, ambos públicos): si el bot se vuelve a
// publicar en Botpress y cambia el archivo de configuración, hay que actualizarlas en los dos lugares.
const urlInjectBotpress = 'https://cdn.botpress.cloud/webchat/v3.7/inject.js';
const urlConfiguracionBotpress = 'https://files.bpcontent.cloud/2026/09/19/19/20260919194522-UDQORGYJ.js';

/// Nombre del canal JavaScript por el que la página le avisa a Flutter, y sus dos mensajes.
const canalAsistente = 'Asistente';
const mensajeListo = 'listo';
const mensajeCerrado = 'cerrado';

/// Página mínima que se carga en el WebView (desde un texto, no desde una URL propia).
///
/// Botpress no dispara `webchat:ready` al cargar sino al abrir el chat por primera vez, así que en cuanto existe
/// `window.botpress` se abre solo, y hasta que llegue `webchat:ready` se vuelve a intentar cada medio segundo.
/// Cerrar el chat desde su "X" avisa con [mensajeCerrado] para que la pantalla se cierre en vez de dejar la burbuja
/// sobre una página vacía.
const paginaAsistente =
    '''
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>html, body { margin: 0; height: 100%; background: #ffffff; }</style>
</head>
<body>
  <script src="$urlInjectBotpress"></script>
  <script src="$urlConfiguracionBotpress" defer></script>
  <script>
    window.addEventListener('load', function () {
      var listo = false;
      var espera = setInterval(function () {
        var bp = window.botpress;
        if (!bp || !bp.on) return;
        clearInterval(espera);
        bp.on('webchat:ready', function () {
          listo = true;
          $canalAsistente.postMessage('$mensajeListo');
        });
        bp.on('webchat:closed', function () {
          $canalAsistente.postMessage('$mensajeCerrado');
        });
        var abrir = setInterval(function () {
          if (listo) { clearInterval(abrir); return; }
          try { bp.open(); } catch (e) {}
        }, 500);
        try { bp.open(); } catch (e) {}
      }, 300);
    });
  </script>
</body>
</html>
''';

const _dominiosBotpress = ['botpress.cloud', 'bpcontent.cloud'];

/// Si el WebView puede navegar a [url]. Solo la propia página y los dominios de Botpress: cualquier otra dirección
/// (un enlace dentro de una respuesta del bot, `javascript:`, `intent:`) se bloquea. Se compara el host completo o
/// con un punto delante, para que `botpress.cloud.otro.com` no pase.
bool navegacionPermitida(String url) {
  final uri = Uri.tryParse(url);
  if (uri == null) return false;
  if (uri.scheme == 'about' || uri.scheme == 'data') return true;
  if (uri.scheme != 'https') return false;
  final host = uri.host.toLowerCase();
  return _dominiosBotpress.any((dominio) => host == dominio || host.endsWith('.$dominio'));
}
