import { DatePipe, DecimalPipe, NgTemplateOutlet, PercentPipe } from '@angular/common';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonModule } from 'primeng/button';
import { ChartModule } from 'primeng/chart';
import { DatePickerModule } from 'primeng/datepicker';
import { SelectModule } from 'primeng/select';
import { TableModule } from 'primeng/table';
import { TabsModule } from 'primeng/tabs';
import { environment } from '../../../environments/environment';
import { fechaDesdeIso, fechaLocalIso } from '../../core/date-utils';
import { Categoria } from '../../core/models/catalogo.models';
import { Empleado, Sucursal } from '../../core/models/organizacion.models';
import {
  DashboardReportes,
  ReporteInventario,
  ReporteReservas,
  ReporteVentas,
  ReporteVozRespuesta,
} from '../../core/models/reportes.models';
import { PlanService } from '../../core/plan.service';
import { VozService } from '../../core/voz.service';
import { IconoComponent } from '../../shared/icono/icono.component';
import { NombreIcono } from '../../shared/icono/iconos';

type PestaniaReportes = 'dashboard' | 'ventas' | 'inventario' | 'reservas';

/** Tarjeta de indicador: el valor se formatea en la plantilla según su tipo. */
interface Kpi {
  etiqueta: string;
  valor: number;
  tipo: 'monto' | 'entero' | 'porcentaje';
  icono: NombreIcono;
  alerta?: boolean;
}

/**
 * Los gráficos de Chart.js pintan en un canvas y no entienden `var(--fs-*)`:
 * se leen los tokens del documento una vez, con el valor de styles.scss como
 * respaldo (pruebas y renderizado sin estilos).
 */
function token(nombre: string, respaldo: string): string {
  if (typeof document === 'undefined') return respaldo;
  const valor = getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
  return valor || respaldo;
}

/** Columnas de la exportación a CSV: p-table solo exporta lo que declara en `[columns]`. */
const COLUMNAS_CSV_VENTAS = [
  { field: 'fecha', header: 'Fecha' },
  { field: 'codigo', header: 'Código' },
  { field: 'canal', header: 'Canal' },
  { field: 'sucursal', header: 'Sucursal' },
  { field: 'producto', header: 'Producto' },
  { field: 'categoria', header: 'Categoría' },
  { field: 'cantidad', header: 'Cantidad' },
  { field: 'subtotal', header: 'Subtotal' },
  { field: 'margen', header: 'Margen' },
];

const COLUMNAS_CSV_INVENTARIO = [
  { field: 'producto', header: 'Producto' },
  { field: 'sku', header: 'SKU' },
  { field: 'talla', header: 'Talla' },
  { field: 'color', header: 'Color' },
  { field: 'sucursal', header: 'Sucursal' },
  { field: 'cantidad_disponible', header: 'Disponible' },
  { field: 'stock_minimo', header: 'Mínimo' },
  { field: 'valor_inventario', header: 'Valor' },
];

const OPCIONES_CANAL = [
  { label: 'Todos los canales', value: null },
  { label: 'Digital', value: 'digital' },
  { label: 'Presencial', value: 'presencial' },
];

@Component({
  selector: 'app-reportes',
  standalone: true,
  imports: [
    DatePipe,
    DecimalPipe,
    PercentPipe,
    NgTemplateOutlet,
    FormsModule,
    ButtonModule,
    ChartModule,
    DatePickerModule,
    SelectModule,
    TableModule,
    TabsModule,
    IconoComponent,
  ],
  templateUrl: './reportes.component.html',
  styleUrl: './reportes.component.scss',
})
export class ReportesComponent implements OnInit {
  private readonly http = inject(HttpClient);
  private readonly voz = inject(VozService);

  protected readonly opcionesCanal = OPCIONES_CANAL;
  protected readonly columnasCsvVentas = COLUMNAS_CSV_VENTAS;
  protected readonly columnasCsvInventario = COLUMNAS_CSV_INVENTARIO;

  protected readonly pestania = signal<PestaniaReportes>('dashboard');

  // ---- Filtros compartidos ----------------------------------------------------------

