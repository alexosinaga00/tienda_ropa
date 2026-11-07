// Único lugar donde el Angular sabe dónde vive el backend. apiUrl la usan
// authInterceptor (agrega el JWT) y error.interceptor (muestra el error) en
// cada HttpClient.get/post/... de la app -- ningún componente arma la URL a
// mano. Este archivo (`ng serve`) apunta al backend local; el build de
// producción usa environment.ts, con la URL de Railway. El backend, a su
// vez, solo acepta peticiones de este origin si está en CORS_ORIGINS
// (backend/app/core/config.py) -- en local coincide con localhost:4200.
export const environment = {
  production: false,
  apiUrl: 'http://localhost:8000/api/v1',
  // Avisos push (FCM): identificadores públicos del proyecto web y clave VAPID pública, sin secretos. Ver environment.ts.
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
