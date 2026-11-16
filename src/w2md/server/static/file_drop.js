(function () {
  function fileMatches(file, accept) {
    var rules = String(accept || "").split(",");
    if (!String(accept || "").trim()) { return true; }
    var name = String(file.name || "").toLowerCase();
    var type = String(file.type || "").toLowerCase();
    for (var index = 0; index < rules.length; index += 1) {
      var rule = rules[index].trim().toLowerCase();
      if (!rule) { continue; }
      if (rule.charAt(0) === "." && name.slice(-rule.length) === rule) {
        return true;
      }
      if (rule.slice(-2) === "/*" && type.indexOf(rule.slice(0, -1)) === 0) {
        return true;
      }
      if (rule === type) { return true; }
    }
    return false;
  }

  function assignFiles(input, files) {
    if (!files.length) { return false; }
    try {
      var transfer = new DataTransfer();
      files.forEach(function (file) { transfer.items.add(file); });
      input.files = transfer.files;
      return true;
    } catch (error) {
      return false;
    }
  }

  function initDropTarget(target) {
    if (!target || target.dataset.dropReady === "1") { return; }
    var input = document.getElementById(target.getAttribute("data-drop-input") || "");
    if (!input) { return; }
    target.dataset.dropReady = "1";
    var depth = 0;

    function over(event) {
      event.preventDefault();
      event.stopPropagation();
      target.classList.add("dragover");
    }

    function enter(event) {
      over(event);
      depth += 1;
    }

    function leave(event) {
      event.preventDefault();
      event.stopPropagation();
      depth = Math.max(0, depth - 1);
      if (!depth) { target.classList.remove("dragover"); }
    }

    function drop(event) {
      event.preventDefault();
      event.stopPropagation();
      depth = 0;
      target.classList.remove("dragover");
      var dropped = Array.prototype.slice.call(
        (event.dataTransfer && event.dataTransfer.files) || []
      );
      var accepted = dropped.filter(function (file) {
        return fileMatches(file, input.accept);
      });
      if (!accepted.length) {
        target.classList.add("drop-reject");
        setTimeout(function () { target.classList.remove("drop-reject"); }, 700);
        return;
      }
      if (!input.multiple) { accepted = accepted.slice(0, 1); }
      if (!assignFiles(input, accepted)) {
        target.classList.add("drop-reject");
        setTimeout(function () { target.classList.remove("drop-reject"); }, 700);
        return;
      }
      input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    target.addEventListener("dragenter", enter);
    target.addEventListener("dragover", over);
    target.addEventListener("dragleave", leave);
    target.addEventListener("drop", drop);
  }

  function initAll() {
    var targets = document.querySelectorAll("[data-drop-input]");
    Array.prototype.forEach.call(targets, initDropTarget);
  }

  window.qtInitFileDrops = initAll;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
})();
