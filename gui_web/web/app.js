/* MaestroLauncher web frontend -- M8 slice 1.
 *
 * Deliberately almost empty. Nothing here is wired to core/: this slice exists
 * to judge the look, so every button is dead on purpose. The only behaviour is
 * what makes a dead shell honest to look at and usable from a keyboard.
 */

(function () {
  "use strict";

  // A launcher window is not a web page: dragging the logo or rubber-banding
  // the viewport immediately breaks the illusion of a native app.
  document.addEventListener("dragstart", function (event) {
    event.preventDefault();
  });

  document.addEventListener("contextmenu", function (event) {
    event.preventDefault();
  });

  // Slice 1 has nothing behind the buttons. Rather than have them look broken,
  // say so once in the console so it is obvious this is the shell, not a bug.
  var pending = document.querySelectorAll(".play, .version, .account, .rail__item");
  Array.prototype.forEach.call(pending, function (element) {
    element.addEventListener("click", function () {
      console.log(
        "[slice 1] " +
          (element.getAttribute("aria-label") || element.textContent.trim()) +
          " is not wired up yet."
      );
    });
  });
})();
