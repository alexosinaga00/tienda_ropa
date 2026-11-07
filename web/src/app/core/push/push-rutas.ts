/**
 * A qué pantalla lleva un aviso push o una notificación, según su `tipo`. Es la MISMA tabla que usa el Service Worker de
 * Firebase (`public/firebase-messaging-sw.js`, que no puede importar este archivo): si cambias una, cambia la otra.
 *
 * - Cliente de la tienda: `compra_confirmada`, `envio` y `pedido_diferido` abren la compra (`referencia_id` es el id de
 *   la venta); `reserva_preparada` abre sus reservas.
 * - Personal: `reserva` abre las reservas de la sucursal y `sincronizacion` las operaciones sincronizadas.
 * Un tipo desconocido no abre nada (la notificación queda solo en la lista).
 */
export function rutaDeAviso(
  tipo: string | null | undefined,
  referenciaId: number | string | null | undefined,
  empresaCodigo: string | null | undefined,
): string | null {
  const id = referenciaId === null || referenciaId === undefined || referenciaId === '' ? null : Number(referenciaId);
  const tienda = empresaCodigo ? `/t/${encodeURIComponent(empresaCodigo)}` : null;
  switch (tipo) {
    case 'compra_confirmada':
    case 'envio':
    case 'pedido_diferido':
      return tienda !== null && id !== null && Number.isInteger(id) ? `${tienda}/mis-compras/${id}` : null;
    case 'reserva_preparada':
      return tienda !== null ? `${tienda}/mis-reservas` : null;
    case 'reserva':
      return '/reservas';
    case 'sincronizacion':
      return '/sincronizacion';
    default:
      return null;
  }
}
