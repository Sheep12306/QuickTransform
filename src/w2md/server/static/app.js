(function () {
  var dropzone = document.getElementById("dropzone");
  var fileInput = document.getElementById("file-input");
  var dropPanel = document.getElementById("drop-panel");
  var statusPanel = document.getElementById("status-panel");
  var result = document.getElementById("result");
  var statusText = document.getElementById("status-text");
  var preview = document.getElementById("preview");
  var source = document.getElementById("source");
  var reportFile = document.getElementById("report-file");
  var statLines = document.getElementById("stat-lines");
  var statChars = document.getElementById("stat-chars");
  var statImages = document.getElementById("stat-images");
  var statWarnings = document.getElementById("stat-warnings");
  var warningsList = document.getElementById("warnings");
  var copyBtn = document.getElementById("copy-btn");
  var previewCopyBtn = document.getElementById("preview-copy-btn");
  var sourceCopyBtn = document.getElementById("source-copy-btn");
  var downloadBtn = document.getElementById("download-btn");
  var resetBtn = document.getElementById("reset-btn");
  var styleToggle = document.getElementById("style-toggle");
  var assetMode = document.getElementById("asset-mode");
  var lightbox = document.getElementById("lightbox");
  var lightboxImg = document.getElementById("lightbox-img");
  var lightboxCaption = document.getElementById("lightbox-caption");

  var current = { filename: "", markdown: "", images: [], downloadUrl: null };
  var currentFile = null;
  var assetValue = "folder";
  var syncBlocks = [];

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
    current = { filename: "", markdown: "", images: [], downloadUrl: null };
    currentFile = null;
    source.value = "";
    preview.innerHTML = "";
    syncBlocks = [];
    invalidateBlocks();
    preview.style.height = "";
    source.style.height = "";
    hide(result);
    hide(statusPanel);
    hideError();
    show(dropPanel);
  }

  function openLightbox(src, alt) {
    lightboxImg.src = src;
    lightboxImg.alt = alt || "";
    lightboxCaption.textContent = alt || "";
    lightbox.classList.remove("hidden");
    document.body.classList.add("lightbox-open");
  }

  function closeLightbox() {
    lightbox.classList.add("hidden");
    document.body.classList.remove("lightbox-open");
  }

  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function inlineMd(s) {
    var protectedTokens = [];
    s = s.replace(/<\/?(?:u|mark|strong|em|span|br)(?:\s[^<>]*)?>/g, function (match) {
      protectedTokens.push(match);
      return "@@T" + (protectedTokens.length - 1) + "@@";
    });
    s = s.replace(/\\(.)/g, function (match, ch) {
      protectedTokens.push(ch);
      return "@@T" + (protectedTokens.length - 1) + "@@";
    });
    s = escapeHtml(s);
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
    s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, '<img src="$2" alt="$1">');
    s = s.replace(/@@T(\d+)@@/g, function (match, index) {
      return protectedTokens[Number(index)];
    });
    return s;
  }

  function splitTableRow(line) {
    var s = line.trim();
    if (s.charAt(0) === "|") { s = s.slice(1); }
    if (s.charAt(s.length - 1) === "|") { s = s.slice(0, -1); }
    var cells = [];
    var buffer = "";
    for (var i = 0; i < s.length; i++) {
      var ch = s.charAt(i);
      if (ch === "|" && (i === 0 || s.charAt(i - 1) !== "\\")) {
        cells.push(buffer);
        buffer = "";
      } else {
        buffer += ch;
      }
    }
    cells.push(buffer);
    return cells.map(function (cell) { return cell.trim(); });
  }

  function isTableBlock(lines) {
    return lines.length >= 2 &&
      lines[0].trim().indexOf("|") === 0 &&
      /^\|[\s\-|:]+\|$/.test(lines[1].trim());
  }

  function createTableElement(lines) {
    var table = document.createElement("table");
    var thead = document.createElement("thead");
    var headRow = document.createElement("tr");
    var headCells = splitTableRow(lines[0]);
    for (var i = 0; i < headCells.length; i++) {
      var th = document.createElement("th");
      th.innerHTML = inlineMd(headCells[i]);
      headRow.appendChild(th);
    }
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = document.createElement("tbody");
    for (var r = 2; r < lines.length; r++) {
      if (!lines[r].trim()) { continue; }
      var tr = document.createElement("tr");
      var cells = splitTableRow(lines[r]);
      for (var c = 0; c < cells.length; c++) {
        var td = document.createElement("td");
        td.innerHTML = inlineMd(cells[c]);
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    return table;
  }

  function createBlockElement(block) {
    var lines = block.split("\n");
    if (isTableBlock(lines)) {
      return createTableElement(lines);
    }
    var heading = block.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      var el = document.createElement("h" + heading[1].length);
      el.innerHTML = inlineMd(heading[2]);
      return el;
    }
    if (block === "---") {
      return document.createElement("hr");
    }
    var paragraph = document.createElement("p");
    paragraph.innerHTML = inlineMd(block.replace(/\n/g, " "));
    return paragraph;
  }

  function renderIntoPreview(src) {
    preview.innerHTML = "";
    syncBlocks = [];
    var lines = src.split("\n");
    var i = 0;
    while (i < lines.length) {
      while (i < lines.length && lines[i].trim() === "") { i++; }
      if (i >= lines.length) { break; }
      var start = i;
      var blockLines = [];
      while (i < lines.length && lines[i].trim() !== "") {
        blockLines.push(lines[i]);
        i++;
      }
      var end = i - 1;
      var el = createBlockElement(blockLines.join("\n").trim());
      if (el) {
        preview.appendChild(el);
        syncBlocks.push({ el: el, lineStart: start, lineEnd: end });
      }
    }
    invalidateBlocks();
  }

  function buildPreviewMarkdown(markdown) {
    var result = markdown;
    for (var i = 0; i < current.images.length; i++) {
      result = result
        .split("(" + current.images[i].path + ")")
        .join("(" + current.images[i].url + ")");
    }
    return result;
  }

  function clamp(value, low, high) {
    return Math.max(low, Math.min(value, high));
  }

  var enableSyncScroll = true;
  var lastLeader = null;

  var blockCache = null;

  function invalidateBlocks() {
    blockCache = null;
  }

  function getBlocks() {
    if (blockCache) { return blockCache; }
    var viewTop = preview.getBoundingClientRect().top;
    var scroll = preview.scrollTop;
    var padTop = parseFloat(getComputedStyle(preview).paddingTop) || 0;
    blockCache = [];
    for (var i = 0; i < syncBlocks.length; i++) {
      var rect = syncBlocks[i].el.getBoundingClientRect();
      blockCache.push({
        pTop: rect.top - viewTop + scroll - padTop,
        pBottom: rect.bottom - viewTop + scroll - padTop
      });
    }
    return blockCache;
  }

  var suppressPreview = null;
  var suppressSource = null;
  var pendingPreview = false;
  var pendingSource = false;

  function setSourcePosition(position) {
    suppressSource = position;
    source.scrollTop = clamp(position, 0, source.scrollHeight - source.clientHeight);
  }

  function setPreviewPosition(position) {
    suppressPreview = position;
    preview.scrollTop = clamp(position, 0, preview.scrollHeight - preview.clientHeight);
  }

  function highlightCurrentPreviewBlock() {
    var blocks = getBlocks();
    if (!blocks.length) { return; }
    var position = preview.scrollTop;
    for (var i = 0; i < blocks.length; i++) {
      if (blocks[i].pBottom >= position) {
        var el = syncBlocks[i].el;
        el.classList.remove("sync-flash");
        void el.offsetWidth;
        el.classList.add("sync-flash");
        return;
      }
    }
  }

  function syncFromPreview() {
    var previewMax = preview.scrollHeight - preview.clientHeight;
    var sourceMax = source.scrollHeight - source.clientHeight;
    var fraction = previewMax > 0 ? preview.scrollTop / previewMax : 0;
    setSourcePosition(fraction * sourceMax);
    highlightCurrentPreviewBlock();
  }

  function syncFromSource() {
    var sourceMax = source.scrollHeight - source.clientHeight;
    var previewMax = preview.scrollHeight - preview.clientHeight;
    var fraction = sourceMax > 0 ? source.scrollTop / sourceMax : 0;
    setPreviewPosition(fraction * previewMax);
    highlightCurrentPreviewBlock();
  }

  function onPreviewScroll() {
    if (!enableSyncScroll) { return; }
    if (suppressPreview !== null && Math.abs(preview.scrollTop - suppressPreview) < 1) {
      suppressPreview = null;
      return;
    }
    suppressPreview = null;
    lastLeader = "preview";
    if (pendingPreview) { return; }
    pendingPreview = true;
    requestAnimationFrame(function () {
      pendingPreview = false;
      syncFromPreview();
    });
  }

  function onSourceScroll() {
    if (!enableSyncScroll) { return; }
    if (suppressSource !== null && Math.abs(source.scrollTop - suppressSource) < 1) {
      suppressSource = null;
      return;
    }
    suppressSource = null;
    lastLeader = "source";
    if (pendingSource) { return; }
    pendingSource = true;
    requestAnimationFrame(function () {
      pendingSource = false;
      syncFromSource();
    });
  }

  function fitPanes() {
    var maxHeight = Math.round(window.innerHeight * 0.70);
    preview.style.height = Math.min(preview.scrollHeight, maxHeight) + "px";
    source.style.height = Math.min(source.scrollHeight, maxHeight) + "px";
    invalidateBlocks();
  }

  function fillReport(report) {
    reportFile.textContent = report.source || current.filename;
    var stats = report.stats || {};
    statLines.innerHTML = "行数 <b>" + (stats.lines || 0) + "</b>";
    statChars.innerHTML = "字数 <b>" + (stats.chars || 0) + "</b>";
    statImages.innerHTML = "图片 <b>" + (stats.images || 0) + "</b>";
    var warnings = report.warnings || [];
    statWarnings.innerHTML = "警告 <b>" + warnings.length + "</b>";
    warningsList.innerHTML = "";
    if (warnings.length) {
      for (var i = 0; i < warnings.length; i++) {
        var item = document.createElement("li");
        item.textContent = warnings[i].kind + "：" + warnings[i].detail;
        warningsList.appendChild(item);
      }
      show(warningsList);
    } else {
      hide(warningsList);
    }
  }

  function convertFile(file) {
    currentFile = file;
    show(statusPanel);
    hide(dropPanel);
    hide(result);
    statusText.textContent = "正在转换 " + file.name + " …";

    var styles = styleToggle.checked ? "html" : "drop";
    var assets = assetValue;
    fetch("/api/convert?filename=" + encodeURIComponent(file.name) + "&styles=" + styles + "&assets=" + assets, {
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
      current.markdown = res.data.markdown;
      current.images = res.data.images || [];
      current.downloadUrl = res.data.download_url || null;
      source.value = res.data.markdown;
      renderIntoPreview(buildPreviewMarkdown(source.value));
      fillReport(res.data.report);
      show(result);
      fitPanes();
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

  copyBtn.addEventListener("click", function () {
    navigator.clipboard.writeText(current.markdown).then(function () {
      flash(copyBtn);
    });
  });

  previewCopyBtn.addEventListener("click", function () {
    var html = preview.innerHTML;
    var plain = preview.innerText;
    function done() { flash(previewCopyBtn); }
    function copyPlain() {
      navigator.clipboard.writeText(plain).then(done);
    }
    if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
      try {
        navigator.clipboard.write([
          new ClipboardItem({
            "text/html": new Blob([html], { type: "text/html" }),
            "text/plain": new Blob([plain], { type: "text/plain" })
          })
        ]).then(done, copyPlain);
      } catch (err) {
        copyPlain();
      }
      return;
    }
    copyPlain();
  });

  sourceCopyBtn.addEventListener("click", function () {
    navigator.clipboard.writeText(source.value).then(function () {
      flash(sourceCopyBtn);
    });
  });

  downloadBtn.addEventListener("click", function () {
    if (current.downloadUrl) {
      fetch(current.downloadUrl).then(function (resp) {
        return resp.blob();
      }).then(function (blob) {
        var url = URL.createObjectURL(blob);
        var anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = (current.filename.replace(/\.docx$/i, "") || "document") + ".zip";
        document.body.appendChild(anchor);
        anchor.click();
        document.body.removeChild(anchor);
        URL.revokeObjectURL(url);
      });
      return;
    }
    var base = current.filename.replace(/\.docx$/i, "") || "document";
    var blob = new Blob([current.markdown], { type: "text/markdown;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = base + ".md";
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  });

  resetBtn.addEventListener("click", reset);
  styleToggle.addEventListener("change", function () {
    if (currentFile) { convertFile(currentFile); }
  });
  assetMode.addEventListener("click", function (event) {
    var button = event.target.closest("button");
    if (!button) { return; }
    assetValue = button.getAttribute("data-value");
    var buttons = assetMode.querySelectorAll("button");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].classList.toggle("active", buttons[i] === button);
    }
    if (currentFile) { convertFile(currentFile); }
  });
  preview.addEventListener("dblclick", function (event) {
    var target = event.target;
    if (target && target.tagName === "IMG") {
      openLightbox(target.getAttribute("src"), target.getAttribute("alt") || "");
    }
  });
  lightbox.addEventListener("click", closeLightbox);
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !lightbox.classList.contains("hidden")) {
      closeLightbox();
    }
  });
  preview.addEventListener("scroll", onPreviewScroll);
  source.addEventListener("scroll", onSourceScroll);
  window.addEventListener("resize", onWindowResize);
  preview.addEventListener("load", onImageLoad, true);

  function onImageLoad(event) {
    if (!event.target || event.target.tagName !== "IMG") { return; }
    invalidateBlocks();
    requestAnimationFrame(function () {
      if (lastLeader === "preview") { syncFromPreview(); }
      else if (lastLeader === "source") { syncFromSource(); }
    });
  }

  function onWindowResize() {
    fitPanes();
    invalidateBlocks();
    requestAnimationFrame(function () {
      if (lastLeader === "preview") { syncFromPreview(); }
      else if (lastLeader === "source") { syncFromSource(); }
    });
  }

  function flash(btn) {
    var original = btn.style.background;
    btn.style.background = "var(--accent)";
    btn.style.color = "#ffffff";
    setTimeout(function () {
      btn.style.background = original;
      btn.style.color = "";
    }, 600);
  }
})();
