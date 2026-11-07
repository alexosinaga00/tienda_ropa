/**
 * Bitácora de auditoría (E06 en el backend). La pantalla muestra lo que manda
 * el servidor, sin filtrar nada en el cliente: el backend ya omite secretos y
 * datos personales (`core/auditoria.py`, `sanear_datos`).
 */
import { instanteServidor } from '../date-utils';

/** Una fila de `GET /bitacora` o `GET /plataforma/bitacora` (`BitacoraRespuesta`). */
export interface RegistroBitacora {
  id: number;
  /** Solo lo informa el backend al superadministrador. */
  empresa_id: number | null;
  usuario_id: number | null;
  /** El administrador de una empresa ve "Administrador de la plataforma" cuando actuó el superadministrador. */
  usuario_nombre: string | null;
  entidad: string;
  entidad_id: number | null;
  accion: string;
  datos: Record<string, unknown> | null;
  ip: string | null;
  /** UTC con "Z" (antes sin zona): usa `fechaDeBitacora` para leerla. */
  creado_en: string;
}

/** `BitacoraPagina`: `total` es el total de filas del filtro, no de la página. */
export interface PaginaBitacora {
  total: number;
  pagina: number;
  tamanio: number;
  items: RegistroBitacora[];
}

/** Filtros de la consulta. `desde` y `hasta` son obligatorios en la pantalla (aaaa-mm-dd). */
export interface ConsultaBitacora {
  desde: string;
  hasta: string;
  entidad?: string | null;
  accion?: string | null;
  usuario_id?: number | null;
  pagina?: number;
  tamanio?: number;
}

/** Solo el superadministrador: una empresa en concreto, o las filas sin empresa. */
export interface ConsultaBitacoraPlataforma extends ConsultaBitacora {
  empresa_id?: number | null;
  sin_empresa?: boolean;
}

export interface OpcionAuditoria {
  value: string;
  label: string;
}

/** Nombres reales de `ENTIDAD_*` en `backend/app/core/auditoria.py`. */
export const ENTIDADES_AUDITORIA: readonly OpcionAuditoria[] = [
  { value: 'sesion', label: 'Sesión' },
  { value: 'usuario', label: 'Usuario' },
  { value: 'rol', label: 'Rol' },
  { value: 'sucursal', label: 'Sucursal' },
  { value: 'empleado', label: 'Empleado' },
  { value: 'empresa', label: 'Empresa' },
  { value: 'plan', label: 'Plan' },
  { value: 'suscripcion', label: 'Suscripción' },
  { value: 'venta', label: 'Venta' },
  { value: 'devolucion', label: 'Devolución' },
  { value: 'movimiento_inventario', label: 'Movimiento de inventario' },
  { value: 'bitacora', label: 'Bitácora' },
  { value: 'reporte_ia', label: 'Reporte con IA' },
  { value: 'reporte', label: 'Reporte' },
  { value: 'lote_sync', label: 'Lote sincronizado' },
  { value: 'operacion_sync', label: 'Operación sincronizada' },
  { value: 'copia_seguridad', label: 'Copia de seguridad' },
  { value: 'cierre_caja', label: 'Cierre de caja' },
  { value: 'modelo_ml', label: 'Modelo de analítica' },
];

/** Nombres reales de `ACCION_*` en `backend/app/core/auditoria.py`. */
export const ACCIONES_AUDITORIA: readonly OpcionAuditoria[] = [
  { value: 'crear', label: 'Crear' },
  { value: 'actualizar', label: 'Actualizar' },
  { value: 'desactivar', label: 'Desactivar' },
  { value: 'asignar_roles', label: 'Asignar roles' },
  { value: 'asignar_permisos', label: 'Asignar permisos' },
  { value: 'login_exitoso', label: 'Inicio de sesión' },
  { value: 'login_fallido', label: 'Inicio de sesión fallido' },
  { value: 'contrasena_restablecida', label: 'Contraseña restablecida' },
  { value: 'asignar_plan', label: 'Asignar plan' },
  { value: 'cambiar_plan', label: 'Cambiar de plan' },
  { value: 'cambiar_estado', label: 'Cambiar estado' },
  { value: 'renovar', label: 'Renovar' },
  { value: 'anular_pago', label: 'Anular pago' },
  { value: 'registrar', label: 'Registrar' },
  { value: 'ajuste', label: 'Ajuste de inventario' },
  { value: 'purgar', label: 'Purgar registros' },
  { value: 'ejecutar', label: 'Ejecutar' },
  { value: 'rechazar', label: 'Rechazar' },
  { value: 'exportar', label: 'Exportar' },
  { value: 'sincronizar_lote', label: 'Sincronizar lote' },
  { value: 'resolver_conflicto', label: 'Resolver conflicto' },
  { value: 'cambiar_plazo_cambio', label: 'Cambiar plazo de cambio' },
  { value: 'descargar', label: 'Descargar' },
  { value: 'eliminar', label: 'Eliminar' },
  { value: 'abrir', label: 'Abrir' },
  { value: 'cerrar', label: 'Cerrar' },
  { value: 'entrenar', label: 'Entrenar modelo' },
];

const ETIQUETA_ENTIDAD = new Map(ENTIDADES_AUDITORIA.map((o) => [o.value, o.label]));
const ETIQUETA_ACCION = new Map(ACCIONES_AUDITORIA.map((o) => [o.value, o.label]));

