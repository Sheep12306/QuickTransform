(function () {
  var dropzone = document.getElementById("dropzone");
  var fileInput = document.getElementById("file-input");
  var dropPanel = document.getElementById("drop-panel");
  var statusPanel = document.getElementById("status-panel");
  var result = document.getElementById("result");
  var statusText = document.getElementById("status-text");
  var reportFile = document.getElementById("report-file");
  var pagesGrid = document.getElementById("pages-grid");
  var downloadBtn = document.getElementById("download-btn");
  var resetBtn = document.getElementById("reset-btn");
  var formatMode = document.getElementById("format-mode");
  var lightbox = document.getElementById("lightbox");
  var lightboxImg = document.getElementById("lightbox-img");
  var lightboxCaption = document.getElementById("lightbox-caption");
  var lightboxClose = document.getElementById("lightbox-close");
  var lightboxDownload = document.getElementById("lightbox-download");

  var current = { filename: "", downloadUrl: null };
  var currentFile = null;
  var formatValue = "png";
  var currentImage = { url: "", name: "" };

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

  function openLightbox(src, alt, name) {
    lightboxImg.src = src;
    lightboxImg.alt = alt || "";
    lightboxCaption.textContent = alt || "";
    currentImage.url = src;
    currentImage.name = name || "image";
    lightbox.classList.remove("hidden");
    document.body.classList.add("lightbox-open");
  }

  function closeLightbox() {
    lightbox.classList.add("hidden");
    document.body.classList.remove("lightbox-open");
  }

  function reset() {
    current = { filename: "", downloadUrl: null };
    currentFile = null;
    pagesGrid.innerHTML = "";
    hide(result);
    hide(statusPanel);
    hideError();
    show(dropPanel);
  }

  function renderPages(images) {
    pagesGrid.innerHTML = "";
    for (var i = 0; i < images.length; i++) {
      (function (image, index) {
        var card = document.createElement("div");
        card.className = "page-card";
        var img = document.createElement("img");
        img.src = image.url;
        img.alt = "第 " + (index + 1) + " 页";
        img.loading = "lazy";
        img.addEventListener("click", function () { openLightbox(image.url, "第 " + (index + 1) + " 页", image.name); });
        var label = document.createElement("span");
        label.textContent = "第 " + (index + 1) + " 页";
        card.appendChild(img);
        card.appendChild(label);
        pagesGrid.appendChild(card);
      })(images[i], i);
    }
  }

  function convertFile(file) {
    currentFile = file;
    show(statusPanel);
    hide(dropPanel);
    hide(result);
    statusText.textContent = "正在转换 " + file.name + " …";

    fetch("/api/pdf2image/convert?filename=" + encodeURIComponent(file.name) + "&format=" + formatValue, {
      method: "POST",
      body: file
    }).then(function (resp) {
      return resp.json().then(function (data) {
        return { ok: resp.ok, data: data };
      });
    }).then(function (res) {
      hide(statusPanel);
      if (!res.ok) {
        showError(res.data.error || "转换失败");
        return;
      }
      current.filename = res.data.filename;
      current.downloadUrl = res.data.download_url || null;
      reportFile.textContent = res.data.filename;
      renderPages(res.data.images || []);
      show(result);
    }).catch(function (err) {
      hide(statusPanel);
      showError(String(err));
    });
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
      hideError();
      convertFile(fileInput.files[0]);
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
      hideError();
      convertFile(files[0]);
    }
  });

  downloadBtn.addEventListener("click", function () {
    if (current.downloadUrl) {
      var anchor = document.createElement("a");
      anchor.href = current.downloadUrl;
      anchor.download = (current.filename.replace(/\.pdf$/i, "") || "pdf-images") + "-images.zip";
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
    }
  });

  resetBtn.addEventListener("click", reset);
  formatMode.addEventListener("click", function (event) {
    var button = event.target.closest("button");
    if (!button) { return; }
    formatValue = button.getAttribute("data-value");
    var buttons = formatMode.querySelectorAll("button");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].classList.toggle("active", buttons[i] === button);
    }
    if (currentFile) { convertFile(currentFile); }
  });

  lightbox.addEventListener("click", closeLightbox);
  lightboxClose.addEventListener("click", closeLightbox);
  lightboxDownload.addEventListener("click", function (event) {
    event.stopPropagation();
    if (!currentImage.url) { return; }
    var anchor = document.createElement("a");
    anchor.href = currentImage.url;
    anchor.download = currentImage.name;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !lightbox.classList.contains("hidden")) {
      closeLightbox();
    }
  });
})();
