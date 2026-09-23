(function () {
  var dropzone = document.getElementById("dropzone");
  var fileInput = document.getElementById("file-input");
  var dropPanel = document.getElementById("drop-panel");
  var statusPanel = document.getElementById("status-panel");
  var result = document.getElementById("result");
  var statusText = document.getElementById("status-text");
  var reportFile = document.getElementById("report-file");
  var wordPreview = document.getElementById("word-preview");
  var downloadBtn = document.getElementById("download-btn");
  var resetBtn = document.getElementById("reset-btn");

  var current = { filename: "", downloadUrl: null };
  var currentFile = null;

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

  function reset() {
    current = { filename: "", downloadUrl: null };
    currentFile = null;
    wordPreview.innerHTML = "";
    hide(result);
    hide(statusPanel);
    hideError();
    show(dropPanel);
  }

  function convertFile(file) {
    currentFile = file;
    show(statusPanel);
    hide(dropPanel);
    hide(result);
    statusText.textContent = "正在转换 " + file.name + " …";

    fetch("/api/pdf2word/convert?filename=" + encodeURIComponent(file.name), {
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
      current.outputName = res.data.output_name || null;
      reportFile.textContent = res.data.filename;
      QuickPreview.render(res.data.preview_markdown || "", wordPreview);
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
      anchor.download = current.outputName || (current.filename.replace(/\.pdf$/i, "") || "converted") + ".docx";
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
    }
  });

  resetBtn.addEventListener("click", reset);
})();
