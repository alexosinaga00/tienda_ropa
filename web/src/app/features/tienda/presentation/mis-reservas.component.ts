import { Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { EstadoReserva, Reserva } from '../../../core/models/reservas.models';
import { IconoComponent } from '../../../shared/icono/icono.component';
import { ReservasClienteService } from '../data/reservas.service';
import { TiendaActualService } from '../state/tienda-actual.service';
import { CLASES_ESTADO_RESERVA, ETIQUETAS_ESTADO_RESERVA } from './estados-reserva';
import { MiCuentaPestanasComponent } from './mi-cuenta-pestanas.component';

@Component({
  selector: 'app-mis-reservas',
  standalone: true,
  imports: [RouterLink, IconoComponent, MiCuentaPestanasComponent],
  templateUrl: './mis-reservas.component.html',
  styleUrl: './mis-reservas.component.scss',
})
export class MisReservasComponent implements OnInit {
  private readonly reservasService = inject(ReservasClienteService);
  protected readonly tienda = inject(TiendaActualService);

  protected readonly reservas = signal<Reserva[]>([]);
  protected readonly cargando = signal(true);
  protected readonly error = signal(false);

  ngOnInit(): void {
    this.cargar();
  }

  protected cargar(): void {
    this.cargando.set(true);
    this.error.set(false);
    this.reservasService.listarMisReservas().subscribe({
      next: (reservas) => {
        this.reservas.set(reservas);
        this.cargando.set(false);
      },
      error: () => {
        this.cargando.set(false);
        this.error.set(true);
      },
    });
  }

  etiquetaEstado(estado: EstadoReserva): string {
    return ETIQUETAS_ESTADO_RESERVA[estado];
  }

  claseEstado(estado: EstadoReserva): string {
    return CLASES_ESTADO_RESERVA[estado];
  }
}
