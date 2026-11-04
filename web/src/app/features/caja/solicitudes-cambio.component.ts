import { DatePipe } from '@angular/common';
import { HttpClient, HttpContext, HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, OnInit, inject, input, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MessageService } from 'primeng/api';
import { environment } from '../../../environments/environment';
import { SIN_TOAST_ERROR } from '../../core/http-contexts';
import type { EstadoSolicitudCambio, SolicitudCambio, SolicitudCambioLinea } from '../../core/models/ventas.models';
import { IconoComponent } from '../../shared/icono/icono.component';

type FiltroSolicitudes = 'pendiente' | 'todas';

/** Etiqueta y color del chip de cada estado de una solicitud. */
const ESTADOS: Record<EstadoSolicitudCambio, { texto: string; clase: string }> = {
  pendiente: { texto: 'Pendiente', clase: 'fs-chip--advertencia' },
  aprobada: { texto: 'Aprobada', clase: 'fs-chip--exito' },
  rechazada: { texto: 'Rechazada', clase: 'fs-chip--error' },
  cancelada: { texto: 'Cancelada por el cliente', clase: '' },
  vencida: { texto: 'Vencida', clase: '' },
};

/**
 * Bandeja de solicitudes de cambio de talla o color (CU-17, Etapa 2). El cliente las pide desde su compra; aquí el
 * personal de la sucursal las aprueba o las rechaza cuando el cliente trae la prenda. Aprobar mueve el stock (entra la
 * prenda devuelta y sale la nueva) y envía el comprobante al cliente; el servidor decide si el plazo y el stock lo
 * permiten. Rechazar exige un motivo, que el cliente recibe por correo.
 */
