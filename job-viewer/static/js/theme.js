(function () {
  var STORAGE_KEY = "theme";

  function preferredTheme() {
    try {
      var saved = localStorage.getItem(STORAGE_KEY);
      if (saved === "light" || saved === "dark") {
        return saved;
      }
    } catch (e) {
      /* private mode / blocked storage */
    }
    if (
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
    ) {
      return "dark";
    }
    return "light";
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-bs-theme", theme);
  }

  function syncToggle(theme) {
    var btn = document.getElementById("themeToggle");
    var icon = document.getElementById("themeIcon");
    if (!btn || !icon) {
      return;
    }
    var isDark = theme === "dark";
    icon.className = isDark ? "bi bi-sun" : "bi bi-moon-stars";
    btn.setAttribute(
      "aria-label",
      isDark ? "Switch to light mode" : "Switch to dark mode"
    );
    btn.setAttribute("title", isDark ? "Light mode" : "Dark mode");
  }

  function setTheme(theme) {
    applyTheme(theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (e) {
      /* ignore */
    }
    syncToggle(theme);
  }

  // Expose for the FOUC head snippet / debugging
  window.StarfallTheme = {
    preferredTheme: preferredTheme,
    applyTheme: applyTheme,
    setTheme: setTheme,
    syncToggle: syncToggle,
  };

  document.addEventListener("DOMContentLoaded", function () {
    var theme = preferredTheme();
    applyTheme(theme);
    syncToggle(theme);

    var btn = document.getElementById("themeToggle");
    if (btn) {
      btn.addEventListener("click", function () {
        var current =
          document.documentElement.getAttribute("data-bs-theme") || "light";
        setTheme(current === "dark" ? "light" : "dark");
      });
    }
  });
})();
