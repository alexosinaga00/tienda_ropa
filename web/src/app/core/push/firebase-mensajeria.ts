import { InjectionToken } from '@angular/core';
import { environment } from '../../../environments/environment';

/** Archivo y alcance del Service Worker de Firebase. El alcance es PROPIO para no pelear con el de Angular (ngsw, `/`). */
export const RUTA_SW_FIREBASE = '/firebase-messaging-sw.js';
export const ALCANCE_SW_FIREBASE = '/firebase-cloud-messaging-push-scope';

/** Lo que llega de FCM mientras la pestaña está abierta. */
export interface MensajePush {
  notification?: { title?: string; body?: string } | null;
  data?: Record<string, string> | null;
}

/**
 * Lo único que la app usa de Firebase. Se carga con `import()` desde `crearMensajeriaFirebase` (el SDK no entra en el
 * paquete inicial) y las pruebas lo sustituyen con el token `MENSAJERIA_PUSH` (nunca se llama a Firebase de verdad).
 */
export interface MensajeriaPush {
  /** Registra el Service Worker de Firebase con su alcance propio. */
  registrarServiceWorker(): Promise<ServiceWorkerRegistration>;
  /** Pide (o renueva) el token de este navegador. Falla si no hay permiso. */
  obtenerToken(registro: ServiceWorkerRegistration): Promise<string>;
  /** Anula el token en Firebase. */
  borrarToken(): Promise<boolean>;
  /** Escucha los mensajes recibidos con la pestaña abierta; devuelve la función para dejar de escuchar. */
  alRecibir(escuchar: (mensaje: MensajePush) => void): Promise<() => void>;
  /** ¿Este navegador puede recibir push con Firebase? */
  soportado(): Promise<boolean>;
}

export const MENSAJERIA_PUSH = new InjectionToken<() => Promise<MensajeriaPush>>('MENSAJERIA_PUSH', {
  providedIn: 'root',
  factory: () => crearMensajeriaFirebase,
});

/** Una sola instancia: `getToken` y `onMessage` deben usar la misma `Messaging`. */
let instancia: Promise<MensajeriaPush> | null = null;

export function crearMensajeriaFirebase(): Promise<MensajeriaPush> {
  instancia ??= cargar();
  return instancia;
}

async function cargar(): Promise<MensajeriaPush> {
  const [{ getApp, getApps, initializeApp }, mensajeria] = await Promise.all([
    import('firebase/app'),
    import('firebase/messaging'),
  ]);
  const aplicacion = getApps().length > 0 ? getApp() : initializeApp(environment.firebase);
  let mensajes: ReturnType<typeof mensajeria.getMessaging> | null = null;
  const obtener = () => (mensajes ??= mensajeria.getMessaging(aplicacion));

  return {
    soportado: () => mensajeria.isSupported(),
    registrarServiceWorker: () =>
      navigator.serviceWorker.register(RUTA_SW_FIREBASE, { scope: ALCANCE_SW_FIREBASE }),
    obtenerToken: (registro) =>
      mensajeria.getToken(obtener(), {
        vapidKey: environment.firebaseVapidKey,
        serviceWorkerRegistration: registro,
      }),
    borrarToken: () => mensajeria.deleteToken(obtener()),
    alRecibir: async (escuchar) => mensajeria.onMessage(obtener(), (mensaje) => escuchar(mensaje as MensajePush)),
  };
}
