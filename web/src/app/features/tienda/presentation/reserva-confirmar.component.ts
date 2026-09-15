import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';import { HorarioSucursal, Sucursal } from '../../../core/models/organizacion.models';
import { ReservaCrear } from '../../../core/models/reservas.models';
import { DisponibilidadService } from '../data/disponibilidad.service';
import { ReservasClienteService } from '../data/reservas.service';
import { ReservaCarritoService } from '../state/reserva-carrito.service';

function aIso(fecha: Date): string {
  const y = fecha.getFullYear();
  const m = String(fecha.getMonth() + 1).padStart(2, '0');
  const d = String(fecha.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

@Component({
  selector: 'app-reserva-confirmar',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './reserva-confirmar.component.html',
  styleUrl: './reserva-confirmar.component.scss',
})
export class ReservaConfirmarComponent implements OnInit {
  protected readonly reservaCarritoService = inject(ReservaCarritoService);
  private readonly disponibilidadService = inject(DisponibilidadService);
  private readonly reservasService = inject(ReservasClienteService);
  private readonly router = inject(Router);

  protected readonly sucursales = signal<Sucursal[]>([]);
  protected readonly cargandoSucursales = signal(true);
  protected readonly sucursalId = signal<number | null>(null);
  protected readonly horarios = signal<HorarioSucursal[]>([]);
  protected readonly cargandoHorarios = signal(false);

  protected readonly fecha = signal('');
  protected readonly horaDesde = signal('');
  protected readonly horaHasta = signal('');
  protected readonly enviando = signal(false);
  protected readonly error = signal<string | null>(null);

  protected readonly minFecha = aIso(new Date(Date.now() + 24 * 60 * 60 * 1000));
  protected readonly maxFecha = aIso(new Date(Date.now() + 60 * 24 * 60 * 60 * 1000));

  protected readonly horarioDelDia = computed(() => {
    const fecha = this.fecha();
    if (!fecha) return null;
    const diaSemanaJs = new Date(`${fecha}T00:00:00`).getDay();
    const diaSemanaIso = diaSemanaJs === 0 ? 7 : diaSemanaJs;
    return this.horarios().find((h) => h.dia_semana === diaSemanaIso) ?? null;
  });

  protected readonly errorFranja = computed(() => {
    const horario = this.horarioDelDia();
    const desde = this.horaDesde();
    const hasta = this.horaHasta();
    if (!horario || !desde || !hasta) return null;
    const apertura = horario.hora_apertura.slice(0, 5);
    const cierre = horario.hora_cierre.slice(0, 5);
    if (desde < apertura || hasta > cierre) {
      return `La franja tiene que estar dentro de ${apertura} - ${cierre}.`;
    }
    if (hasta <= desde) {
      return 'La hora de salida tiene que ser después de la de llegada.';
    }
    return null;
  });

  protected readonly listoParaConfirmar = computed(
    () =>
      !this.enviando() &&
      this.reservaCarritoService.cantidad() > 0 &&
      this.sucursalId() !== null &&
      this.fecha() !== '' &&
      this.horarioDelDia() !== null &&
      this.horaDesde() !== '' &&
      this.horaHasta() !== '' &&
      this.errorFranja() === null,
  );

  ngOnInit(): void {
    if (this.reservaCarritoService.cantidad() === 0) {
      this.router.navigate(['/catalogo']);
      return;
    }
    const lineas = this.reservaCarritoService.lista().map((item) => ({ varianteId: item.varianteId, cantidad: 1 }));
    this.disponibilidadService.sucursalesConStock(lineas).subscribe({
      next: (sucursales) => {
        // En un depósito no se reserva: no recibe clientes.
        this.sucursales.set(sucursales.filter((s) => !s.es_deposito));
        this.cargandoSucursales.set(false);
      },
      error: () => this.cargandoSucursales.set(false),
    });
  }

  elegirSucursal(id: number): void {
    this.sucursalId.set(id);
    this.fecha.set('');
    this.horaDesde.set('');
    this.horaHasta.set('');
    this.cargandoHorarios.set(true);
    this.reservasService.horariosSucursal(id).subscribe({
      next: (horarios) => {
        this.horarios.set(horarios);
        this.cargandoHorarios.set(false);
      },
      error: () => this.cargandoHorarios.set(false),
    });
  }

  onFechaChange(valor: string): void {
    this.fecha.set(valor);
    this.horaDesde.set('');
    this.horaHasta.set('');
  }

  quitar(varianteId: number): void {
    this.reservaCarritoService.quitar(varianteId);
  }

  confirmar(): void {
    if (!this.listoParaConfirmar()) return;

    this.enviando.set(true);
    this.error.set(null);
    const datos: ReservaCrear = {
      sucursal_id: this.sucursalId()!,
      fecha_visita: this.fecha(),
      hora_visita_desde: `${this.horaDesde()}:00`,
      hora_visita_hasta: `${this.horaHasta()}:00`,
      detalle: this.reservaCarritoService.lista().map((item) => ({ variante_id: item.varianteId, cantidad: 1 })),
    };

    this.reservasService.crear(datos).subscribe({
      next: () => {
        this.reservaCarritoService.vaciar();
        this.enviando.set(false);
        this.router.navigate(['/mis-reservas']);
      },
      error: () => {
        this.enviando.set(false);
        this.error.set('No se pudo confirmar la reserva. Probá de nuevo.');
      },
    });
  }
}