  protected readonly sucursales = signal<Sucursal[]>([]);
  protected readonly categorias = signal<Categoria[]>([]);
  protected readonly filtroSucursalId = signal<number | null>(null);
  // Un encargado_sucursal está atado a su sucursal (resuelta vía
  // /empleados/yo, mismo criterio que dashboard.component.ts): el filtro
  // queda fijo, no elige "todas". Un administrador sin registro de
  // empleado sí puede elegir cualquiera o ninguna.
  protected readonly sucursalBloqueada = signal(false);
  protected readonly filtroCategoriaId = signal<number | null>(null);
  protected readonly filtroCanal = signal<string | null>(null);
  protected readonly filtroDesde = signal<Date | null>(null);
  protected readonly filtroHasta = signal<Date | null>(null);

  // ---- Datos por pestaña --------------------------------------------------------------

  protected readonly dashboard = signal<DashboardReportes | null>(null);
  protected readonly cargandoDashboard = signal(false);

  protected readonly ventas = signal<ReporteVentas | null>(null);
  protected readonly cargandoVentas = signal(false);

  protected readonly inventario = signal<ReporteInventario | null>(null);
  protected readonly cargandoInventario = signal(false);

  protected readonly reservas = signal<ReporteReservas | null>(null);
  protected readonly cargandoReservas = signal(false);

  // ---- Indicadores y ranking ------------------------------------------------------------

  protected readonly kpisDashboard = computed<Kpi[]>(() => {
    const d = this.dashboard();
    if (d === null) return [];
    return [
      { etiqueta: 'Ventas del período', valor: d.ventas_del_periodo, tipo: 'monto', icono: 'dinero' },
      { etiqueta: 'Transacciones', valor: d.transacciones, tipo: 'entero', icono: 'carrito' },
      { etiqueta: 'Ticket promedio', valor: d.ticket_promedio, tipo: 'monto', icono: 'etiqueta' },
      { etiqueta: 'Margen bruto', valor: d.margen_bruto, tipo: 'monto', icono: 'grafico' },
      { etiqueta: 'Valor de inventario', valor: d.valor_inventario_total, tipo: 'monto', icono: 'inventario' },
      {
        etiqueta: 'Variantes bajo mínimo',
        valor: d.variantes_bajo_minimo,
        tipo: 'entero',
        icono: 'advertencia',
        alerta: d.variantes_bajo_minimo > 0,
      },
      {
        etiqueta: 'Conversión reservas → ventas',
        valor: d.tasa_conversion_reservas,
        tipo: 'porcentaje',
        icono: 'calendario',
      },
    ];
  });

  protected readonly kpisVentas = computed<Kpi[]>(() => {
    const resumen = this.ventas()?.resumen;
    if (!resumen) return [];
    return [
      { etiqueta: 'Transacciones', valor: resumen.transacciones, tipo: 'entero', icono: 'carrito' },
      { etiqueta: 'Total ventas', valor: resumen.total_ventas, tipo: 'monto', icono: 'dinero' },
      { etiqueta: 'Ticket promedio', valor: resumen.ticket_promedio, tipo: 'monto', icono: 'etiqueta' },
      { etiqueta: 'Margen bruto', valor: resumen.margen_bruto, tipo: 'monto', icono: 'grafico' },
    ];
  });

  protected readonly kpisReservas = computed<Kpi[]>(() => {
    const reporte = this.reservas();
    if (!reporte) return [];
    return [
      { etiqueta: 'Tasa de conversión a venta', valor: reporte.tasa_conversion, tipo: 'porcentaje', icono: 'calendario' },
    ];
  });

  /** Productos más vendidos del dashboard con el ancho de su barra (el primero = 100 %). */
  protected readonly topProductosDashboard = computed(() => {
    const filas = this.dashboard()?.top_productos ?? [];
    const maximo = Math.max(1, ...filas.map((f) => f.cantidad_vendida));
    return filas.map((f) => ({ ...f, ancho: Math.round((f.cantidad_vendida / maximo) * 100) }));
  });

  protected claseEstadoProbador(estado: string): string {
    if (estado === 'completado') return 'fs-chip--exito';
    if (estado === 'fallido') return 'fs-chip--error';
    return 'fs-chip--advertencia';
  }

  // ---- Gráficos (p-chart) --------------------------------------------------------------
  // Paleta del sistema de diseño. Sobre fondo claro la serie principal va en oliva
  // (la lima da ~2,4:1 contra blanco y se reserva para fondos oscuros; aquí solo
  // aparece como un segmento más, con borde). Los estados se escalonan en luminosidad
  // (tinta, oliva/advertencia, gris, lima, neutro) y la leyenda de texto con la cantidad
  // no depende del color. Colores fijos por entidad, nunca por posición.

