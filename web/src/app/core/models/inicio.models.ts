import { EstadoVenta } from './ventas.models';

/**
 * `GET /api/v1/inicio/resumen`: lo de HOY (día de Bolivia) para la pantalla de inicio del personal, ya calculado por el
 * servidor. Cada sección es `null` cuando el usuario no tiene el permiso de esa parte o el plan de la empresa no la incluye.
 * Los montos llegan como texto ("100.00").
 */
export interface PrendaVendidaInicio {
  variante_id: number;
  nombre: string;
  cantidad: number;
}

export interface VentaRecienteInicio {
  id: number;
  codigo: string;
  /** Instante UTC con "Z". */
  fecha: string;
  total: string;
  estado: EstadoVenta;
  unidades_vendidas: number;
  unidades_devueltas: number;
}

export interface ResumenVentasInicio {
  tickets: number;
  total_ventas: string;
  por_cobrar_cantidad: number;
  por_cobrar_total: string;
  mas_vendidas: PrendaVendidaInicio[];
  recientes: VentaRecienteInicio[];
}

export interface AlertaStockInicio {
  producto_id: number;
  variante_id: number;
  producto: string;
  stock_minimo: number;
  cantidad_disponible: number;
  imagen: string | null;
}

export interface ResumenStockInicio {
  total_alertas: number;
  alertas: AlertaStockInicio[];
}

export interface ResumenReservasInicio {
  total: number;
  por_estado: { codigo: string; nombre: string; cantidad: number }[];
}

export interface ResumenInicio {
  /** El día de hoy en Bolivia ("2026-11-07"). */
  fecha: string;
  /** null = todas las sucursales (administrador). */
  sucursal_id: number | null;
  sucursal_nombre: string;
  ventas: ResumenVentasInicio | null;
  stock: ResumenStockInicio | null;
  reservas: ResumenReservasInicio | null;
}
