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

  // Every control on this screen is wired to core/ now. The "[not wired]"
  // reporter that used to live here has nothing left to report.

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

  // pywebview injects window.pywebview asynchronously, strictly after this
  // script's own top-level code has already run -- it does not exist yet at
  // parse time even in the real app, and only appears once pywebview fires
  // 'pywebviewready'. Code that wants the bridge "on load" has to wait for
  // that event rather than checking hasBridge() immediately, or it always
  // takes the no-bridge path. The timeout is only there to resolve a plain
  // browser preview, where the event never fires at all; 700ms is well past
  // how long the real app takes to fire it, so a real app is never mistaken
  // for a preview.
  var BRIDGE_FALLBACK_MS = 700;

  function onBridgeReady(callback) {
    var settled = false;
    function fire() {
      if (settled) return;
      settled = true;
      callback(hasBridge());
    }
    if (hasBridge()) {
      fire();
      return;
    }
    window.addEventListener("pywebviewready", fire, { once: true });
    setTimeout(fire, BRIDGE_FALLBACK_MS);
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

  // -- the rest of Settings: memory, game folder, keep-open, instance folder

  function readLocal(key, fallback) {
    try {
      var value = window.localStorage.getItem(key);
      return value === null ? fallback : value;
    } catch (e) {
      return fallback;
    }
  }

  function writeLocal(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (e) {
      // Private window, cleared site data, or a browser blocking storage --
      // the setting just will not survive a restart. Not fatal.
    }
  }

  // -- memory --
  //
  // core/launch.py already takes memory_mb; this only has to show and
  // remember the choice; passing it into a real launch is later wiring.

  var ramSlider = document.getElementById("ram-slider");
  var ramValue = document.getElementById("ram-value");

  function formatGb(memoryMb) {
    return (memoryMb / 1024).toFixed(1) + " GB";
  }

  function updateRamSliderFill() {
    var min = Number(ramSlider.min);
    var max = Number(ramSlider.max);
    var value = Number(ramSlider.value);
    var pct = max > min ? ((value - min) / (max - min)) * 100 : 0;
    ramSlider.style.background =
      "linear-gradient(to right, rgba(255,255,255,0.5) " + pct + "%, rgba(255,255,255,0.16) " + pct + "%)";
  }

  function setRamValue(memoryMb) {
    ramSlider.value = String(memoryMb);
    ramValue.textContent = formatGb(memoryMb);
    updateRamSliderFill();
  }

  ramSlider.addEventListener("click", function (event) {
    event.stopPropagation();
  });
  ramSlider.addEventListener("input", function () {
    ramValue.textContent = formatGb(Number(ramSlider.value));
    updateRamSliderFill();
    writeLocal("maestro.memoryMb", ramSlider.value);
  });

  onBridgeReady(function (available) {
    var saved = Number(readLocal("maestro.memoryMb", "")) || null;
    if (!available) {
      setRamValue(saved || 2048);
      return;
    }
    window.pywebview.api.get_launch_settings_bounds().then(function (result) {
      if (result && result.ok) {
        ramSlider.min = String(result.minMemoryMb);
        setRamValue(saved || result.defaultMemoryMb);
      } else {
        setRamValue(saved || 2048);
      }
    });
  });

  // -- game folder --
  //
  // Browse opens a real folder dialog and the choice is remembered, but
  // nothing downstream (the version list, an install) reads it yet -- they
  // still call core.installer.default_directory() themselves.

  var gameFolderPath = document.getElementById("game-folder-path");
  var browseFolderButton = document.getElementById("browse-folder");

  function setGameFolderDisplay(path) {
    gameFolderPath.textContent = path;
    gameFolderPath.title = path;
  }

  onBridgeReady(function (available) {
    var saved = readLocal("maestro.gameFolder", "");
    if (saved) {
      setGameFolderDisplay(saved);
      return;
    }
    if (!available) {
      setGameFolderDisplay("Not available in this preview");
      return;
    }
    window.pywebview.api.get_default_game_folder().then(function (result) {
      if (result && result.ok) setGameFolderDisplay(result.path);
    });
  });

  browseFolderButton.addEventListener("click", function (event) {
    event.stopPropagation();
    if (!hasBridge()) {
      console.log("[not wired] the folder picker needs the app window, not a plain browser preview.");
      return;
    }
    window.pywebview.api.pick_game_folder().then(function (result) {
      if (result && result.ok && result.path) {
        setGameFolderDisplay(result.path);
        writeLocal("maestro.gameFolder", result.path);
        closeSettingsPanel();
      }
    });
  });

  // -- keep launcher open --

  var keepOpenToggle = document.getElementById("keep-open-toggle");

  function setKeepOpen(enabled) {
    keepOpenToggle.setAttribute("aria-checked", enabled ? "true" : "false");
  }

  setKeepOpen(readLocal("maestro.keepOpen", "false") === "true");

  keepOpenToggle.addEventListener("click", function (event) {
    event.stopPropagation();
    setKeepOpen(keepOpenToggle.getAttribute("aria-checked") !== "true");
    writeLocal("maestro.keepOpen", keepOpenToggle.getAttribute("aria-checked"));
  });

  // -- open instance folder --
  //
  // currentSelection is declared further down, in the version + profile
  // section -- still reachable here because this whole file is one closure
  // and this only runs later, in response to a click, by which point the
  // rest of the script has already run once.

  function openInstanceFolder() {
    closeSettingsPanel();
    if (!hasBridge()) {
      console.log("[not wired] opening the instance folder needs the app window.");
      return;
    }
    if (!currentSelection) {
      console.log("[settings] pick a version first.");
      return;
    }
    window.pywebview.api.open_instance_folder(currentSelection.version).then(function (result) {
      if (!result || !result.ok) {
        console.log("[settings] could not open the instance folder: " + (result && result.error));
      }
    });
  }

  settingsToggle.addEventListener("click", function (event) {
    event.stopPropagation();
    closeVersionMenu();
    closeContentPanel();
    closeAboutPanel();
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
    } else if (action === "open-instance-folder") {
      openInstanceFolder();
    }
  });

  document.addEventListener("click", function (event) {
    if (!settingsPanel.hidden && !settingsPanel.contains(event.target) && event.target !== settingsToggle) {
      closeSettingsPanel();
    }
    if (!versionMenu.hidden && !versionMenu.contains(event.target) && event.target !== versionToggle) {
      closeVersionMenu();
    }
    if (!contentPanel.hidden && !contentPanel.contains(event.target) && event.target !== contentToggle) {
      closeContentPanel();
    }
    if (!aboutPanel.hidden && !aboutPanel.contains(event.target) && event.target !== aboutToggle) {
      closeAboutPanel();
    }
    if (!accountPanel.hidden && !accountPanel.contains(event.target) && !accountToggle.contains(event.target)) {
      closeAccountPanel();
    }
  });

  fileInput.addEventListener("change", function () {
    if (fileInput.files && fileInput.files[0]) {
      handleChosenFile(fileInput.files[0]);
    }
    fileInput.value = "";
    closeSettingsPanel();
  });

  /* --------------------------------------------------- version + profile -- */

  // The optimization pack's entry point. No second button beside Play --
  // it is a variant of the version already being chosen here, so choosing
  // it is choosing "1.21.1, but optimized" rather than a competing action.
  //
  // Data comes from core/installer.py through app.py's Api: list_versions()
  // kicks off a fetch on a background thread (a Mojang round trip plus a
  // local disk read) and never blocks this page, the same way
  // BackgroundWorker in gui/app.py keeps that off Tk's one UI thread.
  // Results arrive here, not through that call's return value, via
  // window.__maestro.versions -- evaluate_js's counterpart to posting a
  // callback onto BackgroundWorker's queue.

  var versionToggle = document.getElementById("version-toggle");
  var versionMenu = document.getElementById("version-menu");
  var versionLabel = document.getElementById("version-label");
  var versionSearch = document.getElementById("version-search");
  var versionList = document.getElementById("version-list");
  var versionEmpty = document.getElementById("version-empty");
  var versionGroupTemplate = document.getElementById("version-group-template");

  var VARIANT_LABEL = { fabric: "Fabric", optimized: "Fabric · Optimized" };

  var versionsData = null;     // [{version, fabricInstalled, optimizedInstalled}], null until loaded
  var currentSelection = null; // {version, variant}
  var groupElements = {};      // version -> its rendered .version-menu__group

  function openVersionMenu() {
    versionMenu.hidden = false;
    versionToggle.setAttribute("aria-expanded", "true");
    if (versionsData === null && hasBridge()) {
      window.pywebview.api.list_versions();
    }
  }

  function closeVersionMenu() {
    versionMenu.hidden = true;
    versionToggle.setAttribute("aria-expanded", "false");
  }

  function updateClosedLabel() {
    if (!currentSelection) return;
    var label = currentSelection.version + " " + VARIANT_LABEL[currentSelection.variant];
    versionLabel.textContent = label;
    versionToggle.setAttribute("aria-label", "Choose version. Currently " + label);
    statusInstalled.textContent =
      currentSelection.version +
      " · " +
      (currentSelection.variant === "optimized" ? "Optimized" : "Fabric");
  }

  // The default once data loads: the first version in the list (installed
  // ones sort first) and, within it, whichever variant is already on disk --
  // Fabric over Optimized when both are, since Optimized is the upgrade, not
  // the baseline. Falls back to "Fabric, not yet installed" so the button
  // never reads a version with no variant chosen.
  function defaultSelection(versions) {
    if (!versions.length) return null;
    var first = versions[0];
    var variant = first.fabricInstalled ? "fabric" : first.optimizedInstalled ? "optimized" : "fabric";
    return { version: first.version, variant: variant };
  }

  function setOptionState(optionEl, installed) {
    if (optionEl.getAttribute("data-state") !== "installing") {
      optionEl.setAttribute("data-state", installed ? "installed" : "not-installed");
    }
  }

  function buildGroup(entry) {
    var fragment = versionGroupTemplate.content.cloneNode(true);
    var group = fragment.querySelector(".version-menu__group");
    group.setAttribute("data-version", entry.version);
    group.querySelector(".version-menu__group-label").textContent = entry.version;

    var fabricOpt = group.querySelector('[data-variant="fabric"]');
    var optimizedOpt = group.querySelector('[data-variant="optimized"]');
    setOptionState(fabricOpt, entry.fabricInstalled);
    setOptionState(optimizedOpt, entry.optimizedInstalled);

    return group;
  }

  function renderVersions() {
    versionList.innerHTML = "";
    groupElements = {};

    if (!versionsData || !versionsData.length) return;

    var fragment = document.createDocumentFragment();
    versionsData.forEach(function (entry) {
      var group = buildGroup(entry);
      groupElements[entry.version] = group;
      fragment.appendChild(group);
    });
    versionList.appendChild(fragment);

    if (!currentSelection) {
      currentSelection = defaultSelection(versionsData);
      updateClosedLabel();
    }
    markSelected();
  }

  function markSelected() {
    Object.keys(groupElements).forEach(function (version) {
      var options = groupElements[version].querySelectorAll(".version-menu__option");
      Array.prototype.forEach.call(options, function (option) {
        var isSelected = !!currentSelection
          && currentSelection.version === version
          && currentSelection.variant === option.getAttribute("data-variant");
        option.setAttribute("aria-selected", isSelected ? "true" : "false");
      });
    });
  }

  function selectVariant(version, variant) {
    currentSelection = { version: version, variant: variant };
    updateClosedLabel();
    markSelected();
  }

  function applyFilter() {
    var query = versionSearch.value.trim().toLowerCase();
    var visibleCount = 0;
    Object.keys(groupElements).forEach(function (version) {
      var matches = version.toLowerCase().indexOf(query) !== -1;
      groupElements[version].hidden = !matches;
      if (matches) visibleCount += 1;
    });
    versionEmpty.hidden = visibleCount !== 0;
    versionEmpty.textContent = "No versions match “" + versionSearch.value + "”.";
  }

  function findOption(version, variant) {
    var group = groupElements[version];
    if (!group) return null;
    return group.querySelector('[data-variant="' + variant + '"]');
  }

  function beginInstall(version, variant) {
    var option = findOption(version, variant);
    if (!option || option.getAttribute("data-state") !== "not-installed") return;
    if (!hasBridge()) {
      console.log("[not wired] no pywebview bridge in this preview -- open the app window to install for real.");
      return;
    }
    option.setAttribute("data-state", "installing");
    var progressWrap = option.querySelector(".version-menu__progress");
    var progressFill = option.querySelector(".version-menu__progress-fill");
    progressWrap.hidden = false;
    progressFill.style.transform = "scaleX(0)";
    window.pywebview.api.install_variant(version, variant);
  }

  versionToggle.addEventListener("click", function (event) {
    event.stopPropagation();
    closeSettingsPanel();
    closeContentPanel();
    closeAboutPanel();
    if (versionMenu.hidden) {
      openVersionMenu();
    } else {
      closeVersionMenu();
    }
  });

  versionSearch.addEventListener("click", function (event) {
    event.stopPropagation();
  });
  versionSearch.addEventListener("input", applyFilter);

  versionMenu.addEventListener("click", function (event) {
    var option = event.target.closest(".version-menu__option");
    if (!option) return;
    var group = option.closest(".version-menu__group");
    var version = group.getAttribute("data-version");
    var variant = option.getAttribute("data-variant");
    var state = option.getAttribute("data-state");

    if (state === "installing") return;
    if (state === "not-installed") {
      beginInstall(version, variant);
      return;
    }

    selectVariant(version, variant);
    closeVersionMenu();
  });

  // Handlers app.py's evaluate_js calls into. Kept as a plain object on
  // window, not addEventListener, because this is Python pushing into the
  // page rather than the page's own DOM events.
  window.__maestro = window.__maestro || {};
  window.__maestro.versions = {
    onStatus: function (text) {
      if (versionsData === null) {
        versionEmpty.textContent = text;
      }
    },
    onLoaded: function (payload) {
      versionsData = payload.versions || [];
      renderVersions();
      applyFilter();
      if (payload.warning) {
        console.log("[versions] " + payload.warning);
      }
      if (!versionsData.length) {
        versionEmpty.textContent = "No versions found.";
        versionEmpty.hidden = false;
      }
    },
    onError: function (message) {
      versionEmpty.textContent = "Could not load versions: " + message;
      versionEmpty.hidden = false;
    },
    onInstallProgress: function (payload) {
      var option = findOption(payload.version, payload.variant);
      if (!option) return;
      var fill = option.querySelector(".version-menu__progress-fill");
      if (fill) fill.style.transform = "scaleX(" + (payload.percent / 100) + ")";
    },
    onInstallComplete: function (payload) {
      var option = findOption(payload.version, payload.variant);
      if (!option) return;
      option.setAttribute("data-state", "installed");
      var progressWrap = option.querySelector(".version-menu__progress");
      if (progressWrap) progressWrap.hidden = true;
      if (payload.variant === "optimized") {
        versionsData.forEach(function (entry) {
          if (entry.version === payload.version) entry.optimizedInstalled = true;
        });
      } else {
        versionsData.forEach(function (entry) {
          if (entry.version === payload.version) entry.fabricInstalled = true;
        });
      }
      // This is where Play would launch the freshly installed profile once
      // that wiring lands; for now the row is just selectable like any
      // other installed variant.
      selectVariant(payload.version, payload.variant);
      closeVersionMenu();
    },
    onInstallError: function (payload) {
      var option = findOption(payload.version, payload.variant);
      if (option) {
        option.setAttribute("data-state", "not-installed");
        var progressWrap = option.querySelector(".version-menu__progress");
        if (progressWrap) progressWrap.hidden = true;
      }
      console.log("[versions] install failed for " + payload.version + " (" + payload.variant + "): " + payload.error);
    }
  };

  // Kick off the initial fetch once the bridge exists, same as the
  // background restore below, rather than waiting for the first time
  // someone opens the menu -- the button's own closed label needs the
  // answer too.
  onBridgeReady(function (available) {
    if (available) {
      window.pywebview.api.list_versions();
      // Bring back a saved login without opening a browser. app.py uses
      // auth.refresh() for this, not login_or_refresh(), so a dead token
      // leaves the panel signed out rather than launching a browser nobody
      // asked for.
      window.pywebview.api.restore_account();
    } else {
      versionEmpty.textContent = "Version data requires the app window, not a plain browser preview.";
    }
  });

  // Drag-and-drop onto the home screen. dragover must be prevented on every
  // fire, not just the first, or the browser's default (navigate to the
  // file) wins.
  function carriesFiles(event) {
    var types = event.dataTransfer && event.dataTransfer.types;
    return !!types && Array.prototype.indexOf.call(types, "Files") !== -1;
  }

  // A background-image drop only makes sense on the bare home screen. With
  // any floating panel open -- Content's own dropzone included, which stops
  // its drop from ever reaching here -- swapping the background out from
  // under it would be a non sequitur, so this yields to whichever panel is
  // actually open instead.
  function anyOverlayPanelOpen() {
    return !settingsPanel.hidden || !versionMenu.hidden || !contentPanel.hidden || !aboutPanel.hidden;
  }

  ["dragenter", "dragover"].forEach(function (type) {
    document.addEventListener(type, function (event) {
      if (!carriesFiles(event) || anyOverlayPanelOpen()) return;
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
    if (!carriesFiles(event) || anyOverlayPanelOpen()) return;
    event.preventDefault();
    dropHint.hidden = true;
    var files = event.dataTransfer.files;
    if (files && files[0]) {
      handleChosenFile(files[0]);
    }
  });

  /* ------------------------------------------------- job: status + bar -- */

  // One progress bar and one status line for everything, the way gui/app.py
  // has one shared footer: the version install, the optimization pack, a mod
  // download, an import and a launch all report through here.
  //
  // Three tones, and the difference matters. Work in flight replaces itself.
  // A finished job gets a sentence that then gets out of the way, because a
  // result left up turns the line into a log of the last thing that
  // happened. A failure stays until the next action, because a message that
  // erases itself is one nobody may have read.

  var RESULT_DWELL_MS = 6000;

  var jobBar = document.getElementById("job");
  var jobFill = document.getElementById("job-fill");
  var jobStatus = document.getElementById("job-status");
  var statusInstalled = document.getElementById("status-installed");
  var statusDot = document.getElementById("status-dot");
  var statusAccountText = document.getElementById("status-account-text");

  var statusClearTimer = null;

  // A held message outranks anything merely happening. Without this, the
  // version fetch finishing at startup would blank the line and take an
  // account error with it -- the message arrives from one job and is erased
  // by an unrelated one completing, which is exactly when someone needs to
  // read it. Held messages are replaced only by another held message, or
  // released when the next job actually starts.
  var statusHeld = false;

  function writeStatus(text, tone) {
    if (statusClearTimer !== null) {
      clearTimeout(statusClearTimer);
      statusClearTimer = null;
    }
    jobStatus.textContent = text || "";
    if (tone) {
      jobStatus.setAttribute("data-tone", tone);
    } else {
      jobStatus.removeAttribute("data-tone");
    }
  }

  // Work in flight, and anything else that is fine to lose.
  function setStatus(text, tone) {
    if (statusHeld) return;
    writeStatus(text, tone);
  }

  // Something the person has to see: an error, or a condition blocking play.
  // Stays put until the next job starts or another held message replaces it.
  function holdStatus(text, tone) {
    writeStatus(text, tone);
    statusHeld = true;
  }

  function releaseStatus() {
    statusHeld = false;
  }

  function flashStatus(text) {
    if (statusHeld) return;
    writeStatus(text);
    statusClearTimer = setTimeout(function () {
      statusClearTimer = null;
      jobStatus.textContent = "";
    }, RESULT_DWELL_MS);
  }

  function showProgress(percent) {
    jobBar.hidden = false;
    jobFill.style.transform = "scaleX(" + Math.max(0, Math.min(100, percent)) / 100 + ")";
  }

  function clearProgress() {
    jobBar.hidden = true;
    jobFill.style.transform = "scaleX(0)";
  }

  // Locked inputs while a job runs, so nothing changes under it. Play is the
  // deliberate exception while signed out -- see the click handler.
  function setBusy(busy) {
    var locked = [
      playButton,
      versionToggle,
      accountToggle,
      searchButton,
      searchInput,
      addFilesButton
    ];
    Array.prototype.forEach.call(
      contentPanel.querySelectorAll(".content-panel__type, .content-panel__result-install"),
      function (element) {
        locked.push(element);
      }
    );
    locked.forEach(function (element) {
      if (element) element.disabled = busy;
    });
    contentDropzone.classList.toggle("is-locked", busy);
    if (busy) {
      closeVersionMenu();
      closeAccountPanel();
    }
  }

  /* ----------------------------------------------------------- account -- */

  var accountToggle = document.getElementById("account-toggle");
  var accountPanel = document.getElementById("account-panel");
  var accountLabel = document.getElementById("account-label");
  var accountPanelName = document.getElementById("account-panel-name");
  var signOutButton = document.getElementById("account-sign-out");

  var accountUsername = null;

  function closeAccountPanel() {
    accountPanel.hidden = true;
  }

  function setAccount(username) {
    accountUsername = username || null;
    if (accountUsername) {
      accountToggle.setAttribute("data-signed-in", "true");
      accountToggle.setAttribute("aria-label", "Account: " + accountUsername);
      accountLabel.textContent = accountUsername;
      accountPanelName.textContent = accountUsername;
      statusDot.setAttribute("data-state", "on");
      statusAccountText.textContent = accountUsername;
    } else {
      accountToggle.setAttribute("data-signed-in", "false");
      accountToggle.setAttribute("aria-label", "Sign in to your Microsoft account");
      accountLabel.textContent = "Sign in";
      statusDot.setAttribute("data-state", "off");
      statusAccountText.textContent = "Signed out";
      closeAccountPanel();
    }
  }

  accountToggle.addEventListener("click", function (event) {
    event.stopPropagation();
    closeSettingsPanel();
    closeVersionMenu();
    closeContentPanel();
    closeAboutPanel();

    // Signed out, the button is the sign-in action. Signed in, it opens the
    // one menu that has anywhere to go from here.
    if (!accountUsername) {
      if (!hasBridge()) {
        holdStatus("Signing in needs the app window, not a plain browser preview.", "error");
        return;
      }
      window.pywebview.api.sign_in().then(function (result) {
        if (result && !result.ok && result.error) holdStatus(result.error, "error");
      });
      return;
    }
    accountPanel.hidden = !accountPanel.hidden;
  });

  signOutButton.addEventListener("click", function (event) {
    event.stopPropagation();
    closeAccountPanel();
    if (!hasBridge()) return;
    window.pywebview.api.sign_out().then(function (result) {
      if (result && !result.ok && result.error) holdStatus(result.error, "error");
    });
  });

  /* -------------------------------------------------------------- play -- */

  var playButton = document.getElementById("play-button");

  playButton.addEventListener("click", function () {
    if (!hasBridge()) {
      holdStatus("Launching needs the app window, not a plain browser preview.", "error");
      return;
    }
    if (!currentSelection) {
      holdStatus("Pick a version first.", "error");
      return;
    }
    // Play stays pressable while signed out on purpose, the same as
    // gui/app.py: a button that quietly does nothing teaches nothing,
    // whereas pressing it says what is missing.
    var memoryMb = Number(readLocal("maestro.memoryMb", "")) || 2048;
    window.pywebview.api
      .play(currentSelection.version, currentSelection.variant, memoryMb)
      .then(function (result) {
        if (result && !result.ok && result.error) holdStatus(result.error, "error");
      });
  });

  window.__maestro = window.__maestro || {};

  window.__maestro.job = {
    onBusy: function (busy) {
      // A job starting is the next action, so whatever was being held has
      // been superseded and this job's own reporting takes the line.
      if (busy) releaseStatus();
      setBusy(busy);
      if (!busy) clearProgress();
    },
    onStatus: function (text) {
      setStatus(text);
    },
    onProgress: function (payload) {
      showProgress(payload.percent);
      setStatus(payload.status + " (" + payload.percent + "%)");
    },
    onResult: function (text) {
      clearProgress();
      flashStatus(text);
    },
    onError: function (text) {
      clearProgress();
      holdStatus(text, "error");
    },
    onPlayStarted: function (payload) {
      console.log(
        "[play] " + payload.profile + " running as pid " + payload.pid + ", log: " + payload.logPath
      );
    }
  };

  window.__maestro.account = {
    onRestoring: function (payload) {
      accountLabel.textContent = payload.username + "…";
    },
    onSignedIn: function (payload) {
      setAccount(payload.username);
    },
    onSignedOut: function (payload) {
      setAccount(null);
      if (payload && payload.message) holdStatus(payload.message);
    }
  };

  /* ------------------------------------------------------------- about -- */

  var aboutToggle = document.getElementById("about-toggle");
  var aboutPanel = document.getElementById("about-panel");
  var aboutVersion = document.getElementById("about-version");
  var aboutLoaded = false;

  function openAboutPanel() {
    aboutPanel.hidden = false;
    aboutToggle.setAttribute("aria-expanded", "true");
    if (aboutLoaded) return;
    aboutLoaded = true;
    if (!hasBridge()) {
      aboutVersion.textContent = "Version unavailable in this preview";
      return;
    }
    window.pywebview.api.get_about_info().then(function (result) {
      if (result && result.ok) {
        aboutVersion.textContent = "Version " + result.version;
      }
    });
  }

  function closeAboutPanel() {
    aboutPanel.hidden = true;
    aboutToggle.setAttribute("aria-expanded", "false");
  }

  aboutToggle.addEventListener("click", function (event) {
    event.stopPropagation();
    closeSettingsPanel();
    closeVersionMenu();
    closeContentPanel();
    if (aboutPanel.hidden) {
      openAboutPanel();
    } else {
      closeAboutPanel();
    }
  });

  /* ----------------------------------------------------------- content -- */

  // Ported from gui/app.py's Content tab: search Modrinth, pick a type,
  // install a result, or import local files -- all filtered to the version
  // chosen in the selector above. Search and install are both network calls,
  // so both go through Api.search_content()/install_content(), which run on
  // a background thread in app.py and push results back here, the same
  // fire-and-forget-then-push shape list_versions()/install_variant() use.

  var CONTENT_TYPE_LABELS = { mod: "mods", resourcepack: "resource packs", shader: "shaders" };

  var contentToggle = document.getElementById("content-toggle");
  var contentPanel = document.getElementById("content-panel");
  var typeButtons = contentPanel.querySelectorAll(".content-panel__type");
  var searchInput = document.getElementById("content-search-input");
  var searchButton = document.getElementById("content-search-button");
  var resultsList = document.getElementById("content-results");
  var resultsHint = document.getElementById("content-hint");
  var addFilesButton = document.getElementById("content-add-files");
  var contentFileInput = document.getElementById("content-file-input");
  var contentDropzone = document.getElementById("content-dropzone");
  var resultTemplate = document.getElementById("content-result-template");

  var currentContentType = "mod";

  // How much room the dock and the readout under it need, measured rather
  // than guessed: the bottom group's height depends on what is in it, and a
  // fixed offset went stale the moment the progress bar was added.
  var bottomGroup = document.querySelector(".bottom-group");

  function measureDockClearance() {
    var top = bottomGroup.getBoundingClientRect().top;
    root.style.setProperty("--dock-clearance", Math.round(window.innerHeight - top + 16) + "px");
  }

  window.addEventListener("resize", measureDockClearance);

  function openContentPanel() {
    measureDockClearance();
    contentPanel.hidden = false;
    contentToggle.setAttribute("aria-expanded", "true");
  }

  function closeContentPanel() {
    contentPanel.hidden = true;
    contentToggle.setAttribute("aria-expanded", "false");
  }

  contentToggle.addEventListener("click", function (event) {
    event.stopPropagation();
    closeSettingsPanel();
    closeVersionMenu();
    closeAboutPanel();
    if (contentPanel.hidden) {
      openContentPanel();
    } else {
      closeContentPanel();
    }
  });

  function showHint(text) {
    resultsHint.textContent = text;
    resultsHint.hidden = false;
  }

  function clearResults() {
    var rows = resultsList.querySelectorAll(".content-panel__result");
    Array.prototype.forEach.call(rows, function (row) {
      row.remove();
    });
  }

  Array.prototype.forEach.call(typeButtons, function (button) {
    button.addEventListener("click", function () {
      if (button.getAttribute("aria-selected") === "true") return;
      currentContentType = button.getAttribute("data-type");
      Array.prototype.forEach.call(typeButtons, function (other) {
        other.setAttribute("aria-selected", other === button ? "true" : "false");
      });
      clearResults();
      showHint("Search Modrinth for " + CONTENT_TYPE_LABELS[currentContentType] + ".");
    });
  });

  function findResultRow(project) {
    return resultsList.querySelector('.content-panel__result[data-project="' + project + '"]');
  }

  function doContentSearch() {
    var query = searchInput.value.trim();
    if (!query) return;
    if (!currentSelection) {
      showHint("Pick a version on the home screen first.");
      return;
    }
    if (!hasBridge()) {
      showHint("Search needs the app window, not a plain browser preview.");
      return;
    }
    clearResults();
    showHint('Searching Modrinth for "' + query + '" (' + currentContentType + ", " + currentSelection.version + ")...");
    window.pywebview.api.search_content(query, currentContentType, currentSelection.version);
  }

  searchButton.addEventListener("click", doContentSearch);
  searchInput.addEventListener("keydown", function (event) {
    if (event.key === "Enter") doContentSearch();
  });

  resultsList.addEventListener("click", function (event) {
    var button = event.target.closest(".content-panel__result-install");
    if (!button) return;
    if (button.getAttribute("data-state") !== "not-installed") return;
    if (!currentSelection) {
      showHint("Pick a version on the home screen first.");
      return;
    }
    var row = button.closest(".content-panel__result");
    var project = row.getAttribute("data-project");
    button.setAttribute("data-state", "installing");
    button.textContent = "0%";
    window.pywebview.api.install_content(project, currentContentType, currentSelection.version);
  });

  function chooseContentFiles() {
    if (!currentSelection) {
      showHint("Pick a version on the home screen first.");
      return;
    }
    if (!hasBridge()) {
      console.log("[not wired] importing local files needs the app window, not a plain browser preview.");
      return;
    }
    window.pywebview.api.pick_content_files().then(function (result) {
      if (result && result.ok && result.paths && result.paths.length) {
        window.pywebview.api.import_content_files(result.paths, currentSelection.version);
      }
    });
  }

  addFilesButton.addEventListener("click", chooseContentFiles);

  // No bridge means a plain browser preview, where a <input type=file> only
  // ever hands back a fake path -- there is no way to import for real here,
  // so this exists to fail honestly rather than pretend to work.
  contentFileInput.addEventListener("change", function () {
    console.log("[not wired] importing local files needs the app window, not a plain browser preview.");
    contentFileInput.value = "";
  });

  // Visual feedback only -- the real drop (and the real file paths) are
  // handled on the Python side via window.dom, registered on this same
  // element in app.py's _register_content_dropzone(). See that function's
  // docstring for why a drop needs a different mechanism from everything
  // else on this page.
  contentDropzone.addEventListener("dragenter", function () {
    contentDropzone.classList.add("is-active");
  });
  contentDropzone.addEventListener("dragleave", function () {
    contentDropzone.classList.remove("is-active");
  });
  contentDropzone.addEventListener("drop", function () {
    contentDropzone.classList.remove("is-active");
  });

  window.__maestro = window.__maestro || {};
  window.__maestro.content = {
    onStatus: function (text) {
      showHint(text);
    },
    onResults: function (payload) {
      var results = (payload && payload.results) || [];
      clearResults();
      if (!results.length) {
        showHint("Nothing matched that search.");
        return;
      }
      resultsHint.hidden = true;
      results.forEach(function (hit) {
        var fragment = resultTemplate.content.cloneNode(true);
        var row = fragment.querySelector(".content-panel__result");
        row.setAttribute("data-project", hit.slug || hit.projectId);
        row.querySelector(".content-panel__result-title").textContent = hit.title;
        row.querySelector(".content-panel__result-meta").textContent =
          hit.author + " — " + hit.downloads.toLocaleString() + " downloads";
        resultsList.appendChild(fragment);
      });
    },
    onError: function (message) {
      showHint("Search failed: " + message);
    },
    onInstallProgress: function (payload) {
      var row = findResultRow(payload.project);
      var button = row && row.querySelector(".content-panel__result-install");
      if (button) button.textContent = payload.percent + "%";
    },
    onInstallComplete: function (payload) {
      var row = findResultRow(payload.project);
      var button = row && row.querySelector(".content-panel__result-install");
      if (button) {
        button.setAttribute("data-state", "installed");
        button.textContent = "Installed";
      }
    },
    onInstallError: function (payload) {
      var row = findResultRow(payload.project);
      var button = row && row.querySelector(".content-panel__result-install");
      if (button) {
        button.setAttribute("data-state", "not-installed");
        button.textContent = "Install";
      }
      console.log("[content] install failed: " + payload.error);
    },
    onFilesDropped: function (payload) {
      var paths = (payload && payload.paths) || [];
      if (!paths.length) return;
      if (!currentSelection) {
        console.log("[content] pick a version first.");
        return;
      }
      if (!hasBridge()) return;
      window.pywebview.api.import_content_files(paths, currentSelection.version);
    },
    onImportProgress: function (payload) {
      contentDropzone.textContent = payload.status + " (" + payload.percent + "%)";
    },
    onImportComplete: function (payload) {
      contentDropzone.textContent = "Drop jars and pack zips here";
      console.log("[content] " + payload.summary);
    }
  };

  // Restore whatever background was saved last session, or tune the scrim
  // vars for the bundled one (should land at ~0 -- it was measured bare).
  onBridgeReady(function (available) {
    if (!available) {
      applyAdaptiveScrim(DEFAULT_BACKGROUND_URL);
      return;
    }
    window.pywebview.api.get_custom_background().then(function (result) {
      if (result && result.ok && result.dataUrl) {
        applyBackground(result.dataUrl);
      } else {
        applyAdaptiveScrim(DEFAULT_BACKGROUND_URL);
      }
    });
  });
})();
