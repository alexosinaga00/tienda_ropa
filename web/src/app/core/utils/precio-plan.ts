/**
 * Precios de los planes en la web (contratación). El servidor manda los montos como TEXTO decimal ("120.00") y
 * SIEMPRE recalcula lo que se cobra: lo de aquí solo sirve para MOSTRAR.
 */

/** Días de la prueba gratuita (`prueba_dias` del backend; solo para el texto de la portada). */
export const DIAS_PRUEBA = 14;

/** Descuento del pago anual (`descuento_anual_porcentaje` del backend; solo para mostrar el ahorro). */
export const DESCUENTO_ANUAL_PORCENTAJE = 20;

export type PeriodoPlan = 'mensual' | 'anual';

/** "120.00" -> 120. Texto vacío, nulo o no numérico -> null. */
export function aNumeroBs(texto: string | number | null | undefined): number | null {
  if (texto === null || texto === undefined || texto === '') return null;
  const valor = typeof texto === 'number' ? texto : Number(texto);
  return Number.isFinite(valor) ? valor : null;
}

/** Un plan tiene precio publicado solo si es mayor que cero (igual que `plan_sin_precio` en el backend). */
export function tienePrecio(texto: string | number | null | undefined): boolean {
  const valor = aNumeroBs(texto);
  return valor !== null && valor > 0;
}

/** Mitad hacia arriba a 2 decimales, como hace el backend con `Decimal`. */
function redondear2(valor: number): number {
  return Math.round((valor + Number.EPSILON) * 100) / 100;
}

/** Precio del periodo: mensual tal cual; anual = mensual x 12 menos el descuento. */
export function montoDelPeriodo(mensual: number, periodo: PeriodoPlan): number {
  if (periodo === 'mensual') return redondear2(mensual);
  return redondear2(mensual * 12 * (1 - DESCUENTO_ANUAL_PORCENTAJE / 100));
}

/** Lo que cuesta al mes cuando se paga el año entero (para decir "equivale a Bs X al mes"). */
export function equivalenteMensualAnual(mensual: number): number {
  return redondear2(montoDelPeriodo(mensual, 'anual') / 12);
}

/** Lo que se ahorra pagando el año entero frente a doce meses sueltos. */
export function ahorroAnual(mensual: number): number {
  return redondear2(mensual * 12 - montoDelPeriodo(mensual, 'anual'));
}

/** 1152 -> "1.152"; 99.5 -> "99,50"; 120 -> "120". Formato de Bolivia (punto de miles, coma decimal). */
export function formatearNumeroBs(valor: number): string {
  const redondeado = redondear2(valor);
  const [entera, decimales] = Math.abs(redondeado).toFixed(2).split('.');
  const miles = entera.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  const signo = redondeado < 0 ? '-' : '';
  return decimales === '00' ? `${signo}${miles}` : `${signo}${miles},${decimales}`;
}

/** "Bs 1.152". Sin precio válido devuelve cadena vacía. */
export function formatearBs(valor: string | number | null | undefined): string {
  const numero = aNumeroBs(valor);
  return numero === null ? '' : `Bs ${formatearNumeroBs(numero)}`;
}
