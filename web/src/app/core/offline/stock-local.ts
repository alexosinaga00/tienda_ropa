import { instanteServidor } from '../date-utils';
import type { OperacionOffline } from './offline.models';

/** Estados cuyas operaciones ya "ocuparon" unidades en este equipo: una rechazada devuelve las suyas. */
const ESTADOS_QUE_DESCUENTAN = new Set(['registrada', 'enviada', 'confirmada', 'en_conflicto']);

/**
 * El stock que se puede ofrecer SIN conexión: lo que se conocía menos lo que ya se vendió o reservó en este equipo
 * después de ese momento. Cuando una descarga nueva deja `generadoEn` más reciente, esas operaciones dejan de contar
 * solas (el servidor ya las descontó en lo que mandó). Puede dar negativo: es señal de que se vendió de más.
 */
export function stockDisponibleLocal(
  cantidadConocida: number,
  generadoEn: string,
  operaciones: readonly OperacionOffline[],
  varianteId: number,
  sucursalId: number,
): number {
  const desde = instanteServidor(generadoEn).getTime();
  let usado = 0;
  for (const operacion of operaciones) {
    if (operacion.sucursal_id !== sucursalId || !ESTADOS_QUE_DESCUENTAN.has(operacion.estado)) continue;
    if (Number.isFinite(desde) && !(Date.parse(operacion.fecha_operacion) > desde)) continue;
    for (const linea of operacion.lineas) {
      if (linea.variante_id === varianteId) usado += linea.cantidad;
    }
  }
  return cantidadConocida - usado;
}