  private static readonly PALETA = {
    tinta: token('--fs-tinta', '#151515'),
    lima: token('--fs-acento-oscuro', '#8fae5b'),
    oliva: token('--fs-acento', '#5d6b34'),
    neutro: token('--fs-campo-borde', '#c9c2b6'),
    tenue: token('--fs-texto-tenue', '#6b645c'),
    texto: token('--fs-texto', '#161412'),
    advertencia: token('--fs-advertencia', '#a4480a'),
    rejilla: token('--fs-fondo-alt', '#efebe4'),
    superficie: token('--fs-superficie', '#ffffff'),
    carbon: token('--fs-carbon', '#1b1916'),
  };

  private static readonly COLOR_CANAL: Record<string, string> = {
    digital: ReportesComponent.PALETA.oliva,
    presencial: ReportesComponent.PALETA.tinta,
  };
  private static readonly COLOR_ESTADO_RESERVA: Record<string, string> = {
    pendiente: ReportesComponent.PALETA.tenue,
    preparada: ReportesComponent.PALETA.oliva,
    en_prueba: ReportesComponent.PALETA.lima,
    completada: ReportesComponent.PALETA.tinta,
    cancelada: ReportesComponent.PALETA.neutro,
    expirada: ReportesComponent.PALETA.advertencia,
  };
  private static readonly TEXTO = ReportesComponent.PALETA.texto;
  private static readonly TEXTO_TENUE = ReportesComponent.PALETA.tenue;
  private static readonly REJILLA = ReportesComponent.PALETA.rejilla;
  private static readonly FUENTE = { family: 'Public Sans, sans-serif', size: 12 };

  private static readonly TOOLTIP = {
    backgroundColor: ReportesComponent.PALETA.carbon,
    titleFont: { family: 'Public Sans, sans-serif', size: 12, weight: 'bold' as const },
    bodyFont: { family: 'Public Sans, sans-serif', size: 12 },
    padding: 10,
    cornerRadius: 4,
    boxPadding: 4,
  };

  /** Anillo: alto fijo, anillo delgado y leyenda al costado con la cantidad. */
  protected readonly opcionesAnillo = {
    maintainAspectRatio: false,
    cutout: '64%',
    layout: { padding: 8 },
    plugins: {
      legend: {
        position: 'right' as const,
        labels: {
          color: ReportesComponent.TEXTO,
          font: ReportesComponent.FUENTE,
          usePointStyle: true,
          pointStyle: 'circle' as const,
          boxWidth: 8,
          boxHeight: 8,
          padding: 14,
        },
      },
      tooltip: ReportesComponent.TOOLTIP,
    },
  };

  /** Barras finas con extremo redondeado, rejilla suave y sin leyenda (una sola serie). */
  private static opcionesBarras(horizontal: boolean) {
    const ejeValor = {
      beginAtZero: true,
      grid: { color: ReportesComponent.REJILLA },
      border: { display: false },
      ticks: { color: ReportesComponent.TEXTO_TENUE, font: ReportesComponent.FUENTE, precision: 0 },
    };
    const ejeCategoria = {
      grid: { display: false },
      border: { color: ReportesComponent.REJILLA },
      ticks: { color: ReportesComponent.TEXTO_TENUE, font: ReportesComponent.FUENTE, autoSkip: false },
    };
    return {
      maintainAspectRatio: false,
      indexAxis: horizontal ? ('y' as const) : ('x' as const),
      plugins: { legend: { display: false }, tooltip: ReportesComponent.TOOLTIP },
      scales: horizontal ? { x: ejeValor, y: ejeCategoria } : { x: ejeCategoria, y: ejeValor },
    };
  }

  protected readonly opcionesBarrasVerticales = ReportesComponent.opcionesBarras(false);
  protected readonly opcionesBarrasHorizontales = ReportesComponent.opcionesBarras(true);

  private static readonly ESTILO_BARRA = { borderRadius: 2, borderSkipped: 'start' as const, maxBarThickness: 26 };
  private static readonly ESTILO_ANILLO = {
    // Borde blanco grueso: separa los segmentos aunque dos colores se parezcan.
    borderColor: ReportesComponent.PALETA.superficie,
    borderWidth: 3,
    hoverOffset: 6,
  };

