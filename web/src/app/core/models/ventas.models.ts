export type EstadoVenta = 'pendiente_pago' | 'pagada' | 'entregada' | 'anulada';
export type CanalVenta = 'digital' | 'presencial';
export type TipoPromocion = 'porcentaje' | 'monto';

export interface VentaDetalleLinea {
  variante_id: number;
  cantidad: number;
}

export interface VentaPresencialCrear {
  sucursal_id: number;
  detalle?: VentaDetalleLinea[];
  reserva_id?: number | null;
  cliente_id?: number | null;
}

export interface VentaDetalle {
  id: number;
  variante_id: number;
  cantidad: number;
  precio_unitario: number;
  descuento_unitario: number;
  costo_unitario: number | null;
  subtotal: number;
}

export interface Venta {
  id: number;
  codigo: string;
  canal: CanalVenta;
  cliente_id: number | null;
  sucursal_id: number;
  cajero_id: number | null;
  reserva_id: number | null;
  estado: EstadoVenta;
  fecha: string;
  subtotal: number;
  descuento: number;
  costo_envio: number;
  total: number;
  detalle: VentaDetalle[];
}

/** `GET /ventas/{id}/plazo-cambio` (D19): el servidor decide; las marcas van en UTC con "Z". */
export interface PlazoCambio {
  venta_id: number;
  fecha_venta: string;
  plazo_horas: number;
  vence_en: string;
  vigente: boolean;
  estado_venta: string;
}

export interface DevolucionDetalleCrear {
  venta_detalle_id: number;
  cantidad: number;
  /** Cambio de talla o color: la variante (del mismo producto y del mismo precio) que se entrega en su lugar. */
  variante_nueva_id?: number;
}

/** Una prenda entregada en lugar de otra en un cambio (solo en la respuesta del registro). */
export interface Reposicion {
  venta_detalle_id: number;
  variante_devuelta_id: number;
  variante_nueva_id: number;
  cantidad: number;
}

export interface DevolucionCrear {
  venta_id: number;
  motivo?: string | null;
  detalle: DevolucionDetalleCrear[];
}

export interface DevolucionDetalle {
  id: number;
  venta_detalle_id: number;
  cantidad: number;
}

export interface Devolucion {
  id: number;
  codigo: string;
  venta_id: number;
  fecha: string;
  motivo: string | null;
  estado: 'pendiente' | 'aprobada' | 'rechazada';
  usuario_id: number | null;
  detalle: DevolucionDetalle[];
  /** Lo que salió del stock en un cambio; vacío en una devolución simple. */
  reposiciones?: Reposicion[];
  /** El comprobante quedó programado por correo (el comprador tiene correo). */
  correo_programado?: boolean;
}

export interface PromocionAlcance {
  id: number;
  producto_id: number | null;
  categoria_id: number | null;
  temporada_id: number | null;
}

export interface PromocionAlcanceCrear {
  producto_id?: number | null;
  categoria_id?: number | null;
  temporada_id?: number | null;
}

export interface Promocion {
  id: number;
  nombre: string;
  tipo: TipoPromocion;
  valor: number;
  fecha_inicio: string;
  fecha_fin: string;
  activo: boolean;
  alcances: PromocionAlcance[];
}

export interface PromocionCrear {
  nombre: string;
  tipo: TipoPromocion;
  valor: number;
  fecha_inicio: string;
  fecha_fin: string;
  alcances: PromocionAlcanceCrear[];
}

export interface PromocionActualizar {
  nombre?: string;
  valor?: number;
  fecha_inicio?: string;
  fecha_fin?: string;
  activo?: boolean;
}

// ---- Carrito (tienda pública) ------------------------------------------------

export interface CarritoDetalleCrear {
  variante_id: number;
  cantidad?: number;
}

export interface CarritoDetalleActualizar {
  cantidad: number;
}

export interface CarritoDetalle {
  id: number;
  variante_id: number;
  cantidad: number;
  precio_unitario: number;
  subtotal: number;
  /** false: la prenda se dio de baja después de agregarla (no suma ni se puede comprar). */
  disponible: boolean;
}

export interface Carrito {
  id: number;
  cliente_id: number;
  sucursal_id: number | null;
  actualizado_en: string;
  detalle: CarritoDetalle[];
  subtotal: number;
}

/** `CarritoDetalle` + los datos resueltos vía /catalogo/variantes/detalle
 * (el backend no los incluye, ver `obtener_detalle_para_dashboard` en backend/app/catalogo/router.py). */
export interface CarritoLinea extends CarritoDetalle {
  productoNombre?: string;
  imagenPrincipal?: string | null;
  tallaCodigo?: string | null;
  colorNombre?: string | null;
}

export interface CarritoResumenLinea {
  variante_id: number;
  cantidad: number;
  precio_unitario: number;
  descuento_unitario: number;
  subtotal: number;
}

export interface CarritoResumen {
  lineas: CarritoResumenLinea[];
  subtotal: number;
  descuento: number;
  total: number;
}

export interface VentaDigitalCrear {
  sucursal_id: number;
  costo_envio?: number;
  reserva_id?: number | null;
}
