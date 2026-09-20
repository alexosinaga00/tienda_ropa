import { DatePipe, DecimalPipe } from '@angular/common';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ConfirmationService, MessageService } from 'primeng/api';
import { ButtonModule } from 'primeng/button';
import { ConfirmDialogModule } from 'primeng/confirmdialog';
import { DialogModule } from 'primeng/dialog';
import { InputTextModule } from 'primeng/inputtext';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TagModule } from 'primeng/tag';
import { environment } from '../../../environments/environment';
import { EnvioEstadoActualizar, Envio, EstadoEnvio } from '../../core/models/entregas.models';

const TAMANIO_PAGINA = 20;

type Severidad = 'info' | 'warn' | 'success' | 'danger' | 'secondary';

const ETIQUETAS_ESTADO: Record<EstadoEnvio, string> = {
  programado: 'Programado',
  en_ruta: 'En ruta',
  entregado: 'Entregado',
  fallido: 'Fallido',
};

const SEVERIDAD_ESTADO: Record<EstadoEnvio, Severidad> = {
  programado: 'info',
  en_ruta: 'warn',
  entregado: 'success',
  fallido: 'danger',
};

const OPCIONES_ESTADO: { label: string; value: EstadoEnvio | null }[] = [
  { label: 'Todos los estados', value: null },
  { label: 'Programado', value: 'programado' },
  { label: 'En ruta', value: 'en_ruta' },
  { label: 'Entregado', value: 'entregado' },
  { label: 'Fallido', value: 'fallido' },
];

const MENSAJE_EXITO: Record<EstadoEnvio, string> = {
  programado: 'Envío programado',
  en_ruta: 'Envío en ruta',
  entregado: 'Envío entregado',
  fallido: 'Envío marcado como fallido',
};

/**
 * CU-43 — Actualizar estado del envío. El personal (administrador y
 * encargado de sucursal) ve los envíos de su alcance y los hace avanzar:
 * programado → en ruta → entregado, o fallido desde cualquiera de los dos.
 * Las reglas (transiciones, venta pagada, sucursal) las valida el backend;
 * acá solo se ofrecen los botones que tienen sentido para cada estado.
 */
@Component({
  selector: 'app-envios',
  standalone: true,
  imports: [
    DatePipe,
    DecimalPipe,
    FormsModule,
    ButtonModule,
    ConfirmDialogModule,
    DialogModule,
    InputTextModule,
    SelectModule,
    TableModule,
    TagModule,
  ],
  providers: [ConfirmationService],
  templateUrl: './envios.component.html',
  styleUrl: './envios.component.scss',
})
export class EnviosComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly messageService = inject(MessageService);
  private readonly confirmationService = inject(ConfirmationService);

  protected readonly opcionesEstado = OPCIONES_ESTADO;

  protected readonly filas = signal<Envio[]>([]);
  protected readonly cargando = signal(false);
  protected readonly guardando = signal(false);
  protected readonly pagina = signal(1);
  protected readonly hayPaginaSiguiente = signal(false);
  protected readonly filtroEstado = signal<EstadoEnvio | null>(null);

  protected readonly dialogoRutaVisible = signal(false);
  protected readonly envioPorEnviar = signal<Envio | null>(null);
  protected readonly repartidor = signal('');

  ngOnInit(): void {
    this.cargar();
  }

  protected etiquetaEstado(estado: EstadoEnvio): string {
    return ETIQUETAS_ESTADO[estado];
  }

  protected severidadEstado(estado: EstadoEnvio): Severidad {
    return SEVERIDAD_ESTADO[estado];
  }

  protected cambiarFiltro(estado: EstadoEnvio | null): void {
    this.filtroEstado.set(estado);
    this.pagina.set(1);
    this.cargar();
  }

  protected irAPaginaAnterior(): void {
    if (this.pagina() > 1) {
      this.pagina.set(this.pagina() - 1);
      this.cargar();
    }
  }

  protected irAPaginaSiguiente(): void {
    if (this.hayPaginaSiguiente()) {
      this.pagina.set(this.pagina() + 1);
      this.cargar();
    }
  }

  protected cargar(): void {
    let params = new HttpParams().set('pagina', this.pagina()).set('tamanio', TAMANIO_PAGINA);
    const estado = this.filtroEstado();
    if (estado !== null) params = params.set('estado', estado);

    this.cargando.set(true);
    this.http.get<Envio[]>(`${environment.apiUrl}/envios`, { params }).subscribe({
      next: (envios) => {
        this.filas.set(envios);
        this.hayPaginaSiguiente.set(envios.length === TAMANIO_PAGINA);
        this.cargando.set(false);
      },
      error: () => this.cargando.set(false),
    });
  }

  // ---- Acciones ------------------------------------------------------------

  protected abrirEnviar(envio: Envio): void {
    this.envioPorEnviar.set(envio);
    this.repartidor.set(envio.repartidor ?? '');
    this.dialogoRutaVisible.set(true);
  }

  protected confirmarEnviar(): void {
    const envio = this.envioPorEnviar();
    if (envio === null) return;
    this.dialogoRutaVisible.set(false);
    this.cambiarEstado(envio, 'en_ruta', this.repartidor().trim());
  }

  protected pedirConfirmacion(envio: Envio, estado: 'entregado' | 'fallido'): void {
    const entregado = estado === 'entregado';
    this.confirmationService.confirm({
      header: 'Confirmar',
      icon: 'pi pi-exclamation-triangle',
      message: entregado
        ? `¿Marcar el envío #${envio.id} como entregado? La compra pasará a "Entregada".`
        : `¿Marcar el envío #${envio.id} como fallido? Ya no se podrá cambiar.`,
      acceptLabel: entregado ? 'Sí, entregado' : 'Sí, fallido',
      rejectLabel: 'Cancelar',
      accept: () => this.cambiarEstado(envio, estado),
    });
  }

  private cambiarEstado(envio: Envio, estado: EstadoEnvio, repartidor?: string): void {
    const cuerpo: EnvioEstadoActualizar = repartidor ? { estado, repartidor } : { estado };
    this.guardando.set(true);
    this.http.put<Envio>(`${environment.apiUrl}/envios/${envio.id}/estado`, cuerpo).subscribe({
      next: () => {
        this.guardando.set(false);
        this.messageService.add({ severity: 'success', summary: MENSAJE_EXITO[estado] });
        this.cargar(); // con un filtro de estado activo, la fila cambia de lista
      },
      // Los 403/409 del backend (sucursal ajena, venta sin pagar, salto de
      // estado) ya los muestra el manejo global de errores.
      error: () => this.guardando.set(false),
    });
  }
}
