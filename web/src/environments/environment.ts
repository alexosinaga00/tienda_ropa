// Versión de producción de environment.development.ts: Angular la usa en
// vez de esa cuando se compila con `ng build` (fileReplacements en
// angular.json). apiUrl acá es la URL pública del backend en Railway.
export const environment = {
  production: true,
  apiUrl: 'https://tiendaropafashionstore-production.up.railway.app/api/v1',
  // Avisos push en el navegador (Firebase Cloud Messaging). Son identificadores PÚBLICOS del proyecto web (van en
  // cualquier página que use Firebase) y la clave VAPID PÚBLICA; no hay ningún secreto aquí. El mismo bloque está
  // en public/firebase-messaging-sw.js (un Service Worker no puede importar este archivo).
  firebase: {
    apiKey: 'AIzaSyD5Abdyrk39LlMGFNbILH1rvEAu-W14r0Q',
    authDomain: 'fashionstore-96071.firebaseapp.com',
    projectId: 'fashionstore-96071',
    storageBucket: 'fashionstore-96071.firebasestorage.app',
    messagingSenderId: '337599112866',
    appId: '1:337599112866:web:a9ebcfad3643e6d06399fb',
    measurementId: 'G-WREYL37TDS',
  },
  firebaseVapidKey: 'BAsMwDk0Q8S69IiIzgWzN92yAcIuUf1Gduy-pZwfCjmnUpY46vkZkoiZcGeO_zUgXmi1bWZ-McADV26b0P5qf7M',
  primeuiLicense:
    'eyJpZCI6IjAzNjE2ODM4LTU4NTktNGVlOC1iZDVlLTI1ZTBlZjU1YzFlZiIsInByb2R1Y3QiOiJwcmltZXVpIiwidGllciI6ImNvbW11bml0eSIsInR5cGUiOiJkZXYiLCJpYXQiOjE3ODg0MzcyMzYsImV4cCI6MTgxOTk3MzIzNn0.lQq8X44cgVsOFdC4Q1OALL1FdVApsiAM0oBAu2QSLPG1hIWUFacPuMxwTiJoS3naQtjnjDkSVCeKC19zA3M3Bw',
};
