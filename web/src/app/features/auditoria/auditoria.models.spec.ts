import {
  ACCIONES_AUDITORIA,
  ENTIDADES_AUDITORIA,
  etiquetaAccion,
  etiquetaEntidad,
  fechaDeBitacora,
  resumenDeDatos,
} from '../../core/models/auditoria.models';

describe('auditoria.models', () => {
  describe('etiquetas', () => {
    it('traduce las entidades y acciones reales del backend a lenguaje claro', () => {
      expect(etiquetaAccion('login_exitoso')).toBe('Inicio de sesión');
      expect(etiquetaAccion('cambiar_plan')).toBe('Cambiar de plan');
      expect(etiquetaAccion('resolver_conflicto')).toBe('Resolver conflicto');
      expect(etiquetaAccion('sincronizar_lote')).toBe('Sincronizar lote');
      expect(etiquetaAccion('entrenar')).toBe('Entrenar modelo');
      expect(etiquetaEntidad('reembolso')).toBe('Reembolso');
      expect(etiquetaAccion('reembolsar')).toBe('Reembolsar');
      expect(etiquetaAccion('fallar')).toBe('Falló');
      expect(etiquetaEntidad('cierre_caja')).toBe('Cierre de caja');
      expect(etiquetaAccion('abrir')).toBe('Abrir turno');
      expect(etiquetaAccion('cerrar')).toBe('Cerrar turno');
      expect(etiquetaAccion('cierre_automatico')).toBe('Cierre automático');
      expect(etiquetaAccion('completar_conteo')).toBe('Completar conteo');
      expect(etiquetaEntidad('suscripcion')).toBe('Suscripción');
      expect(etiquetaEntidad('operacion_sync')).toBe('Operación sincronizada');
      expect(etiquetaEntidad('lote_sync')).toBe('Lote sincronizado');
    });

    it('lo desconocido se devuelve tal cual', () => {
      expect(etiquetaAccion('algo_nuevo')).toBe('algo_nuevo');
      expect(etiquetaEntidad('<b>x</b>')).toBe('<b>x</b>');
    });

    it('no repite valores en las listas de filtros', () => {
      expect(new Set(ENTIDADES_AUDITORIA.map((o) => o.value)).size).toBe(ENTIDADES_AUDITORIA.length);
      expect(new Set(ACCIONES_AUDITORIA.map((o) => o.value)).size).toBe(ACCIONES_AUDITORIA.length);
    });
  });

  describe('fechaDeBitacora', () => {
    it('una fecha sin zona se lee como UTC', () => {
      expect(fechaDeBitacora('2026-10-28T14:30:00').toISOString()).toBe('2026-10-28T14:30:00.000Z');
      expect(fechaDeBitacora('2026-10-28T14:30:00.123456').toISOString()).toBe('2026-10-28T14:30:00.123Z');
    });

    it('una fecha con Z o con desfase se respeta', () => {
      expect(fechaDeBitacora('2026-10-28T14:30:00Z').toISOString()).toBe('2026-10-28T14:30:00.000Z');
      expect(fechaDeBitacora('2026-10-28T10:30:00-04:00').toISOString()).toBe('2026-10-28T14:30:00.000Z');
      expect(fechaDeBitacora('2026-10-28T14:30:00+00:00').toISOString()).toBe('2026-10-28T14:30:00.000Z');
    });
  });

  describe('resumenDeDatos', () => {
    it('sin datos o sin claves conocidas queda vacío', () => {
      expect(resumenDeDatos(null)).toBe('');
      expect(resumenDeDatos(undefined)).toBe('');
      expect(resumenDeDatos({})).toBe('');
      expect(resumenDeDatos({ cosa: 'x', otra: { anidada: 1 } })).toBe('');
    });

    it('cambio de plan: de qué plan a cuál', () => {
      expect(resumenDeDatos({ plan_antes: 'basico', plan_despues: 'profesional', suscripcion_nueva_id: 4 })).toBe(
        'Plan: basico → profesional',
      );
      expect(resumenDeDatos({ plan_despues: 'profesional', suscripcion_nueva_id: 4 })).toBe('Plan: profesional');
    });

    it('cambio de estado y renovación (fecha dd/mm/aaaa)', () => {
      expect(resumenDeDatos({ estado_antes: 'activa', estado_despues: 'suspendida' })).toBe('Estado: activa → suspendida');
      expect(resumenDeDatos({ vencimiento_antes: '2026-11-30', vencimiento_despues: '2027-01-15' })).toBe(
        'Vence: 30/11/2026 → 15/01/2027',
      );
    });

    it('resolución de conflicto: decisión y operación corta', () => {
      expect(resumenDeDatos({ operacion_id: '1f2e3d4c-aaaa-bbbb', tipo: 'venta_contado', decision: 'forzar', ajustes: [] })).toBe(
        'Decisión: forzar la venta · Operación: 1f2e3d4c · Tipo: venta_contado',
      );
      expect(resumenDeDatos({ decision: 'rechazar', motivo: 'duplicada' })).toBe('Decisión: rechazar · Motivo: duplicada');
    });

    it('lote sincronizado: cuenta lo que importa', () => {
      expect(
        resumenDeDatos({ lote: 'abc', resumen: { confirmadas: 3, rechazadas: 0, en_conflicto: 1, duplicadas: 1, errores_temporales: 0 } }),
      ).toBe('Lote: 3 confirmadas, 1 en conflicto, 1 duplicada');
    });

    it('ids y códigos conocidos, y antes/después de listas y números', () => {
      expect(resumenDeDatos({ codigo: 'S-01' })).toBe('Código: S-01');
      expect(resumenDeDatos({ venta_id: 8, pago_id: 3 })).toBe('Venta: 8 · Pago: 3');
      expect(resumenDeDatos({ antes: ['cajero'], despues: ['cajero', 'encargado'] })).toBe('Cambio: cajero → cajero, encargado');
      expect(resumenDeDatos({ antes: 24, despues: 48 })).toBe('Cambio: 24 → 48');
    });

    it('un valor con HTML queda como texto (se escapa al mostrarlo) y un resumen largo se recorta', () => {
      expect(resumenDeDatos({ motivo: '<b>x</b>' })).toBe('Motivo: <b>x</b>');
      const largo = resumenDeDatos({ motivo: 'm'.repeat(400) });
      expect(largo.length).toBe(140);
      expect(largo.endsWith('…')).toBe(true);
    });
  });
});
