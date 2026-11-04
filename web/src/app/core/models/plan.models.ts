/** Funcionalidades que un plan puede incluir (nombres del backend, `core/planes.py`). */
export type FuncionPlan =
  | 'gestion_productos'
  | 'gestion_ventas'
  | 'reservas'
  | 'reportes_convencionales'
  | 'operacion_offline'
  | 'reportes_ia'
  | 'analitica_ml'
  | 'copias_seguridad';

/** Estado de la suscripción de la empresa de la sesión (`GET /mi-empresa/suscripcion`). */
export type EstadoSuscripcion = 'activa' | 'suspendida' | 'vencida' | 'cancelada' | 'sin_suscripcion';

/** `GET /public/planes`: un plan activo tal como lo ve quien visita la portada (con su precio, sin ids). */
export interface PlanPublico extends Record<FuncionPlan, boolean> {
  codigo: string;
  nombre: string;
  max_sucursales: number;
  max_copias_historial: number;
  plazo_cambio_horas_defecto: number;
  /** Bs por mes, como TEXTO decimal ("120.00"); null = sin precio publicado (no se puede contratar). */
  precio_mensual_bs: string | null;
}

/** `GET /mi-empresa/suscripcion`. */
export interface MiSuscripcion {
  plan_codigo: string | null;
  plan_nombre: string | null;
  estado: EstadoSuscripcion | string;
  fecha_inicio: string | null;
  fecha_vencimiento: string | null;
  max_sucursales: number | null;
  sucursales_activas: number;
  funcionalidades: string[];
}

/** `GET /mi-empresa`. */
export interface MiEmpresa {
  id: number;
  codigo: string;
  nombre: string;
  logo_url: string | null;
  color_acento: string | null;
  activo: boolean;
}

/** `PUT /mi-empresa`: solo la identidad visual. */
export interface MiEmpresaActualizar {
  nombre?: string;
  logo_url?: string | null;
  color_acento?: string | null;
}

export interface DescripcionFuncion {
  id: FuncionPlan;
  etiqueta: string;
  descripcion: string;
}

/** Las 8 funcionalidades, en el orden en que se muestran en "Mi empresa". */
export const FUNCIONES_PLAN: readonly DescripcionFuncion[] = [
  { id: 'gestion_productos', etiqueta: 'Gestión de productos', descripcion: 'Catálogo, categorías, tallas, colores e inventario.' },
  { id: 'gestion_ventas', etiqueta: 'Gestión de ventas', descripcion: 'Ventas en caja, promociones, pagos y envíos.' },
  { id: 'reservas', etiqueta: 'Reservas', descripcion: 'Reservas de prendas para probárselas en sucursal.' },
  { id: 'reportes_convencionales', etiqueta: 'Reportes', descripcion: 'Reportes e indicadores de ventas e inventario.' },
  { id: 'operacion_offline', etiqueta: 'Operación sin conexión', descripcion: 'Vender y reservar sin Internet y sincronizar después.' },
  { id: 'reportes_ia', etiqueta: 'Reportes con IA', descripcion: 'Pide un reporte en lenguaje natural, escrito o por voz.' },
  { id: 'analitica_ml', etiqueta: 'Analítica con Machine Learning', descripcion: 'Segmentación de clientes y predicción de demanda.' },
  { id: 'copias_seguridad', etiqueta: 'Copias de seguridad', descripcion: 'Copias de los datos de tu empresa y su restauración.' },
];
