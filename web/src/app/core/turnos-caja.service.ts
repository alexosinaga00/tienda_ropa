import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { SIN_TOAST_ERROR } from './http-contexts';
import type {
  CompletarConteo,
  ConsultaTurnos,
  EstadoCajaSucursal,
  Turno,
  TurnoAbrir,
  TurnoActual,
  TurnoCerrar,
  TurnoDetalle,
} from './models/caja.models';

/** El backend limita `tamanio` a 100. */
export const TAMANIO_PAGINA_TURNOS = 20;

/**
 * Cierre de caja por turno (`/api/v1/caja`). La caja es de la sucursal. Los errores los muestra cada pantalla junto a
 * lo que la persona estaba haciendo (el diálogo de cierre, la barra de turno, la tabla): por eso van sin el aviso global.
 *
 * Un cajero NO manda `sucursal_id` (usa la suya); el administrador, que tiene alcance global, DEBE mandarla.
 */
@Injectable({ providedIn: 'root' })
export class TurnosCajaService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiUrl}/caja`;
  private readonly sinAviso = () => new HttpContext().set(SIN_TOAST_ERROR, true);

  /** El turno abierto de la sucursal (o null) y el monto inicial que se sugiere. Permiso `ventas.presencial`. */
  actual(sucursalId?: number | null): Observable<TurnoActual> {
    let params = new HttpParams();
    if (sucursalId != null) params = params.set('sucursal_id', sucursalId);
    return this.http.get<TurnoActual>(`${this.base}/turnos/actual`, { params, context: this.sinAviso() });
  }

  /** Abre el turno con el monto inicial. 409 `turno_ya_abierto` si la sucursal ya tiene uno. */
  abrir(datos: TurnoAbrir): Observable<Turno> {
    return this.http.post<Turno>(`${this.base}/turnos`, datos, { context: this.sinAviso() });
  }

  /** Cierra el turno contando el efectivo. Devuelve el esperado, la diferencia y el resumen. */
  cerrar(turnoId: number, datos: TurnoCerrar): Observable<Turno> {
    return this.http.post<Turno>(`${this.base}/turnos/${turnoId}/cerrar`, datos, { context: this.sinAviso() });
  }

  /** "Cajas de hoy": una por sucursal que la persona puede ver. Permiso `caja.supervisar`. */
  estado(): Observable<EstadoCajaSucursal[]> {
    return this.http.get<EstadoCajaSucursal[]>(`${this.base}/turnos/estado`, { context: this.sinAviso() });
  }

  /** Historial de turnos, el más reciente primero. Permiso `caja.supervisar`. */
  listar(consulta: ConsultaTurnos = {}): Observable<Turno[]> {
    let params = new HttpParams()
      .set('pagina', consulta.pagina ?? 1)
      .set('tamanio', consulta.tamanio ?? TAMANIO_PAGINA_TURNOS);
    if (consulta.sucursal_id != null) params = params.set('sucursal_id', consulta.sucursal_id);
    if (consulta.estado) params = params.set('estado', consulta.estado);
    if (consulta.desde) params = params.set('desde', consulta.desde);
    if (consulta.hasta) params = params.set('hasta', consulta.hasta);
    return this.http.get<Turno[]>(`${this.base}/turnos`, { params, context: this.sinAviso() });
  }

  /** El turno con su ajuste posterior y los reembolsos en efectivo. Permiso `caja.supervisar`. */
  detalle(turnoId: number): Observable<TurnoDetalle> {
    return this.http.get<TurnoDetalle>(`${this.base}/turnos/${turnoId}`, { context: this.sinAviso() });
  }

  /** Un supervisor cuenta el cajón de un turno que se cerró solo (una vez, dentro de 72 horas). */
  completarConteo(turnoId: number, datos: CompletarConteo): Observable<Turno> {
    return this.http.post<Turno>(`${this.base}/turnos/${turnoId}/completar-conteo`, datos, {
      context: this.sinAviso(),
    });
  }
}