  protected readonly chartVentasPorCanal = computed(() => {
    const filas = this.dashboard()?.ventas_por_canal ?? this.ventas()?.por_canal ?? [];
    return {
      labels: filas.map((f) => (f.canal === 'digital' ? 'Digital' : 'Presencial')),
      datasets: [
        {
          data: filas.map((f) => Number(f.total_ventas)),
          backgroundColor: filas.map((f) => ReportesComponent.COLOR_CANAL[f.canal] ?? ReportesComponent.PALETA.neutro),
          ...ReportesComponent.ESTILO_ANILLO,
        },
      ],
    };
  });

  protected readonly chartVentasPorSucursal = computed(() => {
    const filas = this.ventas()?.por_sucursal ?? this.dashboard()?.ventas_por_sucursal ?? [];
    return {
      labels: filas.map((f) => f.sucursal),
      datasets: [
        {
          label: 'Ventas (Bs)',
          data: filas.map((f) => Number(f.total_ventas)),
          backgroundColor: ReportesComponent.PALETA.oliva,
          ...ReportesComponent.ESTILO_BARRA,
        },
      ],
    };
  });

  protected readonly chartTopProductos = computed(() => {
    const filas = this.ventas()?.top_productos ?? this.dashboard()?.top_productos ?? [];
    return {
      labels: filas.map((f) => f.producto),
      datasets: [
        {
          label: 'Cantidad vendida',
          data: filas.map((f) => f.cantidad_vendida),
          backgroundColor: ReportesComponent.PALETA.oliva,
          ...ReportesComponent.ESTILO_BARRA,
        },
      ],
    };
  });

  protected readonly chartReservasPorEstado = computed(() => {
    const filas = this.reservas()?.por_estado ?? this.dashboard()?.reservas_por_estado ?? [];
    return {
      labels: filas.map((f) => f.nombre),
      datasets: [
        {
          data: filas.map((f) => f.cantidad),
          backgroundColor: filas.map(
            (f) => ReportesComponent.COLOR_ESTADO_RESERVA[f.codigo] ?? ReportesComponent.PALETA.tenue,
          ),
          ...ReportesComponent.ESTILO_ANILLO,
        },
      ],
    };
  });

  ngOnInit(): void {
    this.http
      .get<Sucursal[]>(`${environment.apiUrl}/sucursales?pagina=1&tamanio=100`)
      .subscribe((sucursales) => this.sucursales.set(sucursales));
    this.http
      .get<Categoria[]>(`${environment.apiUrl}/categorias?pagina=1&tamanio=100`)
      .subscribe((categorias) => this.categorias.set(categorias));

    this.http.get<Empleado>(`${environment.apiUrl}/empleados/yo`).subscribe({
      next: (empleado) => {
        if (empleado.sucursal_id !== null) {
          this.filtroSucursalId.set(empleado.sucursal_id);
          this.sucursalBloqueada.set(true);
        }
        this.buscarDashboard();
      },
      // Sin registro de empleado (típico de un administrador puro): queda
      // libre para elegir cualquier sucursal, o ninguna (vista global).
      error: () => this.buscarDashboard(),
    });
  }

  cambiarPestania(valor: string): void {
    const pestania = valor as PestaniaReportes;
    this.pestania.set(pestania);
    this.buscarPestaniaActual();
  }

  aplicarFiltros(): void {
    this.buscarPestaniaActual();
  }

  // ---- Preguntar a los reportes (CU-23) ---------------------------------------------------
  // Se dicta o se escribe una pregunta; el backend la interpreta, la responde en español y
  // devuelve los filtros que aplicó. Aquí se muestran esos filtros y la pestaña del reporte,
  // reutilizando las mismas búsquedas de siempre (no se dibuja `resultado` aparte).

  protected readonly vozDisponible = this.voz.disponible;

  private readonly planService = inject(PlanService);
  /** "Pregúntale a la IA" (`/ia/reporte-voz`) exige el plan con reportes_ia: sin él el servidor responde 403. */
  protected readonly incluyeIa = computed(() => this.planService.incluye('reportes_ia'));
  protected readonly pregunta = signal('');
  protected readonly escuchando = signal(false);
  protected readonly preguntando = signal(false);
  protected readonly respuestaVoz = signal<string | null>(null);
  protected readonly errorVoz = signal<string | null>(null);

