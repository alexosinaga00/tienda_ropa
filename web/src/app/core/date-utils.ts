/** El servidor manda todo instante (`venta.fecha`, `creado_en`, `vence_en`...) en UTC con "Z"
 * ("2026-11-07T03:12:00Z"). Para comparar o agrupar por día hay que pasarlo a la hora LOCAL del navegador
 * (`instanteServidor` + `diaLocalDe`); cortar el texto (`slice(0, 10)`) compara el día UTC, y una venta de las
 * 23:12 en Bolivia (03:12 UTC del día siguiente) caería en otro día.
 * Los valores de negocio sin hora (`fecha_visita`, `fecha_vencimiento`) son días y NO pasan por aquí. */

const CON_ZONA = /(Z|[+-]\d{2}:?\d{2})$/i;
const SOLO_DIA = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Un instante del servidor como `Date`. Tolera la forma vieja sin zona ("2026-10-30T14:05:00"): se asume UTC, como
 * mandaba el servidor antes. Un día sin hora ("2026-11-04") se lee como medianoche LOCAL (no es un instante). Un valor
 * ilegible da un `Date` inválido (`NaN`), igual que `new Date(...)`.
 */
export function instanteServidor(iso: string): Date {
  if (SOLO_DIA.test(iso)) return fechaDesdeIso(iso);
  return new Date(CON_ZONA.test(iso) ? iso : `${iso}Z`);
}

/** El día calendario LOCAL ("2026-11-06") de un instante del servidor; '' si es ilegible. */
export function diaLocalDe(iso: string): string {
  const fecha = instanteServidor(iso);
  return Number.isNaN(fecha.getTime()) ? '' : fechaLocalIso(fecha);
}

/** Un `Date` como día calendario LOCAL ("2026-11-06"), no UTC: `toISOString()` desalinea el día cerca de medianoche. */
export function fechaLocalIso(fecha: Date): string {
  const y = fecha.getFullYear();
  const m = String(fecha.getMonth() + 1).padStart(2, '0');
  const d = String(fecha.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

/** Inversa de `fechaLocalIso`: '2026-09-20' -> esa fecha a medianoche LOCAL.
 * `new Date('2026-09-20')` la lee como UTC y en Bolivia (UTC-4) muestra el día anterior. */
export function fechaDesdeIso(iso: string): Date {
  const [anio, mes, dia] = iso.split('-').map(Number);
  return new Date(anio, mes - 1, dia);
}
