/**
 * Seguridad de la caché del Service Worker y validez del manifest (E13, 4.11 y 4.12).
 *
 * Lee los archivos REALES del disco (`ngsw-config.json` en la raíz de web/ y `public/manifest.webmanifest`
 * con `public/icons/`): no hay @types/node ni `resolveJsonModule`, y `.webmanifest` no se puede importar como
 * JSON. Las pruebas corren en Node, así que se usa `process.getBuiltinModule('node:fs')`. Si ese acceso
 * no existe, la primera prueba falla a propósito: ninguna de las demás puede pasar "en vacío".
 */

interface ModuloFs {
  readFileSync(ruta: string): Uint8Array;
  existsSync(ruta: string): boolean;
}

interface ProcesoNode {
  cwd(): string;
  getBuiltinModule?(nombre: string): unknown;
}

interface Recursos {
  files?: string[];
  urls?: string[];
}

interface GrupoAssets {
  name: string;
  resources: Recursos;
}

interface GrupoDatos {
  name: string;
  urls: string[];
  cacheConfig?: { strategy?: string; maxAge?: string; maxSize?: number; timeout?: string };
}

interface ConfigNgsw {
  assetGroups?: GrupoAssets[];
  dataGroups?: GrupoDatos[];
}

interface IconoManifest {
  src: string;
  sizes: string;
  type?: string;
  purpose?: string;
}

interface Manifest {
  display?: string;
  theme_color?: string;
  background_color?: string;
  start_url?: string;
  scope?: string;
  icons?: IconoManifest[];
}

const proceso = (globalThis as unknown as { process?: ProcesoNode }).process;
const fs = proceso?.getBuiltinModule?.('node:fs') as ModuloFs | undefined;
const raiz = proceso?.cwd().replace(/\\/g, '/') ?? '';

function leer(rutaDesdeRaiz: string): Uint8Array {
  if (!fs) {
    throw new Error('No hay acceso al sistema de archivos desde la prueba (process.getBuiltinModule).');
  }
  return fs.readFileSync(`${raiz}/${rutaDesdeRaiz}`);
}

function leerJson<T>(rutaDesdeRaiz: string): T {
  return JSON.parse(new TextDecoder('utf-8').decode(leer(rutaDesdeRaiz))) as T;
}

function existe(rutaDesdeRaiz: string): boolean {
  return fs?.existsSync(`${raiz}/${rutaDesdeRaiz}`) ?? false;
}

/** "1d", "12h", "30m", "5s", "250u" (milisegundos) -> milisegundos. Acepta la forma compuesta "1d12h". */
export function duracionAMs(texto: string): number {
  const unidades: Record<string, number> = { d: 86_400_000, h: 3_600_000, m: 60_000, s: 1_000, u: 1 };
  const trozos = texto.match(/\d+[dhmsu]/g);
  if (!trozos || trozos.join('') !== texto) {
    throw new Error(`Duración no reconocida: "${texto}"`);
  }
  return trozos.reduce((total, t) => total + Number(t.slice(0, -1)) * (unidades[t.slice(-1)] ?? 0), 0);
}

/** Alto y ancho de un PNG leídos de su cabecera IHDR (firma de 8 bytes + longitud + "IHDR" + ancho + alto). */
function dimensionesPng(bytes: Uint8Array): { ancho: number; alto: number } | null {
  const firma = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
  if (bytes.length < 24 || firma.some((valor, i) => bytes[i] !== valor)) {
    return null;
  }
  const vista = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  return { ancho: vista.getUint32(16), alto: vista.getUint32(20) };
}

/** Rutas que llevan datos privados o de negocio: jamás deben entrar en la caché del Service Worker. */
const RUTAS_PROHIBIDAS = [
  '/auth',
  '/sincronizacion',
  '/mi-empresa',
  '/plataforma',
  '/analitica',
  '/reportes',
  '/copias-seguridad',
  '/usuarios',
  '/ventas',
  '/carrito',
];

const SIETE_DIAS_MS = 7 * 86_400_000;

