/* eslint-disable no-undef */
/**
 * Service Worker de los avisos push (Firebase Cloud Messaging). Es DISTINTO del de Angular (ngsw-worker.js, alcance `/`):
 * se registra con su propio alcance, `/firebase-cloud-messaging-push-scope` (ver core/push/firebase-mensajeria.ts), y
 * ngsw-config.json lo deja fuera del precaché. No guarda NADA en caché: solo muestra avisos y abre pantallas.
 *
 * La configuración de Firebase de abajo es PÚBLICA (identificadores del proyecto web, sin secretos). Un Service Worker
 * no puede importar los módulos de la app: si cambia la de src/environments/environment*.ts, cambia aquí también.
 * La versión del SDK debe ser la misma que la del paquete `firebase` de package.json.
 */

// El clic en un aviso se registra PRIMERO y corta la propagación: así el manejador del SDK (que solo abre un enlace si
// el mensaje trae `fcmOptions.link`) no se ejecuta además del nuestro.
self.addEventListener('notificationclick', (evento) => {
  evento.stopImmediatePropagation();
  evento.notification.close();
  const ruta = rutaDeAviso(datosDe(evento.notification));
  evento.waitUntil(abrirOEnfocar(ruta));
});

importScripts('https://www.gstatic.com/firebasejs/12.19.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/12.19.0/firebase-messaging-compat.js');

firebase.initializeApp({
  apiKey: 'AIzaSyD5Abdyrk39LlMGFNbILH1rvEAu-W14r0Q',
  authDomain: 'fashionstore-96071.firebaseapp.com',
  projectId: 'fashionstore-96071',
  storageBucket: 'fashionstore-96071.firebasestorage.app',
  messagingSenderId: '337599112866',
  appId: '1:337599112866:web:a9ebcfad3643e6d06399fb',
  measurementId: 'G-WREYL37TDS',
});

// Basta con crear la instancia: el SDK escucha los mensajes en segundo plano y, cuando el mensaje trae el bloque
// `notification` (título y cuerpo), el navegador/SDK ya muestra el aviso. NO se muestra otro a mano para no duplicarlo.
// (Con la pestaña abierta el aviso lo maneja la app con `onMessage`.)
firebase.messaging();

/** Los datos del mensaje: el SDK los guarda dentro de `data.FCM_MSG` cuando él mostró el aviso. */
function datosDe(notificacion) {
  const data = notificacion.data || {};
  const mensaje = data.FCM_MSG;
  return (mensaje && mensaje.data) || data;
}

/**
 * A qué pantalla lleva cada tipo de aviso (la misma tabla que core/push/push-rutas.ts):
 * compra, envío, pedido sin conexión y reembolso -> la compra; reserva preparada -> sus reservas; y para el personal,
 * reserva -> /reservas y sincronizacion -> /sincronizacion. Un tipo desconocido abre la portada de la tienda.
 */
function rutaDeAviso(datos) {
  const tipo = datos.tipo;
  const id = datos.referencia_id;
  const tienda = datos.empresa_codigo ? '/t/' + encodeURIComponent(datos.empresa_codigo) : null;
  switch (tipo) {
    case 'compra_confirmada':
    case 'envio':
    case 'pedido_diferido':
    case 'reembolso':
      return tienda && /^\d+$/.test(String(id)) ? tienda + '/mis-compras/' + id : tienda || '/';
    case 'reserva_preparada':
      return tienda ? tienda + '/mis-reservas' : '/';
    case 'reserva':
      return '/reservas';
    case 'sincronizacion':
      return '/sincronizacion';
    default:
      return tienda || '/';
  }
}

/** Enfoca una pestaña de la app que ya esté abierta (y la lleva a la ruta) o abre una nueva. */
async function abrirOEnfocar(ruta) {
  const destino = new URL(ruta, self.location.origin).href;
  const ventanas = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  for (const ventana of ventanas) {
    if (new URL(ventana.url).origin !== self.location.origin) continue;
    try {
      if ('navigate' in ventana) await ventana.navigate(destino);
    } catch (error) {
      // Una pestaña que no se deja navegar se enfoca igual.
    }
    return ventana.focus();
  }
  return self.clients.openWindow(destino);
}
