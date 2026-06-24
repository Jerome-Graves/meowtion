/*
 * firebase-init.js - initialise the Firebase compat SDK once.
 * Loaded after the firebase-*-compat scripts and firebase-config.js, before each
 * page script. Guards against double initialisation.
 */
(function () {
  if (window.firebase && window.firebaseConfig && !firebase.apps.length) {
    firebase.initializeApp(window.firebaseConfig);
  }
})();
