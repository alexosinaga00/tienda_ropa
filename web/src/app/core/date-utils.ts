/** `venta.fecha`/`reserva.fecha_visita` vienen del backend en hora LOCAL
 * del servidor, sin offset (server_default now() de Postgres) -- comparar
 * contra toISOString() (UTC) desalinea la fecha cerca de medianoche. Se
 * arma "hoy" con el mismo calendario local, no UTC. */
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