/** Lo desconocido (una entidad que agregue una etapa nueva) se muestra tal cual, sin romper. */
export function etiquetaEntidad(entidad: string): string {
  return ETIQUETA_ENTIDAD.get(entidad) ?? entidad;
}

export function etiquetaAccion(accion: string): string {
  return ETIQUETA_ACCION.get(accion) ?? accion;
}

/** `creado_en` llega en UTC ("Z"; la forma vieja sin zona también se lee como UTC): ver `instanteServidor`. */
export const fechaDeBitacora = instanteServidor;

// ---- Resumen ---------------------------------------------------------------

const LARGO_MAXIMO_RESUMEN = 140;

const DECISIONES: Record<string, string> = { forzar: 'forzar la venta', rechazar: 'rechazar' };

/** Claves que se muestran tal cual: `[clave en datos, rótulo]`, en este orden. */
const CLAVES_SIMPLES: readonly (readonly [string, string])[] = [
  ['codigo', 'Código'],
  ['plan', 'Plan'],
  ['rol', 'Rol'],
  ['tipo', 'Tipo'],
  ['motivo', 'Motivo'],
  ['venta_id', 'Venta'],
  ['pago_id', 'Pago'],
  ['variante_id', 'Variante'],
  ['sucursal_id', 'Sucursal'],
  ['version', 'Versión'],
  ['filas', 'Filas'],
  ['unidades', 'Unidades'],
];

function esEscalar(valor: unknown): valor is string | number | boolean {
  return typeof valor === 'string' || typeof valor === 'number' || typeof valor === 'boolean';
}

function texto(valor: unknown): string | null {
  if (esEscalar(valor)) return String(valor);
  if (Array.isArray(valor)) {
    const partes = valor.filter(esEscalar).map(String);
    return partes.length > 0 ? partes.join(', ') : null;
  }
  return null;
}

/** '2026-11-30' -> '30/11/2026'; cualquier otro texto queda como llegó. */
function fechaCorta(valor: string): string {
  const coincide = /^(\d{4})-(\d{2})-(\d{2})/.exec(valor);
  return coincide ? `${coincide[3]}/${coincide[2]}/${coincide[1]}` : valor;
}

function cambio(rotulo: string, antes: unknown, despues: unknown, formato: (v: string) => string = (v) => v): string | null {
  const a = texto(antes);
  const d = texto(despues);
  if (a !== null && d !== null) return `${rotulo}: ${formato(a)} → ${formato(d)}`;
  if (d !== null) return `${rotulo}: ${formato(d)}`;
  return null;
}

/** Los avisos del lote: `{confirmadas, rechazadas, en_conflicto, duplicadas, errores_temporales}`. */
function resumenDeLote(resumen: unknown): string | null {
  if (typeof resumen !== 'object' || resumen === null) return null;
  const r = resumen as Record<string, unknown>;
  const partes: string[] = [];
  const agregar = (clave: string, singular: string, plural: string) => {
    const n = r[clave];
    if (typeof n === 'number' && n > 0) partes.push(`${n} ${n === 1 ? singular : plural}`);
  };
  agregar('confirmadas', 'confirmada', 'confirmadas');
  agregar('rechazadas', 'rechazada', 'rechazadas');
  agregar('en_conflicto', 'en conflicto', 'en conflicto');
  agregar('duplicadas', 'duplicada', 'duplicadas');
  return partes.length > 0 ? `Lote: ${partes.join(', ')}` : null;
}

/**
 * Resumen corto de `datos`, armado solo con claves conocidas (ids y códigos).
 * Sin claves conocidas devuelve '' (el detalle completo está en la fila
 * expandible). Nunca interpreta el texto: es solo texto que Angular escapa.
 */
export function resumenDeDatos(datos: Record<string, unknown> | null | undefined): string {
  if (!datos || typeof datos !== 'object') return '';
  const partes: (string | null)[] = [];

  partes.push(cambio('Plan', datos['plan_antes'], datos['plan_despues']));
  partes.push(cambio('Estado', datos['estado_antes'], datos['estado_despues']));
  partes.push(cambio('Vence', datos['vencimiento_antes'], datos['vencimiento_despues'], fechaCorta));

  const decision = texto(datos['decision']);
  if (decision !== null) partes.push(`Decisión: ${DECISIONES[decision] ?? decision}`);

  const operacion = texto(datos['operacion_id']);
  if (operacion !== null) partes.push(`Operación: ${operacion.slice(0, 8)}`);

  partes.push(resumenDeLote(datos['resumen']));

  for (const [clave, rotulo] of CLAVES_SIMPLES) {
    const valor = texto(datos[clave]);
    if (valor !== null) partes.push(`${rotulo}: ${valor}`);
  }

  // `antes`/`despues` sueltos: plazo de cambio (números) y roles asignados (listas).
  if (!('plan_antes' in datos) && !('estado_antes' in datos)) {
    partes.push(cambio('Cambio', datos['antes'], datos['despues']));
  }

  const resumen = partes.filter((p): p is string => p !== null).join(' · ');
  return resumen.length > LARGO_MAXIMO_RESUMEN ? `${resumen.slice(0, LARGO_MAXIMO_RESUMEN - 1)}…` : resumen;
}
