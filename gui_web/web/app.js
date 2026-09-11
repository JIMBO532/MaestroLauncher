/* MaestroLauncher web frontend -- M8 static shell, plus one real feature:
 * a user-chosen home-screen background. Everything else here is still dead
 * on purpose -- Play, the version selector and Sign in are not wired to
 * core/ yet.
 */

(function () {
  "use strict";

  /* --------------------------------------------------------------- shell -- */

  // A launcher is not a web page: dragging images or opening a context menu
  // immediately breaks the illusion of a native window. This does not touch
  // OS file drags onto the window -- those are dragenter/dragover/drop, not
  // dragstart, and are handled separately below.
  document.addEventListener("dragstart", function (event) {
    event.preventDefault();
  });
  document.addEventListener("contextmenu", function (event) {
    event.preventDefault();
  });

  // Nothing behind these controls yet. Say so in the console rather than
  // letting them look broken. Settings is excluded: it now does something.
  var pending = document.querySelectorAll(".play, .version, .account, .rail__item:not(#settings-toggle)");
  Array.prototype.forEach.call(pending, function (element) {
    element.addEventListener("click", function () {
      console.log(
        "[not wired] " +
          (element.getAttribute("aria-label") || element.textContent.trim()) +
          " is not wired up yet."
      );
    });
  });

  /* ---------------------------------------------------------- background -- */

  var DEFAULT_BACKGROUND_URL = "assets/background.jpg";
  var ACCEPTED_TYPES = ["image/png", "image/jpeg"];

  var root = document.documentElement;
  var backdrop = document.querySelector(".backdrop");
  var dropHint = document.getElementById("dropzone-hint");
  var settingsToggle = document.getElementById("settings-toggle");
  var settingsPanel = document.getElementById("settings-panel");
  var fileInput = document.getElementById("background-file-input");

  function hasBridge() {
    return !!(window.pywebview && window.pywebview.api);
  }

  function setBackgroundImage(url) {
    // Only the image is replaced; --bg, cover/center/no-repeat stay set by
    // the .backdrop rule in styles.css.
    backdrop.style.backgroundImage = 'url("' + url + '")';
  }

  // The three spots text actually sits: .brand (top-left), .account
  // (top-right) and .bottom-group (bottom-centre) in styles.css. Sampled as
  // fractions of the image so it holds at any window size.
  var REGIONS = {
    logo: [0, 0, 0.34, 0.22],
    account: [0.78, 0, 1, 0.16],
    bottom: [0.22, 0.78, 0.78, 1]
  };

  // Below this, an image is already as dark as the bundled night shot and
  // gets no extra help. Above it, darkening ramps up to maxAlpha.
  var DARK_FLOOR = 95;
  var BRIGHT_CEILING = 195;

  function regionBrightness(ctx, w, h, region) {
    var x0 = Math.max(0, Math.floor(w * region[0]));
    var y0 = Math.max(0, Math.floor(h * region[1]));
    var x1 = Math.min(w, Math.ceil(w * region[2]));
    var y1 = Math.min(h, Math.ceil(h * region[3]));
    var data = ctx.getImageData(x0, y0, Math.max(1, x1 - x0), Math.max(1, y1 - y0)).data;
    var total = 0;
    var count = 0;
    for (var i = 0; i < data.length; i += 4) {
      total += 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2];
      count += 1;
    }
    return count ? total / count : 0;
  }

  function brightnessToAlpha(brightness, maxAlpha) {
    var t = (brightness - DARK_FLOOR) / (BRIGHT_CEILING - DARK_FLOOR);
    t = Math.max(0, Math.min(1, t));
    return t * maxAlpha;
  }

  // Reads the image back off the GPU to measure it, so this runs after
  // whatever URL is already on screen, not before.
  function applyAdaptiveScrim(imageUrl) {
    var image = new Image();
    image.onload = function () {
      var w = 240;
      var h = Math.max(1, Math.round(w * (image.naturalHeight / image.naturalWidth || 0.5625)));
      var canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      var ctx = canvas.getContext("2d");
      ctx.drawImage(image, 0, 0, w, h);

      var logo = regionBrightness(ctx, w, h, REGIONS.logo);
      var account = regionBrightness(ctx, w, h, REGIONS.account);
      var bottom = regionBrightness(ctx, w, h, REGIONS.bottom);

      root.style.setProperty("--scrim-logo", brightnessToAlpha(logo, 0.62).toFixed(2));
      root.style.setProperty("--scrim-account", brightnessToAlpha(account, 0.55).toFixed(2));
      root.style.setProperty("--scrim-bottom", brightnessToAlpha(bottom, 0.55).toFixed(2));
    };
    image.onerror = function () {
      console.log("[background] could not sample brightness for scrim tuning");
    };
    image.src = imageUrl;
  }

  function applyBackground(url) {
    setBackgroundImage(url);
    applyAdaptiveScrim(url);
  }

  function resetToDefault() {
    applyBackground(DEFAULT_BACKGROUND_URL);
  }

  function handleImportResult(result) {
    if (result && result.ok && result.dataUrl) {
      applyBackground(result.dataUrl);
    } else if (result && !result.cancelled) {
      console.log("[background] import failed: " + (result.error || "unknown error"));
    }
  }

  function handleChosenFile(file) {
    if (ACCEPTED_TYPES.indexOf(file.type) === -1) {
      console.log("[background] ignored " + (file.type || "unknown type") + ", PNG or JPEG only");
      return;
    }
    var reader = new FileReader();
    reader.onload = function () {
      var dataUrl = reader.result;
      if (hasBridge()) {
        // Persisted to the app's own data directory and re-compressed there;
        // this data URL is only the instant on-screen preview.
        window.pywebview.api.import_background_data(dataUrl).then(handleImportResult);
      } else {
        // No native bridge (previewing in a plain browser): apply visually
        // only, so the adaptive scrim can still be exercised.
        applyBackground(dataUrl);
      }
    };
    reader.readAsDataURL(file);
  }

  function chooseBackground() {
    if (hasBridge()) {
      window.pywebview.api.pick_background().then(function (result) {
        handleImportResult(result);
        closeSettingsPanel();
      });
    } else {
      fileInput.click();
    }
  }

  function resetBackground() {
    closeSettingsPanel();
    if (hasBridge()) {
      window.pywebview.api.reset_background().then(resetToDefault);
    } else {
      resetToDefault();
    }
  }

  function openSettingsPanel() {
    settingsPanel.hidden = false;
    settingsToggle.setAttribute("aria-expanded", "true");
  }

  function closeSettingsPanel() {
    settingsPanel.hidden = true;
    settingsToggle.setAttribute("aria-expanded", "false");
  }

  settingsToggle.addEventListener("click", function (event) {
    event.stopPropagation();
    if (settingsPanel.hidden) {
      openSettingsPanel();
    } else {
      closeSettingsPanel();
    }
  });

  settingsPanel.addEventListener("click", function (event) {
    var action = event.target.getAttribute("data-action");
    if (action === "choose-background") {
      chooseBackground();
    } else if (action === "reset-background") {
      resetBackground();
    }
  });

  document.addEventListener("click", function (event) {
    if (!settingsPanel.hidden && !settingsPanel.contains(event.target) && event.target !== settingsToggle) {
      closeSettingsPanel();
    }
  });

  fileInput.addEventListener("change", function () {
    if (fileInput.files && fileInput.files[0]) {
      handleChosenFile(fileInput.files[0]);
    }
    fileInput.value = "";
    closeSettingsPanel();
  });

  // Drag-and-drop onto the home screen. dragover must be prevented on every
  // fire, not just the first, or the browser's default (navigate to the
  // file) wins.
  function carriesFiles(event) {
    var types = event.dataTransfer && event.dataTransfer.types;
    return !!types && Array.prototype.indexOf.call(types, "Files") !== -1;
  }

  ["dragenter", "dragover"].forEach(function (type) {
    document.addEventListener(type, function (event) {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      dropHint.hidden = false;
    });
  });

  document.addEventListener("dragleave", function (event) {
    // Only clear on leaving the window itself, not a child element.
    if (event.clientX <= 0 || event.clientY <= 0 || event.relatedTarget === null) {
      dropHint.hidden = true;
    }
  });

  document.addEventListener("drop", function (event) {
    if (!carriesFiles(event)) return;
    event.preventDefault();
    dropHint.hidden = true;
    var files = event.dataTransfer.files;
    if (files && files[0]) {
      handleChosenFile(files[0]);
    }
  });

  // Restore whatever background was saved last session, or tune the scrim
  // vars for the bundled one (should land at ~0 -- it was measured bare).
  if (hasBridge()) {
    window.pywebview.api.get_custom_background().then(function (result) {
      if (result && result.ok && result.dataUrl) {
        applyBackground(result.dataUrl);
      } else {
        applyAdaptiveScrim(DEFAULT_BACKGROUND_URL);
      }
    });
  } else {
    applyAdaptiveScrim(DEFAULT_BACKGROUND_URL);
  }
})();
