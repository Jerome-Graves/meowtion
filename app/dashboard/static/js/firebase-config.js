// Firebase web config for the Meowtion project.
//
// The apiKey and these values are NOT secret. They identify the project to the
// browser. Security is enforced by Firebase Auth + the database rules, not by
// hiding this. (Never put a service-account / admin key here.)
//
window.firebaseConfig = {
  apiKey: "AIzaSyByj9WEj_9Gt65Zwc2ivJOfNcZN9fREn88",
  authDomain: "meowtion-app.firebaseapp.com",
  databaseURL: "https://meowtion-app-default-rtdb.europe-west1.firebasedatabase.app",
  projectId: "meowtion-app",
  storageBucket: "meowtion-app.firebasestorage.app",
  messagingSenderId: "99227124719",
  appId: "1:99227124719:web:c47197ceb06833b813ec1a",
};

// Bump this when the privacy policy changes; signup records the version a user agreed to.
window.PRIVACY_VERSION = "2026-06-21";
