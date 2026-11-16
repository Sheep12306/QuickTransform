(function () {
  var dropzone = document.getElementById("dropzone");
  var fileInput = document.getElementById("file-input");
  var dropPanel = document.getElementById("drop-panel");
  var statusPanel = document.getElementById("status-panel");
  var statusText = document.getElementById("status-text");
  var result = document.getElementById("result");
  var resultFile = document.getElementById("result-file");
  var resultSummary = document.getElementById("result-summary");
  var gallery = document.getElementById("gallery");
  var emptyState = document.getElementById("empty-state");
  var selectAll = document.getElementById("select-all");
  var formatFilter = document.getElementById("format-filter");
  var copySelectedBtn = document.getElementById("copy-selected");
  var downloadZipBtn = document.getElementById("download-zip");
  var resetBtn = document.getElementById("reset-btn");
  var manifestLink = document.getElementById("manifest-link");
  var toastEl = document.getElementById("toast");
  var lightbox = document.getElementById("lightbox");
  var lightboxImg = document.getElementById("lightbox-img");
  var lightboxCaption = document.getElementById("lightbox-caption");

  var state = {
    token: "",
    filename: "",
    images: [],
    selected: {},
    blobs: {},
    formatFilter: "",
    toastTimer: null
  };

  var DISPLAYABLE = [
    ".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".gif",
    ".webp", ".avif", ".ico", ".bmp", ".svg"
  ];
  var DISPLAYABLE_TYPES = [
    "image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp",
    "image/avif", "image/x-icon", "image/vnd.microsoft.icon",
    "image/bmp", "image/svg+xml"
  ];
  var MAX_CLIPBOARD_IMAGES = 20;

  function show(el) { el.classList.remove("hidden"); }
  function hide(el) { el.classList.add("hidden"); }

  function toast(message, isError) {
    if (state.toastTimer) { clearTimeout(state.toastTimer); }
    toastEl.textContent = message;
    toastEl.classList.toggle("toast-error", !!isError);
    show(toastEl);
    state.toastTimer = setTimeout(function () { hide(toastEl); }, isError ? 5200 : 3200);
  }

  function formatBytes(size) {
    if (size == null) { return "未知大小"; }
    if (size < 1024) { return size + " B"; }
    if (size < 1024 * 1024) { return (size / 1024).toFixed(1) + " KB"; }
    return (size / (1024 * 1024)).toFixed(2) + " MB";
  }

  function extensionLabel(image) {
    return (image.extension || "").replace(".", "").toUpperCase() || "未知";
  }

  function srcFor(image) {
    return image.preview_url || image.url || "";
  }

  function canDisplay(image) {
    if (image.preview_url) { return true; }
    if (DISPLAYABLE.indexOf((image.extension || "").toLowerCase()) >= 0) {
      return true;
    }
    return DISPLAYABLE_TYPES.indexOf((image.mime_type || "").toLowerCase()) >= 0;
  }

  function formatKey(image) {
    var extension = (image.extension || "").toLowerCase();
    if (extension === ".jpg" || extension === ".jpeg") { return "JPG"; }
    if (extension === ".tif" || extension === ".tiff") { return "TIF"; }
    if (!extension) { return "其他"; }
    return extension.replace(".", "").toUpperCase();
  }

  function visibleEntries() {
    var entries = state.images.map(function (image, index) {
      return { image: image, index: index };
    });
    if (!state.formatFilter) { return entries; }
    return entries.filter(function (entry) {
      return formatKey(entry.image) === state.formatFilter;
    });
  }

  function copyableImages() {
    return visibleEntries().map(function (entry) { return entry.image; }).filter(function (image) {
      return !!image.url && image.status !== "failed";
    });
  }

  function selectedImages() {
    return state.images.filter(function (image, index) {
      return state.selected[index] && !!image.url && image.status !== "failed";
    });
  }

  function openLightbox(src, caption) {
    if (!src) { return; }
    lightboxImg.src = src;
    lightboxImg.alt = caption || "";
    lightboxCaption.textContent = caption || "";
    show(lightbox);
    document.body.classList.add("lightbox-open");
  }

  function closeLightbox() {
    hide(lightbox);
    lightboxImg.removeAttribute("src");
    document.body.classList.remove("lightbox-open");
  }

  function populateFormatFilter() {
    var formats = {};
    state.images.forEach(function (image) { formats[formatKey(image)] = true; });
    var names = Object.keys(formats).sort();

    formatFilter.innerHTML = "";
    var allOption = document.createElement("option");
    allOption.value = "";
    allOption.textContent = "全部格式";
    formatFilter.appendChild(allOption);

    names.forEach(function (name) {
      var option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      formatFilter.appendChild(option);
    });

    state.formatFilter = "";
    formatFilter.value = "";
    formatFilter.disabled = state.images.length === 0;
  }

  function updateSelection() {
    var copyable = copyableImages().length;
    var count = selectedImages().length;
    copySelectedBtn.disabled = count === 0;
    copySelectedBtn.textContent = "复制选中 (" + count + ")";
    copySelectedBtn.title = count > MAX_CLIPBOARD_IMAGES
      ? "浏览器剪贴板建议一次不超过 " + MAX_CLIPBOARD_IMAGES + " 张，请分批复制或使用打包下载"
      : "";
    downloadZipBtn.disabled = copyable === 0;
    selectAll.disabled = copyable === 0;
    selectAll.checked = copyable > 0 && count === copyable;
    selectAll.indeterminate = count > 0 && count < copyable;

    var cards = gallery.querySelectorAll(".image-card");
    for (var i = 0; i < cards.length; i++) {
      var index = Number(cards[i].getAttribute("data-index"));
      var checkbox = cards[i].querySelector(".image-check");
      var isSelected = !!state.selected[index];
      cards[i].classList.toggle("selected", isSelected);
      if (checkbox) { checkbox.checked = isSelected; }
    }
  }

  function renderGallery() {
    gallery.innerHTML = "";
    state.selected = {};
    var entries = visibleEntries();

    if (!entries.length) {
      emptyState.textContent = state.images.length
        ? "当前格式下没有图片。"
        : "没有在正文中检测到图片。";
      emptyState.classList.remove("hidden");
      gallery.classList.add("hidden");
      updateSelection();
      return;
    }

    emptyState.classList.add("hidden");
    gallery.classList.remove("hidden");

    entries.forEach(function (entry) {
      var image = entry.image;
      var index = entry.index;
      var card = document.createElement("article");
      card.className = "image-card";
      card.setAttribute("data-index", String(index));
      if (image.status === "failed") { card.classList.add("failed"); }

      var canDownload = !!image.url && image.status !== "failed";
      var canCopy = canDisplay(image) && canDownload;
      if (canCopy) {
        var selectWrap = document.createElement("div");
        selectWrap.className = "image-select";
        var checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.className = "image-check";
        checkbox.title = "选择这张图片";
        checkbox.addEventListener("change", function () {
          if (checkbox.checked) {
            state.selected[index] = true;
          } else {
            delete state.selected[index];
          }
          updateSelection();
        });
        selectWrap.appendChild(checkbox);
        card.appendChild(selectWrap);
      }

      if (canDisplay(image)) {
        var openButton = document.createElement("button");
        openButton.type = "button";
        openButton.className = "image-open";
        openButton.title = "点击查看大图";
        var frame = document.createElement("div");
        frame.className = "image-frame";
        var img = document.createElement("img");
        img.loading = "lazy";
        img.alt = image.alt_text || ("图片" + image.order);
        img.src = srcFor(image);
        frame.appendChild(img);
        openButton.appendChild(frame);
        openButton.addEventListener("click", function () {
          openLightbox(srcFor(image), image.alt_text || image.filename || "");
        });
        card.appendChild(openButton);
      } else {
        var fallback = document.createElement("div");
        fallback.className = "image-frame";
        var fallbackBox = document.createElement("div");
        fallbackBox.className = "format-fallback";
        var strong = document.createElement("strong");
        strong.textContent = extensionLabel(image);
        var span = document.createElement("span");
        span.textContent = image.status === "failed"
          ? "图片未能提取"
          : "浏览器无法直接预览或复制，原始文件仍可下载";
        fallbackBox.appendChild(strong);
        fallbackBox.appendChild(span);
        fallback.appendChild(fallbackBox);
        card.appendChild(fallback);
      }

      var info = document.createElement("div");
      info.className = "image-info";
      var order = document.createElement("span");
      order.className = "image-order";
      order.textContent = "#" + String(image.order).padStart(6, "0");
      info.appendChild(order);

      var meta = document.createElement("div");
      meta.className = "image-meta";
      var formatBadge = document.createElement("span");
      formatBadge.className = "badge";
      formatBadge.textContent = extensionLabel(image);
      meta.appendChild(formatBadge);
      var sizeBadge = document.createElement("span");
      sizeBadge.className = "badge";
      sizeBadge.textContent = formatBytes(image.size);
      meta.appendChild(sizeBadge);
      if (image.is_duplicate) {
        var duplicateBadge = document.createElement("span");
        duplicateBadge.className = "badge";
        duplicateBadge.textContent = "重复";
        duplicateBadge.title = "与 " + (image.duplicate_of || "前一张") + " 使用同一媒体文件";
        meta.appendChild(duplicateBadge);
      }
      if (image.is_compatibility_format) {
        var compatBadge = document.createElement("span");
        compatBadge.className = "badge badge-warn";
        compatBadge.textContent = "兼容格式";
        meta.appendChild(compatBadge);
      }
      if (image.status === "failed") {
        var failedBadge = document.createElement("span");
        failedBadge.className = "badge badge-error";
        failedBadge.textContent = "失败";
        meta.appendChild(failedBadge);
      }
      info.appendChild(meta);
      card.appendChild(info);

      if (image.error) {
        var errorText = document.createElement("div");
        errorText.className = "image-error";
        errorText.textContent = image.error;
        card.appendChild(errorText);
      }

      if (canDownload) {
        var actions = document.createElement("div");
        actions.className = "image-actions";
        if (canCopy) {
          var copyBtn = document.createElement("button");
          copyBtn.type = "button";
          copyBtn.className = "ghost-btn";
          copyBtn.textContent = "复制";
          if (image.is_compatibility_format) {
            copyBtn.title = "该格式可能需要先转换为 PNG 才能复制；下载可保留原文件";
          }
          copyBtn.addEventListener("click", function () {
            copyImages([image]);
          });
          actions.appendChild(copyBtn);
        }

        var downloadLink = document.createElement("a");
        downloadLink.className = "ghost-btn";
        downloadLink.href = image.url + (image.url.indexOf("?") >= 0 ? "&" : "?") + "download=1";
        downloadLink.download = image.filename || "";
        downloadLink.textContent = "下载";
        downloadLink.addEventListener("click", function (event) {
          event.preventDefault();
          downloadOriginal(image);
        });
        actions.appendChild(downloadLink);
        card.appendChild(actions);
      }

      gallery.appendChild(card);
    });

    updateSelection();
  }

  function downloadOriginal(image) {
    if (!image.url) {
      toast("没有可下载的文件", true);
      return;
    }
    var url = image.url + (image.url.indexOf("?") >= 0 ? "&" : "?") + "download=1";
    var frame = document.createElement("iframe");
    frame.style.display = "none";
    frame.src = url;
    document.body.appendChild(frame);
    setTimeout(function () { frame.remove(); }, 60000);
    toast("已开始下载");
  }

  function downloadZip() {
    var images = selectedImages();
    if (!images.length) {
      toast("请先勾选要打包的图片，或点击「全选」", true);
      return;
    }

    var files = [];
    var seen = {};
    images.forEach(function (image) {
      if (image.filename && !seen[image.filename]) {
        seen[image.filename] = true;
        files.push(image.filename);
      }
    });
    if (!files.length) {
      toast("没有可打包的图片", true);
      return;
    }

    var zipName = (state.filename || "word-images").replace(/\.docx$/i, "") + "-images.zip";
    downloadZipBtn.disabled = true;
    downloadZipBtn.textContent = "正在打包…";
    toast("正在打包 " + files.length + " 张图片，请稍候…");
    fetch("/api/word2image/zip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: state.token, files: files, zip_name: zipName })
    }).then(function (response) {
      return window.qtParseApiResponse(response).then(function (data) {
        if (!response.ok) {
          throw new Error(data.error || "打包失败");
        }
        return data;
      });
    }).then(function (data) {
      if (!data.download_url) {
        throw new Error("服务器没有返回下载地址");
      }
      var frame = document.createElement("iframe");
      frame.style.display = "none";
      frame.src = data.download_url;
      document.body.appendChild(frame);
      setTimeout(function () { frame.remove(); }, 120000);
      toast("已打包 " + (data.count || files.length) + " 张图片，开始下载…");
    }).catch(function (error) {
      toast("打包失败：" + (error.message || error), true);
    }).then(function () {
      downloadZipBtn.textContent = "打包下载";
      updateSelection();
    });
  }

  function copySource(image) {
    return image.preview_url || image.url;
  }

  function loadBlob(image) {
    var source = copySource(image);
    if (state.blobs[source]) { return Promise.resolve(state.blobs[source]); }
    return fetch(source).then(function (response) {
      if (!response.ok) { throw new Error("读取图片失败"); }
      return response.blob();
    }).then(function (blob) {
      state.blobs[source] = blob;
      return blob;
    });
  }

  function prefetchBlobs() {
    state.images.forEach(function (image) {
      if (image.url && image.status !== "failed") {
        loadBlob(image).catch(function () {});
      }
    });
  }

  function canvasToPng(bitmap) {
    var canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    var context = canvas.getContext("2d");
    context.drawImage(bitmap, 0, 0);
    return new Promise(function (resolve, reject) {
      canvas.toBlob(function (blob) {
        if (blob) { resolve(blob); } else { reject(new Error("PNG 转换失败")); }
      }, "image/png");
    });
  }

  function imageElementToBitmap(blob) {
    var url = URL.createObjectURL(blob);
    return new Promise(function (resolve, reject) {
      var image = new Image();
      image.onload = function () { resolve({ image: image, url: url }); };
      image.onerror = function () {
        URL.revokeObjectURL(url);
        reject(new Error("浏览器无法解码该图片格式"));
      };
      image.src = url;
    });
  }

  function toPngBlob(blob) {
    if (blob.type === "image/png") { return Promise.resolve(blob); }

    if (typeof createImageBitmap === "function") {
      return createImageBitmap(blob).then(function (bitmap) {
        return canvasToPng(bitmap).finally(function () {
          if (bitmap.close) { bitmap.close(); }
        });
      }).catch(function () {
        return viaImageElement(blob);
      });
    }
    return viaImageElement(blob);
  }

  function viaImageElement(blob) {
    return imageElementToBitmap(blob).then(function (loaded) {
      var canvas = document.createElement("canvas");
      canvas.width = loaded.image.naturalWidth;
      canvas.height = loaded.image.naturalHeight;
      var context = canvas.getContext("2d");
      context.drawImage(loaded.image, 0, 0);
      URL.revokeObjectURL(loaded.url);
      return new Promise(function (resolve, reject) {
        canvas.toBlob(function (png) {
          if (png) { resolve(png); } else { reject(new Error("PNG 转换失败")); }
        }, "image/png");
      });
    });
  }

  function blobToDataUrl(blob) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () { resolve(reader.result); };
      reader.onerror = function () { reject(new Error("图片读取失败")); };
      reader.readAsDataURL(blob);
    });
  }

  function copyViaHtml(blobs) {
    return Promise.all(blobs.map(blobToDataUrl)).then(function (urls) {
      var html = urls.map(function (url, index) {
        return '<img src="' + url + '" alt="image-' + String(index + 1).padStart(3, "0") + '">';
      }).join("");
      return navigator.clipboard.write([
        new ClipboardItem({
          "text/html": new Blob([html], { type: "text/html" }),
          "text/plain": new Blob(["已复制 " + blobs.length + " 张图片"], { type: "text/plain" })
        })
      ]);
    });
  }

  function copyImages(images) {
    if (!images.length) {
      toast("请先选择要复制的图片", true);
      return;
    }
    if (images.length > MAX_CLIPBOARD_IMAGES) {
      toast(
        "浏览器剪贴板一次最多建议复制 " + MAX_CLIPBOARD_IMAGES +
        " 张图片；当前已选 " + images.length +
        " 张，请分批复制，或使用「打包下载」",
        true
      );
      return;
    }
    if (!navigator.clipboard || typeof ClipboardItem === "undefined") {
      toast("当前浏览器不支持写入图片剪贴板，请使用下载按钮", true);
      return;
    }

    var items = [];
    var htmlBlobs = [];
    var unsupported = [];
    var chain = Promise.resolve();
    images.forEach(function (image) {
      chain = chain.then(function () {
        return loadBlob(image).then(function (sourceBlob) {
          return toPngBlob(sourceBlob).then(function (png) {
            items.push(new ClipboardItem({ "image/png": png }));
            htmlBlobs.push(
              sourceBlob.type && sourceBlob.type.indexOf("image/") === 0 ? sourceBlob : png
            );
          });
        }).catch(function () {
          unsupported.push(image.filename || image.placeholder || "未知图片");
        });
      });
    });

    chain.then(function () {
      if (!items.length) {
        toast("没有可复制的图片，浏览器可能不支持这些格式", true);
        return;
      }
      return navigator.clipboard.write(items).then(function () {
        var message = "已复制 " + items.length + " 张图片";
        if (unsupported.length) { message += "，" + unsupported.length + " 张格式不支持"; }
        toast(message, unsupported.length > 0);
      }).catch(function (error) {
        if (items.length === 1) {
          toast("复制失败：" + (error.message || error), true);
          return;
        }
        return copyViaHtml(htmlBlobs).then(function () {
          var message = "已复制 " + htmlBlobs.length + " 张图片，请粘贴到 ShowDoc";
          if (unsupported.length) { message += "；" + unsupported.length + " 张格式不支持"; }
          toast(message, unsupported.length > 0);
        }).catch(function () {
          return navigator.clipboard.write([items[0]]).then(function () {
            toast("当前浏览器一次只能复制一张，已复制第 1 张；其余请逐张点击「复制」", true);
          }).catch(function (firstError) {
            toast("复制失败：" + (firstError.message || firstError), true);
          });
        });
      });
    });
  }

  function extractFile(file) {
    if (!file) { return; }
    if (!/\.docx$/i.test(file.name)) {
      toast("请选择 .docx 文件", true);
      return;
    }

    hide(dropPanel);
    hide(result);
    show(statusPanel);
    statusText.textContent = "正在上传 " + file.name + " …";

    var xhr = new XMLHttpRequest();
    xhr.open(
      "POST",
      "/api/word2image/extract?filename=" + encodeURIComponent(file.name)
    );
    xhr.upload.onprogress = function (event) {
      if (event.lengthComputable) {
        statusText.textContent = "正在上传 " +
          Math.round(event.loaded / event.total * 100) + "% …";
      }
    };
    xhr.upload.onload = function () {
      statusText.textContent = "上传完成，正在提取图片…";
    };
    xhr.onload = function () {
      hide(statusPanel);
      var data;
      try {
        data = window.qtParseXhrResponse(xhr);
      } catch (error) {
        show(dropPanel);
        toast("提取失败：" + error.message, true);
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        show(dropPanel);
        toast(data.error || "提取失败", true);
        return;
      }

      state.token = data.token || "";
      state.filename = data.filename || file.name;
      state.images = data.images || [];
      state.selected = {};
      state.blobs = {};

      resultFile.textContent = state.filename;
      var summary = data.summary || {};
      var parts = [String(summary.occurrences || 0) + " 张图片"];
      if (summary.unique_media != null) { parts.push(summary.unique_media + " 个唯一文件"); }
      if (summary.duplicates) { parts.push(summary.duplicates + " 张重复"); }
      if (summary.failed) { parts.push(summary.failed + " 张失败"); }
      if (summary.compatibility) { parts.push(summary.compatibility + " 张兼容格式"); }
      resultSummary.textContent = parts.join(" · ");
      manifestLink.href = data.manifest_url || "#";

      populateFormatFilter();
      renderGallery();
      show(result);
      prefetchBlobs();
    };
    xhr.onerror = function () {
      hide(statusPanel);
      show(dropPanel);
      toast("网络错误，上传失败", true);
    };
    xhr.send(file);
  }

  function reset() {
    state.token = "";
    state.filename = "";
    state.images = [];
    state.selected = {};
    state.blobs = {};
    state.formatFilter = "";
    formatFilter.value = "";
    formatFilter.disabled = true;
    gallery.innerHTML = "";
    resultFile.textContent = "";
    resultSummary.textContent = "";
    manifestLink.href = "#";
    hide(result);
    hide(statusPanel);
    show(dropPanel);
  }

  selectAll.addEventListener("change", function () {
    state.selected = {};
    if (selectAll.checked) {
      copyableImages().forEach(function (image) {
        state.selected[state.images.indexOf(image)] = true;
      });
    }
    updateSelection();
  });

  formatFilter.addEventListener("change", function () {
    state.formatFilter = formatFilter.value;
    state.selected = {};
    renderGallery();
  });

  copySelectedBtn.addEventListener("click", function () {
    copyImages(selectedImages());
  });

  downloadZipBtn.addEventListener("click", downloadZip);

  resetBtn.addEventListener("click", reset);
  dropzone.addEventListener("click", function () { fileInput.click(); });
  dropzone.addEventListener("keydown", function (event) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      fileInput.click();
    }
  });
  fileInput.addEventListener("change", function () {
    if (fileInput.files.length) { extractFile(fileInput.files[0]); }
    fileInput.value = "";
  });

  ["dragenter", "dragover"].forEach(function (name) {
    dropzone.addEventListener(name, function (event) {
      event.preventDefault();
      dropzone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach(function (name) {
    dropzone.addEventListener(name, function (event) {
      event.preventDefault();
      dropzone.classList.remove("dragover");
    });
  });
  dropzone.addEventListener("drop", function (event) {
    if (event.dataTransfer.files.length) { extractFile(event.dataTransfer.files[0]); }
  });

  lightbox.addEventListener("click", function (event) {
    if (event.target === lightbox || event.target.id === "lightbox-close") {
      closeLightbox();
    }
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !lightbox.classList.contains("hidden")) {
      closeLightbox();
    }
  });
})();
