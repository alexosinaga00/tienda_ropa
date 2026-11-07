import { DatePipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { ConectividadService } from '../../../core/conectividad.service';
import { MetodoPagoPaypal } from '../../../core/models/metodo-pago.models';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { MetodoPagoService, mensajeErrorMetodoPago } from '../data/metodo-pago.service';
import { MetodoPagoLocalService } from '../state/metodo-pago-local.service';
import { MiCuentaPestanasComponent } from './mi-cuenta-pestanas.component';

/**
 * Mi cuenta > Método de pago. PayPal guarda el medio de pago; aquí solo se ve si hay uno guardado (con el correo
 * enmascarado que manda el servidor), se inicia el guardado (el cliente va a PayPal y vuelve a
 * `mi-cuenta/paypal-guardado`) y se quita. Guardar y quitar necesitan conexión; ver el estado, no (se muestra lo que se
 * recordó la última vez).
 */
@Component({
  selector: 'app-metodo-pago',
  standalone: true,
  imports: [DatePipe, IconoComponent, MiCuentaPestanasComponent],
  templateUrl: './metodo-pago.component.html',
  styleUrl: './metodo-pago.component.scss',
})
export class MetodoPagoComponent implements OnInit {
  private readonly api = inject(MetodoPagoService);
  private readonly local = inject(MetodoPagoLocalService);
  private readonly conectividad = inject(ConectividadService);

  /** Lo que dijo el servidor en esta visita. */
  protected readonly estado = signal<MetodoPagoPaypal | null>(null);
  protected readonly cargando = signal(true);
  protected readonly error = signal<string | null>(null);
  protected readonly guardando = signal(false);
  protected readonly quitando = signal(false);
  protected readonly confirmandoQuitar = signal(false);

  protected readonly sinConexion = computed(() => this.conectividad.estado() !== 'en_linea');
  /** Lo del servidor y, si no se pudo preguntar, lo que se recordó la última vez. */
  protected readonly vista = computed<MetodoPagoPaypal | null>(() => this.estado() ?? this.local.recordado());
  /** Verdadero si lo que se ve es lo recordado y no lo confirmado ahora. */
  protected readonly esRecordado = computed(() => this.estado() === null && this.local.recordado() !== null);

  ngOnInit(): void {
    this.cargar();
  }

  protected cargar(): void {
    this.cargando.set(true);
    this.error.set(null);
    this.api.estado().subscribe({
      next: (estado) => {
        this.estado.set(estado);
        this.cargando.set(false);
        void this.local.recordar(estado);
      },
      error: (error: unknown) => {
        this.cargando.set(false);
        // Sin conexión no es un error de la pantalla: se muestra lo recordado y el aviso de arriba.
        if (!this.sinConexion()) this.error.set(mensajeErrorMetodoPago(error));
      },
    });
  }

  protected guardar(): void {
    if (this.sinConexion() || this.guardando()) return;
    this.guardando.set(true);
    this.error.set(null);
    this.api.iniciar('web').subscribe({
      next: (respuesta) => {
        if (!/^https?:\/\//i.test(respuesta.url_aprobacion)) {
          this.guardando.set(false);
          this.error.set('No pudimos abrir PayPal. Prueba de nuevo en unos minutos.');
          return;
        }
        this.redirigir(respuesta.url_aprobacion);
      },
      error: (error: unknown) => {
        this.guardando.set(false);
        this.error.set(mensajeErrorMetodoPago(error));
      },
    });
  }

  protected pedirQuitar(): void {
    if (this.sinConexion()) return;
    this.confirmandoQuitar.set(true);
  }

  protected cancelarQuitar(): void {
    this.confirmandoQuitar.set(false);
  }

  protected quitar(): void {
    if (this.sinConexion() || this.quitando()) return;
    this.quitando.set(true);
    this.error.set(null);
    this.api.quitar().subscribe({
      next: () => {
        const vacio: MetodoPagoPaypal = { guardado: false, correo_paypal: null, guardado_en: null };
        this.estado.set(vacio);
        void this.local.recordar(vacio);
        this.quitando.set(false);
        this.confirmandoQuitar.set(false);
      },
      error: (error: unknown) => {
        this.quitando.set(false);
        this.confirmandoQuitar.set(false);
        this.error.set(mensajeErrorMetodoPago(error));
      },
    });
  }

  /** Va a la página de aprobación de PayPal (en una prueba se reemplaza). */
  protected redirigir(url: string): void {
    window.location.assign(url);
  }
}