@Component({
  selector: 'app-solicitudes-cambio',
  standalone: true,
  imports: [DatePipe, FormsModule, IconoComponent],
  templateUrl: './solicitudes-cambio.component.html',
  styleUrl: './solicitudes-cambio.component.scss',
})
export class SolicitudesCambioComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly destroyRef = inject(DestroyRef);
  private readonly messageService = inject(MessageService);

  readonly sucursalId = input.required<number>();
  /** Cuántas solicitudes pendientes hay tras cada carga (la Caja lo muestra junto al botón). */
  readonly pendientes = output<number>();

  protected readonly solicitudes = signal<SolicitudCambio[]>([]);
  protected readonly cargando = signal(false);
  protected readonly errorCarga = signal(false);
  protected readonly filtro = signal<FiltroSolicitudes>('pendiente');
  /** La solicitud que se está aprobando o rechazando: bloquea sus botones mientras responde el servidor. */
  protected readonly resolviendo = signal<number | null>(null);
  /** Por solicitud: el motivo con que el servidor no la pudo aprobar (sin stock, plazo vencido, precio cambiado...). */
  protected readonly errores = signal<Record<number, string>>({});
  protected readonly rechazandoId = signal<number | null>(null);
  protected readonly motivoRechazo = signal('');

  ngOnInit(): void {
    this.cargar();
  }

  protected cambiarFiltro(filtro: FiltroSolicitudes): void {
    if (this.filtro() === filtro) return;
    this.filtro.set(filtro);
    this.errores.set({});
    this.cargar();
  }

  /** El botón "Actualizar": vuelve a leer la bandeja y olvida los avisos de intentos anteriores. */
  protected actualizar(): void {
    this.errores.set({});
    this.cargar();
  }

  /** Lee la bandeja. Los avisos de una aprobación que el servidor rechazó se conservan: explican por qué sigue pendiente. */
  private cargar(): void {
    this.cargando.set(true);
    this.errorCarga.set(false);
    const filtro = this.filtro();
    this.http
      .get<SolicitudCambio[]>(`${environment.apiUrl}/solicitudes-cambio/sucursal/${this.sucursalId()}`, {
        params: { estado: filtro },
        context: new HttpContext().set(SIN_TOAST_ERROR, true),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (lista) => {
          this.cargando.set(false);
          this.solicitudes.set(lista);
          this.pendientes.emit(lista.filter((s) => s.estado === 'pendiente').length);
        },
        error: () => {
          this.cargando.set(false);
          this.errorCarga.set(true);
        },
      });
  }

  protected estado(solicitud: SolicitudCambio): { texto: string; clase: string } {
    return ESTADOS[solicitud.estado];
  }

  /** La prenda nueva alcanza para la cantidad pedida (o no se sabe: el servidor decide al aprobar). */
  protected hayStock(linea: SolicitudCambioLinea): boolean {
    return linea.disponible_nueva === null || linea.disponible_nueva >= linea.cantidad;
  }

  protected alcanzaElStock(solicitud: SolicitudCambio): boolean {
    return solicitud.detalle.every((linea) => this.hayStock(linea));
  }

  protected textoDisponible(linea: SolicitudCambioLinea): string {
    const disponible = linea.disponible_nueva ?? 0;
    if (disponible <= 0) return 'Sin stock en la sucursal';
    return disponible >= linea.cantidad ? `Hay ${disponible} en la sucursal` : `Solo hay ${disponible} en la sucursal`;
  }

  protected aprobar(solicitud: SolicitudCambio): void {
    if (this.resolviendo() !== null) return;
    this.resolviendo.set(solicitud.id);
    this.quitarError(solicitud.id);
    this.http
      .post<SolicitudCambio>(`${environment.apiUrl}/solicitudes-cambio/${solicitud.id}/aprobar`, null, {
        context: new HttpContext().set(SIN_TOAST_ERROR, true),
      })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resuelta) => {
          this.resolviendo.set(null);
          this.messageService.add({
            severity: 'success',
            summary: 'Cambio aprobado',
            detail: resuelta.correo_programado
              ? 'Entrega la prenda nueva. Se envió el comprobante al correo del cliente.'
              : 'Entrega la prenda nueva. El cliente no tiene correo: no se envió comprobante.',
          });
          this.cargar();
        },
        error: (error: HttpErrorResponse) => {
          this.resolviendo.set(null);
          this.guardarError(solicitud.id, mensajeDeError(error, 'No se pudo aprobar la solicitud.'));
          // El stock o el plazo pudieron cambiar: se vuelve a leer para que la fila diga la verdad.
          if (error.status === 409) this.cargar();
        },
      });
  }

  protected empezarRechazo(solicitud: SolicitudCambio): void {
    this.rechazandoId.set(solicitud.id);
    this.motivoRechazo.set('');
    this.quitarError(solicitud.id);
  }

  protected cancelarRechazo(): void {
    this.rechazandoId.set(null);
    this.motivoRechazo.set('');
  }

  protected motivoValido(): boolean {
    return this.motivoRechazo().trim().length >= 3;
  }

  protected confirmarRechazo(solicitud: SolicitudCambio): void {
    if (this.resolviendo() !== null || !this.motivoValido()) return;
    this.resolviendo.set(solicitud.id);
    this.http
      .post<SolicitudCambio>(
        `${environment.apiUrl}/solicitudes-cambio/${solicitud.id}/rechazar`,
        { motivo: this.motivoRechazo().trim() },
        { context: new HttpContext().set(SIN_TOAST_ERROR, true) },
      )
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (resuelta) => {
          this.resolviendo.set(null);
          this.cancelarRechazo();
          this.messageService.add({
            severity: 'success',
            summary: 'Solicitud rechazada',
            detail: resuelta.correo_programado
              ? 'Se avisó al cliente por correo con el motivo.'
              : 'El cliente no tiene correo: no se envió aviso.',
          });
          this.cargar();
        },
        error: (error: HttpErrorResponse) => {
          this.resolviendo.set(null);
          this.guardarError(solicitud.id, mensajeDeError(error, 'No se pudo rechazar la solicitud.'));
          if (error.status === 409) {
            this.cancelarRechazo();
            this.cargar();
          }
        },
      });
  }

  private guardarError(id: number, mensaje: string): void {
    this.errores.update((actuales) => ({ ...actuales, [id]: mensaje }));
  }

  private quitarError(id: number): void {
    this.errores.update(({ [id]: _quitado, ...resto }) => resto);
  }
}

/** El texto con que el servidor explicó el error (`detail` en texto, o `detail.mensaje` / `mensaje`). */
function mensajeDeError(error: HttpErrorResponse, porDefecto: string): string {
  const detalle = error.error?.detail;
  if (typeof detalle === 'string' && detalle.trim()) return detalle;
  if (typeof detalle?.mensaje === 'string' && detalle.mensaje.trim()) return detalle.mensaje;
  if (typeof error.error?.mensaje === 'string' && error.error.mensaje.trim()) return error.error.mensaje;
  return error.status === 0 ? 'Sin conexión con el servidor. Inténtalo de nuevo.' : porDefecto;
}
