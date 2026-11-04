import { FuncionPlan } from './plan.models';

/** Estados que informa el backend (`estado_efectivo`): `vencida` se calcula por fecha. */
export type EstadoSuscripcionPlataforma = 'activa' | 'suspendida' | 'vencida' | 'cancelada';

/** Estados que se le pueden pedir al backend (`PUT /plataforma/suscripciones/{id}/estado`). `vencida` nunca se pide. */
export type EstadoSuscripcionPedido = 'activa' | 'suspendida' | 'cancelada';

export type SeveridadEstado = 'success' | 'danger' | 'warn' | 'secondary';

/** Texto y color (p-tag) de cada estado: activa verde, vencida roja, suspendida ámbar, cancelada gris. */
export const ESTADOS_SUSCRIPCION: Record<EstadoSuscripcionPlataforma, { etiqueta: string; severidad: SeveridadEstado }> = {
  activa: { etiqueta: 'Activa', severidad: 'success' },
  vencida: { etiqueta: 'Vencida', severidad: 'danger' },
  suspendida: { etiqueta: 'Suspendida', severidad: 'warn' },
  cancelada: { etiqueta: 'Cancelada', severidad: 'secondary' },
};

/** Etiqueta de un estado que viene del backend (o de una empresa sin suscripción: null). */
export function etiquetaEstadoSuscripcion(estado: string | null | undefined): string {
  if (!estado) return 'Sin suscripción';
  return ESTADOS_SUSCRIPCION[estado as EstadoSuscripcionPlataforma]?.etiqueta ?? estado;
}

export function severidadEstadoSuscripcion(estado: string | null | undefined): SeveridadEstado {
  return ESTADOS_SUSCRIPCION[estado as EstadoSuscripcionPlataforma]?.severidad ?? 'secondary';
}

/** `GET /plataforma/planes` (PlanRespuesta). Las fechas son 'YYYY-MM-DD'. */
export interface PlanPlataforma extends Record<FuncionPlan, boolean> {
  id: number;
  codigo: string;
  nombre: string;
  max_sucursales: number;
  max_copias_historial: number;
  plazo_cambio_horas_defecto: number;
  /** Bs por mes, como TEXTO decimal ("120.00"); null = sin precio publicado (no se puede contratar). */
  precio_mensual_bs: string | null;
  activo: boolean;
}

/**
 * `PUT /plataforma/planes/{id}` (PlanActualizar): todo opcional. El código no cambia. El precio va como número;
 * `null` borra el precio del plan (queda "a consultar" y no se puede contratar).
 */
export type PlanPlataformaActualizar = Partial<
  Pick<PlanPlataforma, 'max_sucursales' | 'max_copias_historial' | 'plazo_cambio_horas_defecto'> &
    Record<FuncionPlan, boolean> & { precio_mensual_bs: number | null }
>;

/** `GET /plataforma/empresas` (EmpresaRespuesta). */
export interface EmpresaPlataforma {
  id: number;
  codigo: string;
  nombre: string;
  logo_url: string | null;
  color_acento: string | null;
  activo: boolean;
  plan_codigo: string | null;
  suscripcion_estado: EstadoSuscripcionPlataforma | string | null;
  fecha_inicio: string | null;
  fecha_vencimiento: string | null;
  administrador_email: string | null;
}

/** `GET /plataforma/empresas/{id}/resumen`. */
export interface EmpresaResumen extends EmpresaPlataforma {
  usuarios_activos: number;
  sucursales_activas: number;
  max_sucursales: number | null;
}

export interface AdministradorRegistrar {
  nombre: string;
  apellido: string;
  email: string;
  telefono?: string;
  password: string;
}

/** `POST /plataforma/empresas` (EmpresaRegistrar). El código sale del nombre. */
export interface EmpresaRegistrar {
  nombre: string;
  plan_codigo?: string;
  fecha_vencimiento?: string;
  color_acento?: string;
  logo_url?: string;
  administrador: AdministradorRegistrar;
}

/** `PUT /plataforma/empresas/{id}` (EmpresaActualizar). `null` borra el logo o el color. */
export interface EmpresaActualizar {
  nombre?: string;
  logo_url?: string | null;
  color_acento?: string | null;
  activo?: boolean;
}

/** `GET /plataforma/suscripciones` (SuscripcionRespuesta). */
export interface SuscripcionPlataforma {
  id: number;
  empresa_id: number;
  plan_codigo: string;
  plan_nombre: string;
  estado: string;
  estado_efectivo: EstadoSuscripcionPlataforma | string;
  fecha_inicio: string;
  fecha_vencimiento: string;
  creado_en: string | null;
}

/** `POST /plataforma/suscripciones`: asigna un plan o CAMBIA el vigente. */
export interface SuscripcionAsignar {
  empresa_id: number;
  plan_codigo: string;
  fecha_inicio?: string;
  fecha_vencimiento?: string;
}

export interface ConsultaEmpresas {
  q?: string;
  activo?: boolean;
  pagina?: number;
  tamanio?: number;
}

export interface ConsultaSuscripciones {
  empresa_id?: number;
  estado?: EstadoSuscripcionPlataforma;
  pagina?: number;
  tamanio?: number;
}