  protected dictar(): void {
    if (this.escuchando()) return;
    this.errorVoz.set(null);
    this.escuchando.set(true);
    let hayTexto = false;
    this.voz.escuchar().subscribe({
      next: (texto) => {
        hayTexto = true;
        this.pregunta.set(texto);
        this.preguntar(); // un comando de voz se envía solo; el texto queda visible
      },
      error: (error: Error) => {
        this.escuchando.set(false);
        this.errorVoz.set(error.message);
      },
      complete: () => {
        this.escuchando.set(false);
        if (!hayTexto) this.errorVoz.set('No se escuchó nada. Intenta de nuevo.');
      },
    });
  }

  protected preguntar(): void {
    const texto = this.pregunta().trim();
    if (texto === '' || this.preguntando()) return;
    this.errorVoz.set(null);
    this.preguntando.set(true);
    this.http.post<ReporteVozRespuesta>(`${environment.apiUrl}/ia/reporte-voz`, { texto }).subscribe({
      next: (resultado) => {
        this.preguntando.set(false);
        // Un backend anterior no manda `respuesta`: entonces solo se ajustan los filtros.
        this.respuestaVoz.set(resultado.respuesta ?? null);
        this.aplicarRespuesta(resultado);
      },
      // Los 403/429 del backend ya los muestra el manejo global de errores.
      error: () => this.preguntando.set(false),
    });
  }

  private aplicarRespuesta(resultado: ReporteVozRespuesta): void {
    const filtros = resultado.filtros_aplicados;
    this.filtroDesde.set(fechaDesdeIso(filtros.desde));
    this.filtroHasta.set(fechaDesdeIso(filtros.hasta));
    // El encargado ya viene con su sucursal: el backend le devuelve la propia.
    if (!this.sucursalBloqueada()) this.filtroSucursalId.set(filtros.sucursal_id);
    this.filtroCategoriaId.set(filtros.categoria_id);
    this.filtroCanal.set(filtros.canal);
    this.cambiarPestania(resultado.tipo_reporte);
  }

  private buscarPestaniaActual(): void {
    switch (this.pestania()) {
      case 'dashboard':
        this.buscarDashboard();
        break;
      case 'ventas':
        this.buscarVentas();
        break;
      case 'inventario':
        this.buscarInventario();
        break;
      case 'reservas':
        this.buscarReservas();
        break;
    }
  }

  private parametrosPeriodo(): HttpParams {
    let params = new HttpParams();
    if (this.filtroSucursalId() !== null) params = params.set('sucursal_id', this.filtroSucursalId()!);
    if (this.filtroDesde() !== null) params = params.set('desde', fechaLocalIso(this.filtroDesde()!));
    if (this.filtroHasta() !== null) params = params.set('hasta', fechaLocalIso(this.filtroHasta()!));
    return params;
  }

  buscarDashboard(): void {
    this.cargandoDashboard.set(true);
    this.http.get<DashboardReportes>(`${environment.apiUrl}/reportes/dashboard`, { params: this.parametrosPeriodo() }).subscribe({
      next: (datos) => {
        this.dashboard.set(datos);
        this.cargandoDashboard.set(false);
      },
      error: () => this.cargandoDashboard.set(false),
    });
  }

  buscarVentas(): void {
    this.cargandoVentas.set(true);
    let params = this.parametrosPeriodo();
    if (this.filtroCategoriaId() !== null) params = params.set('categoria_id', this.filtroCategoriaId()!);
    if (this.filtroCanal() !== null) params = params.set('canal', this.filtroCanal()!);
    this.http.get<ReporteVentas>(`${environment.apiUrl}/reportes/ventas`, { params }).subscribe({
      next: (datos) => {
        this.ventas.set(datos);
        this.cargandoVentas.set(false);
      },
      error: () => this.cargandoVentas.set(false),
    });
  }

  buscarInventario(): void {
    this.cargandoInventario.set(true);
    let params = new HttpParams();
    if (this.filtroSucursalId() !== null) params = params.set('sucursal_id', this.filtroSucursalId()!);
    this.http.get<ReporteInventario>(`${environment.apiUrl}/reportes/inventario`, { params }).subscribe({
      next: (datos) => {
        this.inventario.set(datos);
        this.cargandoInventario.set(false);
      },
      error: () => this.cargandoInventario.set(false),
    });
  }

  buscarReservas(): void {
    this.cargandoReservas.set(true);
    this.http.get<ReporteReservas>(`${environment.apiUrl}/reportes/reservas`, { params: this.parametrosPeriodo() }).subscribe({
      next: (datos) => {
        this.reservas.set(datos);
        this.cargandoReservas.set(false);
      },
      error: () => this.cargandoReservas.set(false),
    });
  }
}
