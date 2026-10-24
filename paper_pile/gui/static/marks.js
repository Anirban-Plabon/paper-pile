// Tailwind's in-browser compiler (NiceGUI's tailwindcss.min.js) adds a performance mark and
// measure on every rebuild — every class change in the page — and never clears them; the
// browser keeps user-timing entries forever, so they piled up for the whole session (P20).
// The app reads none of them: drop them now and then.
(function () {
  setInterval(() => {
    performance.clearMarks();
    performance.clearMeasures();
  }, 30000);
})();
