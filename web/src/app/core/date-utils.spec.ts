import { diaLocalDe, fechaDesdeIso, fechaLocalIso, instanteServidor } from './date-utils';

describe('instanteServidor', () => {
  it('lee un instante con "Z" como UTC', () => {
    expect(instanteServidor('2026-11-07T03:12:00Z').toISOString()).toBe('2026-11-07T03:12:00.000Z');
  });

  it('respeta un desfase explícito', () => {
    expect(instanteServidor('2026-11-06T23:12:00-04:00').toISOString()).toBe('2026-11-07T03:12:00.000Z');
    expect(instanteServidor('2026-11-06T23:12:00+00:00').toISOString()).toBe('2026-11-06T23:12:00.000Z');
  });

  it('tolera la forma vieja sin zona y la lee como UTC', () => {
    expect(instanteServidor('2026-11-07T03:12:00').toISOString()).toBe('2026-11-07T03:12:00.000Z');
    expect(instanteServidor('2026-11-07T03:12:00.123456').toISOString()).toBe('2026-11-07T03:12:00.123Z');
  });

  it('con y sin zona dan el mismo instante', () => {
    expect(instanteServidor('2026-11-07T03:12:00').getTime()).toBe(instanteServidor('2026-11-07T03:12:00Z').getTime());
  });

  it('un día sin hora es medianoche LOCAL (no un instante UTC)', () => {
    const fecha = instanteServidor('2026-11-04');
    expect([fecha.getFullYear(), fecha.getMonth(), fecha.getDate(), fecha.getHours()]).toEqual([2026, 10, 4, 0]);
  });

  it('un valor ilegible da una fecha inválida', () => {
    expect(Number.isNaN(instanteServidor('no es fecha').getTime())).toBe(true);
  });
});

describe('diaLocalDe', () => {
  it('es el día calendario LOCAL del instante, no el del texto UTC', () => {
    // Un instante cualquiera: su día local sale de los getters locales, sea cual sea la zona de la máquina.
    const instante = new Date(2026, 10, 6, 23, 12, 0); // 23:12 locales
    expect(diaLocalDe(instante.toISOString())).toBe('2026-11-06');
    const madrugada = new Date(2026, 10, 6, 0, 30, 0); // 00:30 locales
    expect(diaLocalDe(madrugada.toISOString())).toBe('2026-11-06');
  });

  it('tolera la forma sin zona (se asume UTC)', () => {
    const instante = new Date(2026, 10, 6, 23, 12, 0);
    const sinZona = instante.toISOString().replace('Z', '').replace(/\.\d+$/, '');
    expect(diaLocalDe(sinZona)).toBe('2026-11-06');
  });

  it('un valor ilegible da vacío (nunca coincide con un día)', () => {
    expect(diaLocalDe('xx')).toBe('');
  });

  describe('en la hora de Bolivia (UTC-4), si el entorno deja cambiar la zona', () => {
    // El ejecutor de pruebas corre en Node; `process` no está en los tipos del proyecto (son de navegador).
    const entorno = (globalThis as unknown as { process?: { env: Record<string, string | undefined> } }).process?.env;
    const zonaOriginal = entorno?.['TZ'];

    afterEach(() => {
      if (!entorno) return;
      if (zonaOriginal === undefined) delete entorno['TZ'];
      else entorno['TZ'] = zonaOriginal;
    });

    it('una venta de las 23:12 en Bolivia (03:12 UTC del día siguiente) es del día de Bolivia', () => {
      if (!entorno) return;
      entorno['TZ'] = 'America/La_Paz';
      // Si el entorno no permite cambiar la zona en caliente, la prueba general de arriba ya cubre el caso.
      if (new Date(2026, 10, 7, 12).getTimezoneOffset() !== 240) return;

      expect(diaLocalDe('2026-11-07T03:12:00Z')).toBe('2026-11-06');
      expect(diaLocalDe('2026-11-07T03:12:00')).toBe('2026-11-06');
      // El corte de texto que se usaba antes daba otro día.
      expect('2026-11-07T03:12:00Z'.slice(0, 10)).toBe('2026-11-07');
      // Y 04:00 UTC ya es la medianoche siguiente en Bolivia.
      expect(diaLocalDe('2026-11-07T04:00:00Z')).toBe('2026-11-07');
    });
  });
});

describe('fechaLocalIso y fechaDesdeIso', () => {
  it('son inversas y usan el calendario local', () => {
    const fecha = new Date(2026, 10, 6, 23, 59);
    expect(fechaLocalIso(fecha)).toBe('2026-11-06');
    expect(fechaLocalIso(fechaDesdeIso('2026-11-06'))).toBe('2026-11-06');
  });
});
