export interface ZonaEnvio {
  id: number;
  ciudad_id: number;
  nombre: string;
  anillo_desde: number | null;
  anillo_hasta: number | null;
  tarifa_base: number;
  activo: boolean;
}

export interface ZonaEnvioCrear {
  ciudad_id: number;
  nombre: string;
  anillo_desde?: number | null;
  anillo_hasta?: number | null;
  tarifa_base: number;
}

export interface ZonaEnvioActualizar {
  nombre?: string;
  anillo_desde?: number | null;
  anillo_hasta?: number | null;
  tarifa_base?: number;
  activo?: boolean;
}

export interface DireccionCliente {
  id: number;
  cliente_id: number;
  zona_envio_id: number | null;
  alias: string | null;
  direccion: string;
  referencia: string | null;
  latitud: number | null;
  longitud: number | null;
  es_principal: boolean;
  activo: boolean;
}

export interface DireccionClienteCrear {
  zona_envio_id?: number | null;
  alias?: string | null;
  direccion: string;
  referencia?: string | null;
  es_principal?: boolean;
}

export type EstadoEnvio = 'programado' | 'en_ruta' | 'entregado' | 'fallido';

export interface CotizarEnvioRequest {
  direccion_id: number;
  cantidad_prendas: number;
}

export interface CotizacionEnvio {
  zona_envio_id: number;
  zona_nombre: string;
  peso_kg: number;
  tarifa_base: number;
  recargo_peso: number;
  costo: number;
}

export interface EnvioCrear {
  venta_id: number;
  direccion_id: number;
}

export interface Envio {
  id: number;
  venta_id: number;
  direccion_id: number;
  zona_envio_id: number;
  costo: number;
  peso_kg: number | null;
  estado: EstadoEnvio;
  fecha_programada: string | null;
  fecha_entrega: string | null;
  repartidor: string | null;
}

export interface EnvioEstadoActualizar {
  estado: EstadoEnvio;
  repartidor?: string;
}
