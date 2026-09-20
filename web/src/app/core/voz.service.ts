import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';

// La Web Speech API no es estándar: Chrome y Edge la exponen (con prefijo
// webkit) y Firefox no. `lib.dom` de TypeScript no declara `SpeechRecognition`
// ni `webkitSpeechRecognition`, así que se tipa solo lo que se usa.
interface ReconocimientoVoz {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((evento: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((evento: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  abort(): void;
}

type ConstructorReconocimiento = new () => ReconocimientoVoz;

const MENSAJE_SIN_PERMISO = 'El navegador no tiene permiso para usar el micrófono. Permitilo e intentá de nuevo.';

const MENSAJES_ERROR: Record<string, string> = {
  'not-allowed': MENSAJE_SIN_PERMISO,
  'service-not-allowed': MENSAJE_SIN_PERMISO,
  'no-speech': 'No se escuchó nada. Intentá de nuevo.',
  'audio-capture': 'No se encontró un micrófono.',
  network: 'El reconocimiento de voz necesita conexión a internet.',
};

/** Dictado por voz del navegador (Web Speech API), en español de Bolivia. */
@Injectable({ providedIn: 'root' })
export class VozService {
  private readonly reconocimiento: ConstructorReconocimiento | null = (() => {
    const ventana = window as unknown as {
      SpeechRecognition?: ConstructorReconocimiento;
      webkitSpeechRecognition?: ConstructorReconocimiento;
    };
    return ventana.SpeechRecognition ?? ventana.webkitSpeechRecognition ?? null;
  })();

  /** false en navegadores sin la API (p. ej. Firefox): se ofrece solo el texto. */
  readonly disponible = this.reconocimiento !== null;

  /**
   * Escucha una frase y la emite. Si no se entendió nada completa sin emitir.
   * Cancelar la suscripción corta el micrófono.
   */
  escuchar(): Observable<string> {
    return new Observable<string>((suscriptor) => {
      if (this.reconocimiento === null) {
        suscriptor.error(new Error('Tu navegador no permite dictar. Escribí la pregunta.'));
        return undefined;
      }

      const dictado = new this.reconocimiento();
      dictado.lang = 'es-BO';
      dictado.continuous = false;
      dictado.interimResults = false;
      dictado.maxAlternatives = 1;

      let texto = '';
      dictado.onresult = (evento) => {
        texto = evento.results[0]?.[0]?.transcript?.trim() ?? '';
      };
      dictado.onerror = (evento) => {
        suscriptor.error(new Error(MENSAJES_ERROR[evento.error] ?? 'No se pudo usar el micrófono.'));
      };
      dictado.onend = () => {
        if (texto) suscriptor.next(texto);
        suscriptor.complete();
      };

      try {
        dictado.start();
      } catch {
        suscriptor.error(new Error('No se pudo usar el micrófono.'));
      }
      return () => dictado.abort();
    });
  }
}
