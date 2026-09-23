(function () {
  var dropzone = document.getElementById("dropzone");
  var fileInput = document.getElementById("file-input");
  var dropPanel = document.getElementById("drop-panel");
  var result = document.getElementById("result");
  var reportFile = document.getElementById("report-file");
  var preview = document.getElementById("preview");
  var source = document.getElementById("source");
  var copyBtn = document.getElementById("copy-btn");
  var sourceCopyBtn = document.getElementById("source-copy-btn");
  var resetBtn = document.getElementById("reset-btn");
  var fullscreenBtn = document.getElementById("fullscreen-btn");
  var themeMode = document.getElementById("theme-mode");
  var accentMode = document.getElementById("accent-mode");

  var current = { filename: "", markdown: "" };

  function show(el) { el.classList.remove("hidden"); }
  function hide(el) { el.classList.add("hidden"); }

  function hideError() {
    var banner = document.getElementById("error-banner");
    if (banner) { hide(banner); }
  }

  function showError(message) {
    var banner = document.getElementById("error-banner");
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "error-banner";
      banner.className = "error-banner";
      document.querySelector(".layout").insertBefore(banner, dropPanel);
    }
    banner.textContent = message;
    show(banner);
    show(dropPanel);
  }

  function placeholdLocalImages(markdown) {
    return markdown.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, function (match, alt, url) {
      if (/^(https?:|data:|blob:)/i.test(url)) {
        return match;
      }
      var label = alt || "图片";
      return "**图片占位：" + label + "**";
    });
  }

  function renderFile(text) {
    source.value = text;
    preview.innerHTML = "";
    QuickPreview.render(placeholdLocalImages(text), preview);
  }

  function fitPanes() {
    var maxHeight = Math.round(window.innerHeight * 0.70);
    preview.style.height = Math.min(preview.scrollHeight, maxHeight) + "px";
    source.style.height = Math.min(source.scrollHeight, maxHeight) + "px";
  }

  var suppressPreview = null;
  var suppressSource = null;
  var pendingPreview = false;
  var pendingSource = false;

  function clamp(value, low, high) {
    return Math.max(low, Math.min(value, high));
  }

  function setSourcePosition(position) {
    suppressSource = position;
    source.scrollTop = clamp(position, 0, source.scrollHeight - source.clientHeight);
  }

  function setPreviewPosition(position) {
    suppressPreview = position;
    preview.scrollTop = clamp(position, 0, preview.scrollHeight - preview.clientHeight);
  }

  function syncFromPreview() {
    var previewMax = preview.scrollHeight - preview.clientHeight;
    var sourceMax = source.scrollHeight - source.clientHeight;
    var fraction = previewMax > 0 ? preview.scrollTop / previewMax : 0;
    setSourcePosition(fraction * sourceMax);
  }

  function syncFromSource() {
    var sourceMax = source.scrollHeight - source.clientHeight;
    var previewMax = preview.scrollHeight - preview.clientHeight;
    var fraction = sourceMax > 0 ? source.scrollTop / sourceMax : 0;
    setPreviewPosition(fraction * previewMax);
  }

  function onPreviewScroll() {
    if (suppressPreview !== null && Math.abs(preview.scrollTop - suppressPreview) < 1) {
      suppressPreview = null;
      return;
    }
    suppressPreview = null;
    if (pendingPreview) { return; }
    pendingPreview = true;
    requestAnimationFrame(function () {
      pendingPreview = false;
      syncFromPreview();
    });
  }

  function onSourceScroll() {
    if (suppressSource !== null && Math.abs(source.scrollTop - suppressSource) < 1) {
      suppressSource = null;
      return;
    }
    suppressSource = null;
    if (pendingSource) { return; }
    pendingSource = true;
    requestAnimationFrame(function () {
      pendingSource = false;
      syncFromSource();
    });
  }

  function readFile(file) {
    hideError();
    hide(dropPanel);
    hide(result);
    var reader = new FileReader();
    reader.onload = function () {
      current.filename = file.name;
      current.markdown = String(reader.result || "").replace(/^\uFEFF/, "");
      reportFile.textContent = file.name;
      renderFile(current.markdown);
      show(result);
      fitPanes();
    };
    reader.onerror = function () {
      showError("读取文件失败，请确认文件编码为 UTF-8");
    };
    reader.readAsText(file, "UTF-8");
  }

  function reset() {
    current = { filename: "", markdown: "" };
    source.value = "";
    preview.innerHTML = "";
    preview.style.height = "";
    source.style.height = "";
    document.body.classList.remove("reader-fullscreen");
    fullscreenBtn.textContent = "全屏阅读";
    hide(result);
    hideError();
    show(dropPanel);
  }

  dropzone.addEventListener("click", function () { fileInput.click(); });
  dropzone.addEventListener("keydown", function (event) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInput.click();
    }
  });

  fileInput.addEventListener("change", function () {
    if (fileInput.files.length) {
      readFile(fileInput.files[0]);
    }
    fileInput.value = "";
  });

  ["dragenter", "dragover"].forEach(function (type) {
    dropzone.addEventListener(type, function (event) {
      event.preventDefault();
      dropzone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach(function (type) {
    dropzone.addEventListener(type, function (event) {
      event.preventDefault();
      dropzone.classList.remove("dragover");
    });
  });
  dropzone.addEventListener("drop", function (event) {
    var files = event.dataTransfer.files;
    if (files.length) {
      readFile(files[0]);
    }
  });

  copyBtn.addEventListener("click", function () {
    navigator.clipboard.writeText(current.markdown).then(function () {
      var original = copyBtn.style.background;
      copyBtn.style.background = "var(--accent)";
      copyBtn.style.color = "#ffffff";
      setTimeout(function () {
        copyBtn.style.background = original;
        copyBtn.style.color = "";
      }, 600);
    });
  });

  sourceCopyBtn.addEventListener("click", function () {
    navigator.clipboard.writeText(source.value).then(function () {
      var original = sourceCopyBtn.style.background;
      sourceCopyBtn.style.background = "var(--accent)";
      sourceCopyBtn.style.color = "#ffffff";
      setTimeout(function () {
        sourceCopyBtn.style.background = original;
        sourceCopyBtn.style.color = "";
      }, 600);
    });
  });

  source.addEventListener("input", function () {
    current.markdown = source.value;
    preview.innerHTML = "";
    QuickPreview.render(placeholdLocalImages(source.value), preview);
    fitPanes();
  });

  resetBtn.addEventListener("click", reset);
  fullscreenBtn.addEventListener("click", function () {
    var active = document.body.classList.toggle("reader-fullscreen");
    fullscreenBtn.textContent = active ? "退出全屏" : "全屏阅读";
    requestAnimationFrame(fitPanes);
  });

  themeMode.addEventListener("click", function (event) {
    var button = event.target.closest("button");
    if (!button) { return; }
    document.body.setAttribute("data-theme", button.getAttribute("data-value"));
    var buttons = themeMode.querySelectorAll("button");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].classList.toggle("active", buttons[i] === button);
    }
  });

  accentMode.addEventListener("click", function (event) {
    var button = event.target.closest("button");
    if (!button) { return; }
    document.body.setAttribute("data-accent", button.getAttribute("data-value"));
    var buttons = accentMode.querySelectorAll("button");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].classList.toggle("active", buttons[i] === button);
    }
  });

  preview.addEventListener("scroll", onPreviewScroll);
  source.addEventListener("scroll", onSourceScroll);
  window.addEventListener("resize", function () {
    fitPanes();
    requestAnimationFrame(function () {
      if (preview.scrollTop > 0) { syncFromPreview(); }
    });
  });
})();
