// Versión de producción de environment.development.ts: Angular la usa en
// vez de esa cuando se compila con `ng build` (fileReplacements en
// angular.json). apiUrl acá es la URL pública del backend en Railway.
export const environment = {
  production: true,
  apiUrl: 'https://backend-production-0714.up.railway.app/api/v1',
  primeuiLicense:
    'eyJpZCI6IjAzNjE2ODM4LTU4NTktNGVlOC1iZDVlLTI1ZTBlZjU1YzFlZiIsInByb2R1Y3QiOiJwcmltZXVpIiwidGllciI6ImNvbW11bml0eSIsInR5cGUiOiJkZXYiLCJpYXQiOjE3ODg0MzcyMzYsImV4cCI6MTgxOTk3MzIzNn0.lQq8X44cgVsOFdC4Q1OALL1FdVApsiAM0oBAu2QSLPG1hIWUFacPuMxwTiJoS3naQtjnjDkSVCeKC19zA3M3Bw',
};
