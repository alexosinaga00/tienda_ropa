export interface Ciudad {
  id: number;
  nombre: string;
  departamento: string | null;
  activo: boolean;
}

export interface CiudadCrear {
  nombre: string;
  departamento?: string | null;
}

export type CiudadActualizar = Partial<CiudadCrear>;

export interface Sucursal {
  id: number;
  ciudad_id: number;
  codigo: string;
  nombre: string;
  direccion: string;
  telefono: string | null;
  latitud: number | null;
  longitud: number | null;
  es_deposito: boolean;
  activo: boolean;
  creado_en: string;
}

export interface SucursalCrear {
  ciudad_id: number;
  codigo: string;
  nombre: string;
  direccion: string;
  telefono?: string | null;
  es_deposito?: boolean;
}

export type SucursalActualizar = Partial<SucursalCrear> & { activo?: boolean };

/** Fila de GET /sucursales/{id}/horarios -- público, `dia_semana` es
 * 1=lunes...7=domingo (isoweekday), igual que Date.getDay() ajustado. */
export interface HorarioSucursal {
  id: number;
  sucursal_id: number;
  dia_semana: number;
  hora_apertura: string;
  hora_cierre: string;
}

export interface Empleado {
  id: number;
  usuario_id: number;
  usuario_nombre?: string | null;
  usuario_apellido?: string | null;
  sucursal_id: number | null;
  sucursal_nombre?: string | null;
  ci: string | null;
  cargo: string | null;
  fecha_ingreso: string | null;
  activo: boolean;
}

export interface EmpleadoCrear {
  usuario_id: number;
  sucursal_id?: number | null;
  ci?: string | null;
  cargo?: string | null;
  fecha_ingreso?: string | null;
}

export type EmpleadoActualizar = Partial<Omit<EmpleadoCrear, 'usuario_id'>>;