/** Única excepción a "solo /public/": las fotos del catálogo, que son públicas y viven en Cloudinary. */
const FOTOS_CATALOGO = 'https://res.cloudinary.com/*/image/upload/**';

describe('ngsw-config.json: seguridad de la caché', () => {
  let config: ConfigNgsw;

  beforeAll(() => {
    config = leerJson<ConfigNgsw>('ngsw-config.json');
  });

  const dataGroups = (): GrupoDatos[] => config.dataGroups ?? [];
  const urlsDeDatos = (): string[] => dataGroups().flatMap((g) => g.urls);
  // Los assetGroups declaran `files` (rutas del build) y `urls` (externas): ambas cuentan.
  const patronesDeAssets = (): string[] =>
    (config.assetGroups ?? []).flatMap((g) => [...(g.resources.files ?? []), ...(g.resources.urls ?? [])]);

  it('puede leer los archivos reales (sin esto ninguna otra prueba vale)', () => {
    expect(fs).toBeDefined();
    expect(existe('ngsw-config.json')).toBe(true);
    expect(existe('public/manifest.webmanifest')).toBe(true);
    expect(dataGroups().length).toBeGreaterThan(0);
    expect(patronesDeAssets().length).toBeGreaterThan(0);
  });

  it('TODA url de dataGroups es de la API pública ("/public/") o de las fotos públicas del catálogo en Cloudinary', () => {
    expect(urlsDeDatos().length).toBeGreaterThan(0);
    for (const grupo of dataGroups()) {
      expect(grupo.urls.length, `el grupo "${grupo.name}" no tiene urls`).toBeGreaterThan(0);
    }
    const ajenas = urlsDeDatos().filter((url) => !url.includes('/public/') && url !== FOTOS_CATALOGO);
    expect(ajenas).toEqual([]);
  });

  it('las fotos del catálogo (Cloudinary) se guardan solo como imágenes, pocas y por pocos días', () => {
    const grupo = dataGroups().find((g) => g.name === 'fotos-catalogo');
    expect(grupo, 'falta el grupo fotos-catalogo').toBeDefined();
    expect(grupo?.urls).toEqual([FOTOS_CATALOGO]);
    expect(grupo?.cacheConfig?.maxSize).toBeLessThanOrEqual(100);
    expect(duracionAMs(grupo?.cacheConfig?.maxAge ?? '')).toBeLessThanOrEqual(SIETE_DIAS_MS);
  });

  it.each(RUTAS_PROHIBIDAS)('ninguna url de dataGroups ni de assetGroups contiene %s', (ruta) => {
    const conLaRuta = [...urlsDeDatos(), ...patronesDeAssets()].filter((url) => url.includes(ruta));
    expect(conLaRuta).toEqual([]);
  });

  it('la contratación pública (pedidos, token, PayPal) queda fuera de la caché: cada patrón público tiene su exclusión', () => {
    const urls = urlsDeDatos();
    const publicas = urls.filter((url) => !url.startsWith('!') && url.endsWith('/api/v1/public/**'));
    expect(publicas.length).toBeGreaterThan(0);
    for (const patron of publicas) {
      const exclusion = `!${patron.replace(/public\/\*\*$/, 'public/contratacion/**')}`;
      expect(urls, `falta ${exclusion}`).toContain(exclusion);
    }
    // Nada que se cachee puede nombrar la contratación: solo aparece en las exclusiones.
    const cacheables = urls.filter((url) => !url.startsWith('!'));
    expect(cacheables.filter((url) => url.includes('contratacion'))).toEqual([]);
  });

  it('ninguna dataGroup guarda respuestas más de 7 días y todas declaran maxAge', () => {
    for (const grupo of dataGroups()) {
      const maxAge = grupo.cacheConfig?.maxAge;
      expect(maxAge, `el grupo "${grupo.name}" no declara maxAge`).toBeDefined();
      expect(duracionAMs(maxAge ?? '')).toBeLessThanOrEqual(SIETE_DIAS_MS);
    }
  });

  it('las dataGroups usan la estrategia freshness (red primero: nunca datos viejos si hay conexión)', () => {
    for (const grupo of dataGroups()) {
      expect(grupo.cacheConfig?.strategy, `grupo "${grupo.name}"`).toBe('freshness');
    }
  });

  it('el intérprete de duraciones distingue días, horas y valores inválidos', () => {
    expect(duracionAMs('1d')).toBe(86_400_000);
    expect(duracionAMs('7d')).toBe(SIETE_DIAS_MS);
    expect(duracionAMs('8d')).toBeGreaterThan(SIETE_DIAS_MS);
    expect(duracionAMs('12h')).toBe(43_200_000);
    expect(duracionAMs('1d12h')).toBe(129_600_000);
    expect(() => duracionAMs('mucho')).toThrow();
  });
});

