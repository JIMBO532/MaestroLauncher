/* MaestroLauncher web frontend -- M8 static shell.
 *
 * Still nothing wired to core/: every control is dead on purpose. The drawn
 * voxel horizon that used to live here is gone -- a real screenshot does that
 * job now, and the drawn one read as an unfinished effect along the bottom
 * rather than as scenery.
 */

(function () {
  "use strict";

  /* --------------------------------------------------------------- shell -- */

  // A launcher is not a web page: dragging images or opening a context menu
  // immediately breaks the illusion of a native window.
  document.addEventListener("dragstart", function (event) {
    event.preventDefault();
  });
  document.addEventListener("contextmenu", function (event) {
    event.preventDefault();
  });

  // Nothing behind the controls yet. Say so in the console rather than
  // letting them look broken.
  var pending = document.querySelectorAll(".play, .version, .account, .rail__item");
  Array.prototype.forEach.call(pending, function (element) {
    element.addEventListener("click", function () {
      console.log(
        "[not wired] " +
          (element.getAttribute("aria-label") || element.textContent.trim()) +
          " is not wired up yet."
      );
    });
  });
})();
