// Everything visual is applied before first paint, so the app never
// flashes the default look and then corrects itself.
//
// The lookup order matches appearancePref() in app.js exactly:
//     your manual change  →  the selected theme  →  the app default
// It is duplicated here rather than imported because app.js loads at the
// end of the body, which is far too late to prevent the flash. The theme
// VALUES are the only thing repeated; keep them in step with
// THEME_PRESETS, or a themed reload will flicker.
(function () {
  const _r = document.documentElement;
  const THEMES = {
    default: { palette: "default", glass: "on", radius: "14" },
    manuscript: { palette: "parchment", font: "serif", glass: "off", radius: "6", density: "spacious" },
    terminal: { palette: "carbon", font: "mono", glass: "off", radius: "2", density: "compact" },
    study: { palette: "sage", font: "serif", glass: "on", radius: "16" },
    abyss: { palette: "ocean", glass: "on", "glass-blur": "26", radius: "14" },
    ember: { palette: "ember", glass: "on", radius: "12" },
    orchid: { palette: "plum", glass: "on", radius: "18" },
    blueprint: { palette: "ocean", font: "mono", glass: "off", radius: "4", density: "compact" },
    graphite: { palette: "carbon", glass: "off", radius: "4" },
    lagoon: { palette: "lagoon", glass: "on", radius: "14" },
  };
  const preset = THEMES[localStorage.getItem("themePreset")] || {};
  const pref = (key, fallback) =>
    localStorage.getItem(key) ?? preset[key] ?? fallback;

  const theme = pref("theme", "system");
  if (theme && theme !== "system") _r.dataset.theme = theme;
  // data-mode is the RESOLVED light/dark, which the palettes match on, 
  // under "System" there is no data-theme for CSS to hang off, so without
  // this every palette would paint its light set on a dark desktop until
  // app.js caught up.
  _r.dataset.mode =
    theme === "light" || theme === "dark"
      ? theme
      : window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";

  const palette = pref("palette", "default");
  if (palette && palette !== "default") _r.dataset.palette = palette;
  const accent = pref("accent", "indigo");
  if (accent && accent !== "indigo") _r.dataset.accent = accent;
  if (localStorage.getItem("contrast") === "on") _r.dataset.contrast = "on";

  _r.dataset.fontsize = pref("fontsize", "normal");
  _r.dataset.font = pref("font", "system");
  _r.dataset.density = pref("density", "comfortable");
  // Performance mode, mirrored from perfModeOn() in settings.js: "on", or
  // "auto" on a small machine (2 cores or 4 GB or fewer), or the operating
  // system asking for less transparency. It takes the glass and the motion
  // off before first paint so a small laptop never draws the blurred frame
  // it is about to be spared. Keep the three readings in step.
  const perfPref = pref("perf", "auto");
  const small =
    (navigator.deviceMemory && navigator.deviceMemory <= 4) ||
    (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 2);
  const lessGlass = window.matchMedia("(prefers-reduced-transparency: reduce)").matches;
  const perf = perfPref === "on" || (perfPref === "auto" && (small || lessGlass));
  _r.dataset.perf = perf ? "on" : "off";
  _r.dataset.glass = perf ? "off" : pref("glass", "on");
  _r.dataset.motion = perf ? "reduced" : pref("motion", "auto");
  _r.dataset.themePreset = localStorage.getItem("themePreset") || "";
  _r.style.setProperty("--radius", pref("radius", "14") + "px");
  _r.style.setProperty("--glass-blur", pref("glass-blur", "14") + "px");
  _r.style.setProperty("--bg-art-opacity", Number(pref("bg-intensity", "45")) / 100);
  const page = pref("page-bg", null);
  if (page) _r.style.setProperty("--page", page);
})();
