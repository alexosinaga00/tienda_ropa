import { HttpClient, HttpContext } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';
import { environment } from '../../environments/environment';
import { SIN_TOAST_ERROR } from './http-contexts';
import { Notificacion } from './models/notificaciones.models';

/**
 * Estado de notificaciones con signals. No arranca el polling por su
 * cuenta -- lo controla `LayoutComponent` (ngOnInit/ngOnDestroy), para que
 * se detenga solo si el usuario navega fuera del back office o cierra
 * sesión, en vez de seguir pegándole a la API en segundo plano para
 * siempre (este servicio es `providedIn: 'root'`, vive toda la sesión).
 */
@Injectable({ providedIn: 'root' })
export class NotificacionesService {
  private readonly http = inject(HttpClient);
  private readonly lista = signal<Notificacion[]>([]);

  readonly notificaciones = this.lista.asReadonly();
  readonly noLeidas = computed(() => this.lista().filter((n) => !n.leida).length);

  /** `silencioso`: si la consulta falla (p. ej. el servidor no las entrega a ese usuario) no se abre el aviso de error. */
  cargar(silencioso = false): Observable<Notificacion[]> {
    return this.http
      .get<Notificacion[]>(`${environment.apiUrl}/notificaciones`, {
        context: silencioso ? new HttpContext().set(SIN_TOAST_ERROR, true) : undefined,
      })
      .pipe(tap((notificaciones) => this.lista.set(notificaciones)));
  }

  /** Las del tipo indicado (p. ej. `pedido_diferido` para el cliente). */
  deTipo(tipo: string): Notificacion[] {
    return this.lista().filter((n) => n.tipo === tipo);
  }

  marcarLeida(notificacionId: number): Observable<Notificacion> {
    return this.http
      .put<Notificacion>(`${environment.apiUrl}/notificaciones/${notificacionId}/leida`, {})
      .pipe(
        tap((actualizada) => {
          this.lista.update((actual) => actual.map((n) => (n.id === actualizada.id ? actualizada : n)));
        }),
      );
  }
}
