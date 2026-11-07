import { fechaDesdeIso, fechaLocalIso, instanteServidor } from '../../core/date-utils';
import {
  AgrupacionReporte,
  CanalReporte,
  FiltroCatalogo,
  OrdenReporte,
  ReporteCatalogo,
  SolicitudReporte,
  SolicitudResuelta,
} from '../../core/models/reportes-ia.models';
import { formatearFechaIso } from '../../shared/graficos/formato-reporte';
import { periodoDeRango } from './data/solicitud-reporte';

/**
 * Funciones puras de la pantalla "Reportes con IA": textos de "Entendí esto", ejemplos y el formulario de filtros
 * editables. El web no sabe qué calcula cada reporte: solo arma la solicitud con lo que el catálogo del servidor declara.
 */

/** Ejemplos de respaldo si el catálogo no se pudo cargar (los mismos que se usan para probar la función). */
export const EJEMPLOS_RESPALDO: readonly string[] = [
  'Muéstrame las ventas de septiembre por sucursal',
  'Dame los 10 productos más vendidos de este mes',
  'Hazme un gráfico de ventas por semana',
  'Compara las sucursales de los últimos 3 meses',
  'Productos con menor existencia',
  'Ingresos por categoría',
];

/** Máximo de ejemplos que se ofrecen como atajos. */
export const MAX_ATAJOS = 6;
/** El servidor admite hasta 5 nombres por filtro de lista. */
export const MAX_NOMBRES_POR_FILTRO = 5;
/** Largo máximo del pedido (lo mismo que acepta el servidor). */
export const MAX_TEXTO_PEDIDO = 300;

/**
 * El primer ejemplo de cada reporte del catálogo, en el orden del servidor (los reportes base van primero), sin
 * repetidos y hasta `MAX_ATAJOS`. Sin catálogo se usan los de respaldo.
 */
export function ejemplosDelCatalogo(catalogo: readonly ReporteCatalogo[], maximo = MAX_ATAJOS): string[] {
  const lista: string[] = [];
  for (const reporte of catalogo) {
    const ejemplo = reporte.ejemplos.find((e) => e.trim() !== '');
    if (ejemplo && !lista.includes(ejemplo)) lista.push(ejemplo);
    if (lista.length >= maximo) break;
  }
  return lista.length > 0 ? lista : [...EJEMPLOS_RESPALDO].slice(0, maximo);
}

// ---- Textos -------------------------------------------------------------------------------------------------------

function dos(n: number): string {
  return String(n).padStart(2, '0');
}

/** `2026-10-30T14:05:00Z` (UTC) → `30/10/2026 10:05` en la hora LOCAL del navegador. Un valor ilegible se devuelve tal cual. */
export function fechaHoraLocal(iso: string): string {
  const fecha = instanteServidor(iso);
  if (Number.isNaN(fecha.getTime())) return iso;
  return (
    `${dos(fecha.getDate())}/${dos(fecha.getMonth() + 1)}/${fecha.getFullYear()} ` +
    `${dos(fecha.getHours())}:${dos(fecha.getMinutes())}`
  );
}

export const ETIQUETA_CANAL: Record<string, string> = { digital: 'Digital', presencial: 'Presencial' };
export const ETIQUETA_AGRUPACION: Record<string, string> = { dia: 'Por día', semana: 'Por semana', mes: 'Por mes' };
export const ETIQUETA_ORDEN: Record<string, string> = { mayor_a_menor: 'De mayor a menor', menor_a_mayor: 'De menor a mayor' };

/** Las etiquetas de los valores que el catálogo declara (un valor nuevo del servidor se muestra tal cual). */
export function etiquetaDeValor(clave: string, valor: string): string {
  const tabla = clave === 'canal' ? ETIQUETA_CANAL : clave === 'agrupacion' ? ETIQUETA_AGRUPACION : clave === 'orden' ? ETIQUETA_ORDEN : {};
  return tabla[valor] ?? valor;
}

export interface ChipFiltro {
  clave: string;
  texto: string;
}

function semanas(n: number): string {
  return `${n} ${n === 1 ? 'semana' : 'semanas'}`;
}

/** Lo que el servidor entendió, como chips. Solo aparecen los filtros que traen valor. */
export function chipsDeSolicitud(s: SolicitudResuelta): ChipFiltro[] {
  const chips: ChipFiltro[] = [];
  if (s.periodo) {
    chips.push({
      clave: 'periodo',
      texto: `Periodo: ${s.periodo.etiqueta} (${formatearFechaIso(s.periodo.desde)} al ${formatearFechaIso(s.periodo.hasta)})`,
    });
  }
  if (s.sucursales.length > 0) chips.push({ clave: 'sucursales', texto: `Sucursales: ${s.sucursales.map((x) => x.nombre).join(', ')}` });
  if (s.categorias.length > 0) chips.push({ clave: 'categorias', texto: `Categorías: ${s.categorias.map((x) => x.nombre).join(', ')}` });
  if (s.productos.length > 0) chips.push({ clave: 'productos', texto: `Productos: ${s.productos.map((x) => x.nombre).join(', ')}` });
  if (s.canal) chips.push({ clave: 'canal', texto: `Canal: ${etiquetaDeValor('canal', s.canal)}` });
  if (s.agrupacion) chips.push({ clave: 'agrupacion', texto: `Agrupación: ${etiquetaDeValor('agrupacion', s.agrupacion)}` });
  if (s.orden) chips.push({ clave: 'orden', texto: `Orden: ${etiquetaDeValor('orden', s.orden)}` });
  if (s.limite != null) chips.push({ clave: 'limite', texto: `Límite: ${s.limite}` });
  if (s.horizonte_semanas != null) chips.push({ clave: 'horizonte_semanas', texto: `Horizonte: ${semanas(s.horizonte_semanas)}` });
  return chips;
}

