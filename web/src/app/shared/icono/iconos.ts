/**
 * Catálogo de íconos de trazo del rediseño (rejilla 24x24, trazo 1.5-1.75).
 * Los trazos son los mismos del canvas de Design. El nombre es lo que se pasa a
 * <fs-icono nombre="..."> -- no agregar íconos fuera de este mapa.
 */
export const ICONOS = {
  // Navegación y acciones
  busqueda: 'M4 11a7 7 0 1 0 14 0a7 7 0 1 0 -14 0M20 20l-4-4',
  usuario: 'M8 8a4 4 0 1 0 8 0a4 4 0 1 0 -8 0M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1',
  carrito: 'M5 8h14l-1 12H6L5 8zM9 8V6a3 3 0 0 1 6 0v2',
  menu: 'M4 8h16M4 16h16',
  'flecha-derecha': 'M5 12h14M13 6l6 6-6 6',
  'flecha-izquierda': 'M19 12H5M11 6l-6 6 6 6',
  'chevron-derecha': 'M9 6l6 6-6 6',
  'chevron-izquierda': 'M15 6l-6 6 6 6',
  'chevron-abajo': 'M6 9l6 6 6-6',
  check: 'M5 12l5 5 9-10',
  cerrar: 'M6 6l12 12M18 6L6 18',
  mas: 'M12 5v14M5 12h14',
  menos: 'M5 12h14',
  editar: 'M4 20h4l11-11-4-4L4 16zM13 7l4 4',
  apagar: 'M12 3v9M6.3 6.3a8 8 0 1 0 11.4 0',
  basura: 'M4 7h16M10 7V4h4v3M6 7l1 13h10l1-13M10 11v6M14 11v6',
  filtros: 'M4 7h10M18 7h2M4 17h2M10 17h10M14 5v4M8 15v4',
  descargar: 'M12 4v12M7 11l5 5 5-5M4 20h16',
  subir: 'M12 16V4M7 9l5-5 5 5M4 20h16',
  salir: 'M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10',
  'enlace-externo': 'M14 4h6v6M20 4l-9 9M18 14v6H4V6h6',
  estrella: 'M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2-5.5-2.9-5.5 2.9 1-6.2L3 9.6l6.2-.9z',
  corazon: 'M12 21s-8-5.2-8-11a5 5 0 0 1 8-3.5A5 5 0 0 1 20 10c0 5.8-8 11-8 11z',
  refrescar: 'M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7',
  historial: 'M3 12a9 9 0 1 0 3-6.7M3 4v5h5M12 8v4l3 2',
  imagen: 'M4 5h16v14H4zM4 15l4-4 4 4 3-3 5 5M15 9.5v.01',
  microfono: 'M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v3',
  enviar: 'M3 11l18-8-8 18-2-8z',
  'codigo-barras': 'M4 6v12M8 6v12M12 6v12M17 6v12M20 6v12',

  // Campos
  correo: 'M3 6h18v12H3zM3 7l9 6 9-6',
  candado: 'M6 11h12v10H6zM8 11V7a4 4 0 0 1 8 0v4',
  ojo: 'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM9 12a3 3 0 1 0 6 0a3 3 0 1 0 -6 0',
  edificio: 'M4 21V5l8-2 8 2v16M9 21v-4h6v4M8 9h.01M12 9h.01M16 9h.01M8 13h.01M12 13h.01M16 13h.01',
  calendario: 'M4 6h16v14H4zM4 10h16M8 3v4M16 3v4',
  ubicacion: 'M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11zM9.5 10a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0 -5 0',

  // Tienda
  camisa: 'M8 3l-5 3 2 4 3-1v11h8V9l3 1 2-4-5-3a4 4 0 0 1-8 0z',
  tienda: 'M3 9l2-5h14l2 5M3 9v11h18V9M3 9h18M9 20v-6h6v6',
  inventario: 'M3 8l9-5 9 5v8l-9 5-9-5zM3 8l9 5 9-5M12 13v8',
  camion: 'M2 6h11v10H2zM13 10h4l3 3v3h-7M6 19m-1.5 0a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0 -3 0M17 19m-1.5 0a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0 -3 0',
  telefono: 'M7 2h10v20H7zM11 18h2',
  destellos:
    'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7z',
  etiqueta: 'M3 12V4h8l9 9-8 8zM7.5 8.5v.01',
  'sin-tienda': 'M3 9l2-5h14l2 5M3 9v11h18V9M3 9h18M9 20v-6h6v6M3 3l18 18',
  'sin-resultados': 'M4 11a7 7 0 1 0 14 0a7 7 0 1 0 -14 0M20 20l-4-4M9 9l4 4M13 9l-4 4',

  // Pago y confianza
  'escudo-check': 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM8.5 12l2.5 2.5 4.5-5',
  escudo: 'M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z',
  tarjeta: 'M3 6h18v12H3zM3 10h18M7 15h3',
  qr: 'M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h3v3h-3zM20 14v.01M14 20h6',
  dinero: 'M3 7h18v10H3zM9.5 12a2.5 2.5 0 1 0 5 0a2.5 2.5 0 1 0 -5 0M6 10v.01M18 14v.01',
  auriculares: 'M4 14v-2a8 8 0 0 1 16 0v2M4 14h3v5H4zM17 14h3v5h-3zM20 19c0 2-2 3-5 3h-2',

  // Estados
  advertencia: 'M12 3l10 18H2zM12 10v5M12 18v.01',
  alerta: 'M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0M12 7v6M12 16.5v.01',
  reloj: 'M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0M12 7v5l3 2',
  'reloj-arena': 'M7 3h10M7 21h10M8 3v4l4 5-4 5v4M16 3v4l-4 5 4 5v4',
  'enlace-roto':
    'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3A4 4 0 0 0 11 18.7l1-1M4 4l16 16',

  // Menú del back office
  dashboard: 'M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z',
  categorias: 'M12 3l9 5-9 5-9-5zM3 13l9 5 9-5',
  envios: 'M3 11l18-8-8 18-2-8z',
  promociones:
    'M19 5L5 19M6 7.5a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0 -3 0M15 16.5a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0 -3 0',
  grafico: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  tendencia: 'M3 17l6-6 4 4 8-8M15 7h6v6',
  usuarios:
    'M16 19v-1a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v1M6.5 10a3.5 3.5 0 1 0 7 0a3.5 3.5 0 1 0 -7 0M20 19v-1a4 4 0 0 0-3-3.8M16 3.2a3.5 3.5 0 0 1 0 6.6',
  'ojo-tachado':
    'M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12zM9 12a3 3 0 1 0 6 0a3 3 0 1 0 -6 0M4 4l16 16',
  transferencia: 'M4 8h14M14 4l4 4-4 4M20 16H6M10 12l-4 4 4 4',
  imprimir: 'M7 9V3h10v6M7 17H4V9h16v8h-3M7 14h10v7H7z',
  bandeja: 'M4 13l2-8h12l2 8M4 13v6h16v-6M4 13h5l1 2h4l1-2h5',
  deshacer: 'M9 14L4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3',
  carnet: 'M3 5h18v14H3zM8.5 11a2 2 0 1 0 4 0a2 2 0 1 0 -4 0M6 16c.5-2 5.5-2 6 0M15 10h3M15 14h3',
  paleta:
    'M12 3a9 9 0 1 0 0 18c1.4 0 2-1 2-2 0-1.5-1-1.8-1-3 0-1 1-2 2-2h3a3 3 0 0 0 3-3c0-4.4-4-8-9-8zM7.5 11v.01M10 7.5v.01M14.5 7.5v.01',
  sol: 'M8 12a4 4 0 1 0 8 0a4 4 0 1 0 -8 0M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19',
  mapa: 'M9 4L3 6v14l6-2 6 2 6-2V4l-6 2zM9 4v14M15 6v14',
  llave: 'M3 17a4 4 0 1 0 8 0a4 4 0 1 0 -8 0M10 14l10-10M16 8l3 3M13 11l2 2',
  campana: 'M6 16V11a6 6 0 0 1 12 0v5l2 2H4zM10 21h4',
  movil: 'M9 2h6a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2zM11 18h2',
  libelula: 'M12 3v18M4 8c4-3 12-3 16 0M5 14c4-2 10-2 14 0',
  // Cierres de caja: caja registradora (pantalla arriba, cuerpo con cajón abajo).
  'caja-registradora': 'M7 3h10v6H7zM4 9h16v11H4zM8 14h8M8 17h4',
} as const;

export type NombreIcono = keyof typeof ICONOS;