/**
 * Avisos push web (FCM): el Service Worker de Firebase convive con el de Angular. Va con su propio alcance, fuera del
 * precaché de ngsw, y no puede abrir ninguna vía para guardar respuestas (nada autenticado en caché).
 */
describe('Service Worker de Firebase (avisos push) junto al de Angular', () => {
  let config: ConfigNgsw;
  let sw: string;
  let entorno: string;

  beforeAll(() => {
    config = leerJson<ConfigNgsw>('ngsw-config.json');
    sw = new TextDecoder('utf-8').decode(leer('public/firebase-messaging-sw.js'));
    entorno = new TextDecoder('utf-8').decode(leer('src/environments/environment.ts'));
  });

  const archivosDelGrupoApp = (): string[] => config.assetGroups?.find((g) => g.name === 'app')?.resources.files ?? [];

  it('el archivo existe en public/ (se publica en la raíz del sitio)', () => {
    expect(existe('public/firebase-messaging-sw.js')).toBe(true);
  });

  it('queda FUERA del precaché de ngsw: el grupo "app" lo excluye después de "/*.js"', () => {
    const archivos = archivosDelGrupoApp();
    const incluye = archivos.indexOf('/*.js');
    const excluye = archivos.indexOf('!/firebase-messaging-sw.js');
    expect(incluye).toBeGreaterThanOrEqual(0);
    expect(excluye).toBeGreaterThan(incluye);
  });

  it('ningún otro grupo de ngsw (assets ni datos) menciona Firebase ni el Service Worker de avisos', () => {
    const todo = [
      ...(config.dataGroups ?? []).flatMap((g) => g.urls),
      ...(config.assetGroups ?? []).filter((g) => g.name !== 'app').flatMap((g) => [...(g.resources.files ?? []), ...(g.resources.urls ?? [])]),
    ];
    expect(todo.filter((url) => /firebase|fcm|dispositivos-push|messaging/i.test(url))).toEqual([]);
  });

  it('no guarda nada en caché: sin la API de caches, sin interceptar peticiones (fetch)', () => {
    expect(sw).not.toMatch(/\bcaches\b/);
    expect(sw).not.toMatch(/addEventListener\(\s*['"]fetch['"]/);
    expect(sw).not.toMatch(/cache\.(put|add|addAll)\(/);
  });

  it('el clic en el aviso se registra antes de cargar el SDK y corta su propio manejador', () => {
    const clic = sw.indexOf("addEventListener('notificationclick'");
    const sdk = sw.indexOf('importScripts(');
    expect(clic).toBeGreaterThanOrEqual(0);
    expect(clic).toBeLessThan(sdk);
    expect(sw).toContain('stopImmediatePropagation');
  });

  it('usa el SDK de la MISMA versión que el paquete "firebase" de package.json', () => {
    const paquete = leerJson<{ dependencies: Record<string, string> }>('package.json').dependencies['firebase'];
    expect(paquete).toMatch(/^\d+\.\d+\.\d+$/); // versión exacta, sin ^ ni ~
    const versiones = [...sw.matchAll(/firebasejs\/(\d+\.\d+\.\d+)\//g)].map((m) => m[1]);
    expect(versiones.length).toBeGreaterThan(0);
    expect(new Set(versiones)).toEqual(new Set([paquete]));
  });

  it('lleva la misma configuración pública de Firebase que environment.ts', () => {
    for (const clave of ['apiKey', 'authDomain', 'projectId', 'storageBucket', 'messagingSenderId', 'appId']) {
      const enEntorno = new RegExp(`${clave}:\\s*'([^']+)'`).exec(entorno)?.[1];
      const enSw = new RegExp(`${clave}:\\s*'([^']+)'`).exec(sw)?.[1];
      expect(enEntorno, `falta ${clave} en environment.ts`).toBeDefined();
      expect(enSw, clave).toBe(enEntorno);
    }
  });

  it('el SDK se descarga solo desde gstatic (un script externo más no se cuela)', () => {
    const origenes = [...sw.matchAll(/importScripts\(\s*'(https?:\/\/[^/']+)/g)].map((m) => m[1]);
    expect(origenes.length).toBeGreaterThan(0);
    expect(new Set(origenes)).toEqual(new Set(['https://www.gstatic.com']));
  });
});

describe('manifest.webmanifest', () => {
  let manifest: Manifest;

  beforeAll(() => {
    manifest = leerJson<Manifest>('public/manifest.webmanifest');
  });

  const iconos = (): IconoManifest[] => manifest.icons ?? [];
  // `src` es relativo al manifest, que se sirve en la raíz: "icons/x.png" -> public/icons/x.png.
  const rutaDeIcono = (icono: IconoManifest): string => `public/${icono.src.replace(/^\/+/, '')}`;

  it('se abre como app independiente con los colores del rediseño', () => {
    expect(manifest.display).toBe('standalone');
    expect(manifest.theme_color).toBe('#1B1916');
    expect(manifest.background_color).toBe('#F7F5F1');
  });

  it('start_url empieza con "/" y está dentro de scope', () => {
    expect(manifest.start_url?.startsWith('/')).toBe(true);
    expect(manifest.scope).toBeDefined();
    expect(manifest.start_url?.startsWith(manifest.scope ?? '\u0000')).toBe(true);
  });

  it('incluye un icono maskable de 512x512 y los de 192 y 512 para "any"', () => {
    const maskable = iconos().filter((i) => (i.purpose ?? '').split(' ').includes('maskable'));
    expect(maskable.some((i) => i.sizes === '512x512')).toBe(true);

    const normales = iconos().filter((i) => (i.purpose ?? 'any').split(' ').includes('any'));
    expect(normales.map((i) => i.sizes)).toEqual(expect.arrayContaining(['192x192', '512x512']));
  });

  it('CADA archivo de icono referenciado existe en public/icons', () => {
    expect(iconos().length).toBeGreaterThan(0);
    const faltantes = iconos()
      .map(rutaDeIcono)
      .filter((ruta) => !existe(ruta));
    expect(faltantes).toEqual([]);
    for (const icono of iconos()) {
      expect(rutaDeIcono(icono).startsWith('public/icons/'), icono.src).toBe(true);
    }
  });

  it('cada PNG mide lo que declara "sizes" (un icono de otro tamaño no instala la app)', () => {
    for (const icono of iconos().filter((i) => i.type === 'image/png')) {
      const dimensiones = dimensionesPng(leer(rutaDeIcono(icono)));
      expect(dimensiones, `${icono.src} no es un PNG válido`).not.toBeNull();
      expect(`${dimensiones?.ancho}x${dimensiones?.alto}`, icono.src).toBe(icono.sizes);
    }
  });

  it('los iconos de los atajos (shortcuts) también existen', () => {
    const atajos = (manifest as { shortcuts?: { icons?: IconoManifest[] }[] }).shortcuts ?? [];
    const rutas = atajos.flatMap((a) => (a.icons ?? []).map(rutaDeIcono));
    expect(rutas.filter((ruta) => !existe(ruta))).toEqual([]);
  });
});