/** Los filtros aplicados en una sola línea (para el encabezado del resultado). */
export function textoFiltrosAplicados(s: SolicitudResuelta | null): string {
  if (s === null) return 'Sin filtros';
  const chips = chipsDeSolicitud(s);
  return chips.length > 0 ? chips.map((c) => c.texto).join(' · ') : 'Sin filtros adicionales';
}

// ---- Formulario de filtros editables -------------------------------------------------------------------------------

/** Claves que la solicitud admite, en el orden en que se muestran. Una clave nueva del catálogo que no esté aquí se ignora. */
export const CLAVES_FILTRO = [
  'periodo',
  'sucursales',
  'categorias',
  'productos',
  'canal',
  'agrupacion',
  'orden',
  'limite',
  'horizonte_semanas',
] as const;

export type ClaveFiltro = (typeof CLAVES_FILTRO)[number];

export const ETIQUETA_FILTRO: Record<ClaveFiltro, string> = {
  periodo: 'Periodo',
  sucursales: 'Sucursales',
  categorias: 'Categorías',
  productos: 'Productos',
  canal: 'Canal',
  agrupacion: 'Agrupación',
  orden: 'Orden',
  limite: 'Límite de filas',
  horizonte_semanas: 'Horizonte (semanas)',
};

export interface CampoFiltro {
  clave: ClaveFiltro;
  definicion: FiltroCatalogo;
}

/** Los campos editables de un reporte: los filtros del catálogo que la solicitud conoce, en orden estable. */
export function camposDeCatalogo(filtros: Record<string, FiltroCatalogo>): CampoFiltro[] {
  return CLAVES_FILTRO.filter((clave) => clave in filtros).map((clave) => ({ clave, definicion: filtros[clave] }));
}

export interface FormularioFiltros {
  desde: Date | null;
  hasta: Date | null;
  sucursales: string[];
  categorias: string[];
  productos: string[];
  canal: CanalReporte | null;
  agrupacion: AgrupacionReporte | null;
  orden: OrdenReporte | null;
  limite: number | null;
  horizonte: number | null;
}

/** Los valores iniciales del formulario: lo que el servidor entendió. */
export function formularioDesdeResuelta(r: SolicitudResuelta): FormularioFiltros {
  return {
    desde: r.periodo ? fechaDesdeIso(r.periodo.desde) : null,
    hasta: r.periodo ? fechaDesdeIso(r.periodo.hasta) : null,
    sucursales: r.sucursales.map((s) => s.nombre),
    categorias: r.categorias.map((c) => c.nombre),
    productos: r.productos.map((p) => p.nombre),
    canal: r.canal,
    agrupacion: r.agrupacion,
    orden: r.orden,
    limite: r.limite,
    horizonte: r.horizonte_semanas,
  };
}

/** Por qué el formulario no se puede enviar (null si está bien). */
export function errorDeFormulario(f: FormularioFiltros, filtros: Record<string, FiltroCatalogo>): string | null {
  const periodo = filtros['periodo'];
  if (periodo) {
    if ((f.desde === null) !== (f.hasta === null)) return 'Elige las dos fechas del periodo: Desde y Hasta.';
    if (f.desde === null && periodo.obligatorio) return 'Elige el periodo del reporte.';
    if (f.desde !== null && f.hasta !== null && f.desde.getTime() > f.hasta.getTime()) {
      return 'La fecha Desde no puede ser posterior a Hasta.';
    }
  }
  for (const [clave, valor] of [
    ['limite', f.limite],
    ['horizonte_semanas', f.horizonte],
  ] as const) {
    const def = filtros[clave];
    if (!def || valor === null) continue;
    if (def.minimo !== null && valor < def.minimo) return `${ETIQUETA_FILTRO[clave]}: el mínimo es ${def.minimo}.`;
    if (def.maximo !== null && valor > def.maximo) return `${ETIQUETA_FILTRO[clave]}: el máximo es ${def.maximo}.`;
  }
  return null;
}

/**
 * La solicitud que se reenvía con "Actualizar reporte": solo NOMBRES y fechas (nunca ids), y solo los filtros que el
 * catálogo del reporte declara. Los vacíos no se mandan (el servidor aplica su valor por defecto).
 */
export function solicitudDesdeFormulario(
  tipo: string,
  f: FormularioFiltros,
  filtros: Record<string, FiltroCatalogo>,
): SolicitudReporte {
  const s: SolicitudReporte = { tipo_reporte: tipo };
  if ('periodo' in filtros && f.desde && f.hasta) s.periodo = periodoDeRango(fechaLocalIso(f.desde), fechaLocalIso(f.hasta));
  if ('sucursales' in filtros && f.sucursales.length > 0) s.sucursales = [...f.sucursales];
  if ('categorias' in filtros && f.categorias.length > 0) s.categorias = [...f.categorias];
  if ('productos' in filtros && f.productos.length > 0) s.productos = [...f.productos];
  if ('canal' in filtros && f.canal) s.canal = f.canal;
  if ('agrupacion' in filtros && f.agrupacion) s.agrupacion = f.agrupacion;
  if ('orden' in filtros && f.orden) s.orden = f.orden;
  if ('limite' in filtros && f.limite !== null) s.limite = f.limite;
  if ('horizonte_semanas' in filtros && f.horizonte !== null) s.horizonte_semanas = f.horizonte;
  return s;
}
