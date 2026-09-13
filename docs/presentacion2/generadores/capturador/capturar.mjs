// Capturas de pantalla de la web de FashionStore para el documento (Ciclo 2).
//
// Abre una ventana de Chrome visible en la pantalla de login. La persona inicia
// sesión a mano (el script NUNCA escribe credenciales). En cuanto sale del login,
// recorre las pantallas del rol y guarda cada captura en ../capturas/.
//
// Uso:  node capturar.mjs <url-de-la-web> <admin|encargado|cajero|cliente>
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const [, , baseArg, rol] = process.argv;
if (!baseArg || !rol) {
  console.error("Uso: node capturar.mjs <url> <admin|encargado|cajero|cliente>");
  process.exit(1);
}
const BASE = baseArg.replace(/\/+$/, "");
const SALIDA = join(dirname(fileURLToPath(import.meta.url)), "..", "capturas");
mkdirSync(SALIDA, { recursive: true });

// cada paso: ruta a abrir (o null = quedarse), pestaña/texto a clickear (opcional), archivo
const RECORRIDOS = {
  admin: [
    ["/usuarios", null, "CU-03_usuarios"],
    ["/roles", null, "CU-03_roles"],
    ["/ciudades", null, "CU-04_ciudades"],
    ["/empleados", null, "CU-06_empleados"],
    ["/proveedores", null, "CU-11_proveedores"],
    ["/inventario", "Recepción", "CU-12_recepcion"],
    [null, "Consolidado", "CU-14_consolidado"],
    [null, "Alertas", "CU-14_alertas"],
    [null, "Kardex", "CU-15_kardex"],
    [null, "Transferencias", "CU-15_transferencias"],
    ["/promociones", null, "CU-27_promociones"],
  ],
  encargado: [
    ["/reservas", null, "CU-19_reservas_sucursal"],
    ["/dashboard", null, "CU-19_dashboard_reservas_hoy"],
  ],
  cajero: [
    ["/caja", null, "CU-30_caja"],
    [null, "Ventas de hoy", "CU-28_ventas_de_hoy"],
  ],
  cliente: [
    ["/catalogo", null, "CU-10_catalogo_busqueda"],
    ["/carrito", null, "CU-23_carrito"],
    ["/mis-reservas", null, "CU-17_mis_reservas"],
    ["__detalle_reserva__", null, "CU-18_detalle_reserva_cancelar"],
    ["/mis-compras", null, "CU-26_mis_compras"],
    ["__detalle_compra__", null, "CU-26_comprobante"],
  ],
};

const pasos = RECORRIDOS[rol];
if (!pasos) {
  console.error("Rol desconocido:", rol);
  process.exit(1);
}

const browser = await chromium.launch({ channel: "chrome", headless: false });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(`${BASE}/login`);
console.log(`\n>>> Iniciá sesión con la cuenta de ${rol} en la ventana de Chrome.`);
console.log(">>> Tenés 5 minutos; al salir del login empiezan las capturas.\n");
await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 5 * 60 * 1000 });
await page.waitForTimeout(2500);

async function esperarCarga() {
  await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1500);
}

for (const [ruta, clic, archivo] of pasos) {
  try {
    if (ruta === "__detalle_reserva__" || ruta === "__detalle_compra__") {
      const selector = ruta === "__detalle_reserva__" ? 'a[href*="/mis-reservas/"]' : 'a[href*="/mis-compras/"]';
      const enlace = page.locator(selector).first();
      if ((await enlace.count()) === 0) {
        console.log(`  - ${archivo}: no hay registros para abrir, se omite`);
        continue;
      }
      await enlace.click();
    } else if (ruta) {
      await page.goto(`${BASE}${ruta}`);
    }
    await esperarCarga();
    if (clic) {
      const pestana = page.getByText(clic, { exact: true }).first();
      if ((await pestana.count()) > 0) {
        await pestana.click();
        await esperarCarga();
      } else {
        console.log(`  - ${archivo}: no encontré «${clic}», capturo la pantalla tal cual`);
      }
    }
    const destino = join(SALIDA, `${archivo}.png`);
    await page.screenshot({ path: destino });
    console.log(`  ✓ ${archivo}.png`);
  } catch (err) {
    console.log(`  ✗ ${archivo}: ${err.message.split("\n")[0]}`);
  }
}

await browser.close();
console.log(`\nListo. Capturas en ${SALIDA}`);
