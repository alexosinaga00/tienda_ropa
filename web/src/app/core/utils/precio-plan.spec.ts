import {
  DIAS_PRUEBA,
  ahorroAnual,
  aNumeroBs,
  equivalenteMensualAnual,
  formatearBs,
  formatearNumeroBs,
  montoDelPeriodo,
  tienePrecio,
} from './precio-plan';

describe('precio-plan', () => {
  it('la prueba dura 14 días', () => {
    expect(DIAS_PRUEBA).toBe(14);
  });

  it('convierte el texto decimal del servidor a número', () => {
    expect(aNumeroBs('120.00')).toBe(120);
    expect(aNumeroBs(290)).toBe(290);
    expect(aNumeroBs(null)).toBeNull();
    expect(aNumeroBs(undefined)).toBeNull();
    expect(aNumeroBs('')).toBeNull();
    expect(aNumeroBs('abc')).toBeNull();
  });

  it('tiene precio solo si es mayor que cero', () => {
    expect(tienePrecio('120.00')).toBe(true);
    expect(tienePrecio('0.00')).toBe(false);
    expect(tienePrecio(null)).toBe(false);
  });

  it('el anual es mensual x 12 menos 20 %', () => {
    expect(montoDelPeriodo(120, 'mensual')).toBe(120);
    expect(montoDelPeriodo(120, 'anual')).toBe(1152);
    expect(montoDelPeriodo(290, 'anual')).toBe(2784);
    expect(montoDelPeriodo(590, 'anual')).toBe(5664);
    expect(equivalenteMensualAnual(120)).toBe(96);
    expect(ahorroAnual(120)).toBe(288);
  });

  it('da formato de Bolivia: punto de miles, coma decimal y sin ",00"', () => {
    expect(formatearNumeroBs(120)).toBe('120');
    expect(formatearNumeroBs(1152)).toBe('1.152');
    expect(formatearNumeroBs(99.5)).toBe('99,50');
    expect(formatearNumeroBs(12345.67)).toBe('12.345,67');
    expect(formatearBs('590.00')).toBe('Bs 590');
    expect(formatearBs(5664)).toBe('Bs 5.664');
    expect(formatearBs(null)).toBe('');
  });
});
