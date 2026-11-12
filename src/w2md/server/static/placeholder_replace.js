(function () {
  var markdownFile = document.getElementById("markdown-file");
  var showdocFile = document.getElementById("showdoc-file");
  var manifestFile = document.getElementById("manifest-file");
  var imageFiles = document.getElementById("image-files");
  var markdownText = document.getElementById("markdown-text");
  var showdocText = document.getElementById("showdoc-text");
  var markdownName = document.getElementById("markdown-name");
  var showdocName = document.getElementById("showdoc-name");
  var manifestName = document.getElementById("manifest-name");
  var imageCount = document.getElementById("image-count");
  var analyzeBtn = document.getElementById("analyze-btn");
  var clearBtn = document.getElementById("clear-btn");
  var generateBtn = document.getElementById("generate-btn");
  var analysisPanel = document.getElementById("analysis-panel");
  var mappingPanel = document.getElementById("mapping-panel");
  var mappingBody = document.getElementById("mapping-body");
  var resultPanel = document.getElementById("result-panel");
  var resultText = document.getElementById("result-text");
  var resultNote = document.getElementById("result-note");
  var copyResult = document.getElementById("copy-result");
  var downloadMd = document.getElementById("download-md");
  var downloadManifest = document.getElementById("download-manifest");
  var downloadReport = document.getElementById("download-report");
  var toastEl = document.getElementById("toast");

  var state = {
    markdownFilename: "",
    showdocFilename: "",
    manifest: null,
    manifestFilename: "",
    imageUrls: {},
    analysis: null,
    mapping: {},
    mappingDirty: false,
    generateResult: null,
    analyzeTimer: null,
    toastTimer: null
  };

  function show(el) { el.classList.remove("hidden"); }
  function hide(el) { el.classList.add("hidden"); }

  function toast(message, isError) {
    if (state.toastTimer) { clearTimeout(state.toastTimer); }
    toastEl.textContent = message;
    toastEl.classList.toggle("toast-error", !!isError);
    show(toastEl);
    state.toastTimer = setTimeout(function () { hide(toastEl); }, isError ? 5200 : 3200);
  }

  function readTextFile(file, callback) {
    var reader = new FileReader();
    reader.onload = function () { callback(String(reader.result || "")); };
    reader.readAsText(file, "utf-8");
  }

  function resetAnalysis() {
    state.analysis = null;
    state.mapping = {};
    state.mappingDirty = false;
    state.generateResult = null;
    generateBtn.disabled = true;
    hide(analysisPanel);
    hide(mappingPanel);
    hide(resultPanel);
  }

  function payload(includeMapping) {
    return {
      markdown: markdownText.value,
      showdoc_markdown: showdocText.value,
      manifest: state.manifest,
      mapping: includeMapping ? mappingList() : null
    };
  }

  function mappingList() {
    var result = [];
    Object.keys(state.mapping).forEach(function (token) {
      var url = state.mapping[token];
      if (url) {
        result.push({ placeholder: token, url: url });
      }
    });
    return result;
  }

  function postJson(url, data) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    }).then(function (response) {
      return response.json().then(function (body) {
        return { ok: response.ok, data: body };
      });
    });
  }

  function analyze() {
    if (!markdownText.value.trim()) {
      toast("请先填写带占位符的 Markdown", true);
      return;
    }
    if (!showdocText.value.trim()) {
      toast("请先填写 ShowDoc Markdown 源码", true);
      return;
    }

    analyzeBtn.disabled = true;
    analyzeBtn.textContent = "正在校验…";
    postJson("/api/placeholder-replace/analyze", payload(state.mappingDirty))
      .then(function (result) {
        if (!result.ok) {
          throw new Error((result.data && result.data.error) || "校验失败");
        }
        state.analysis = result.data;
        state.mapping = {};
        (result.data.mapping || []).forEach(function (item) {
          if (item.url) { state.mapping[item.placeholder] = item.url; }
        });
        state.generateResult = null;
        hide(resultPanel);
        renderAnalysis();
        if (state.mappingDirty) {
          // The response mapping reflects the explicit mapping we sent.
          state.mappingDirty = true;
        }
      })
      .catch(function (error) {
        toast("校验失败：" + (error.message || error), true);
      })
      .then(function () {
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = "校验并生成映射";
      });
  }

  function scheduleAnalyze() {
    if (state.analyzeTimer) { clearTimeout(state.analyzeTimer); }
    state.analyzeTimer = setTimeout(function () {
      state.analyzeTimer = null;
      analyze();
    }, 350);
  }

  function renderAnalysis() {
    var analysis = state.analysis;
    if (!analysis) { return; }
    var counts = analysis.counts || {};
    document.getElementById("count-placeholders").textContent = counts.placeholders || 0;
    document.getElementById("count-occurrences").textContent = counts.placeholder_occurrences || 0;
    document.getElementById("count-urls").textContent = counts.urls || 0;
    document.getElementById("count-manifest").textContent = counts.manifest_images || 0;
    document.getElementById("count-matched").textContent = counts.matched || 0;
    document.getElementById("count-missing").textContent = counts.missing || 0;
    document.getElementById("count-invalid").textContent = counts.invalid || 0;
    document.getElementById("count-code").textContent = counts.code_block_placeholders || 0;

    renderMessages("error-list", analysis.errors || []);
    renderMessages("warning-list", analysis.warnings || []);

    renderMapping(analysis);
    show(analysisPanel);
    show(mappingPanel);
    generateBtn.disabled = !analysis.can_generate;
  }

  function renderMessages(id, messages) {
    var list = document.getElementById(id);
    list.innerHTML = "";
    if (!messages.length) {
      hide(list);
      return;
    }
    messages.forEach(function (message) {
      var item = document.createElement("li");
      item.textContent = message;
      list.appendChild(item);
    });
    show(list);
  }

  function renderMapping(analysis) {
    mappingBody.innerHTML = "";
    var items = analysis.mapping || [];
    if (!items.length) {
      var emptyRow = document.createElement("tr");
      var emptyCell = document.createElement("td");
      emptyCell.colSpan = 6;
      emptyCell.textContent = "没有可替换的占位符";
      emptyRow.appendChild(emptyCell);
      mappingBody.appendChild(emptyRow);
      return;
    }

    var urls = analysis.urls || [];
    items.forEach(function (item) {
      var row = document.createElement("tr");
      row.setAttribute("data-placeholder", item.placeholder);

      var orderCell = document.createElement("td");
      orderCell.textContent = "#" + String(item.order).padStart(6, "0");
      row.appendChild(orderCell);

      var tokenCell = document.createElement("td");
      var token = document.createElement("span");
      token.className = "placeholder-code";
      token.textContent = item.placeholder;
      tokenCell.appendChild(token);
      row.appendChild(tokenCell);

      var thumbCell = document.createElement("td");
      var localUrl = item.filename ? state.imageUrls[item.filename] : null;
      if (localUrl) {
        var img = document.createElement("img");
        img.className = "mapping-thumb";
        img.src = localUrl;
        img.alt = item.alt_text || "";
        thumbCell.appendChild(img);
      } else {
        var empty = document.createElement("div");
        empty.className = "mapping-thumb-empty";
        empty.textContent = "无缩略图";
        thumbCell.appendChild(empty);
      }
      row.appendChild(thumbCell);

      var altCell = document.createElement("td");
      altCell.className = "mapping-alt";
      var alt = document.createElement("strong");
      alt.textContent = item.alt_text || "图片";
      var fileName = document.createElement("span");
      fileName.textContent = item.filename || "未提供 manifest";
      altCell.appendChild(alt);
      altCell.appendChild(fileName);
      row.appendChild(altCell);

      var urlCell = document.createElement("td");
      var select = document.createElement("select");
      select.className = "url-select";
      var none = document.createElement("option");
      none.value = "";
      none.textContent = "— 未分配 —";
      select.appendChild(none);

      var known = {};
      urls.forEach(function (urlItem) {
        known[urlItem.url] = true;
        var option = document.createElement("option");
        option.value = urlItem.url;
        option.textContent = "#" + urlItem.index + " " + shorten(urlItem.url) +
          (urlItem.valid ? "" : "（非法）");
        select.appendChild(option);
      });
      if (item.url && !known[item.url]) {
        var custom = document.createElement("option");
        custom.value = item.url;
        custom.textContent = shorten(item.url) + "（自定义）";
        select.appendChild(custom);
      }
      select.value = item.url || "";
      select.addEventListener("change", function () {
        if (select.value) {
          state.mapping[item.placeholder] = select.value;
        } else {
          delete state.mapping[item.placeholder];
        }
        state.mappingDirty = true;
        scheduleAnalyze();
      });
      urlCell.appendChild(select);
      row.appendChild(urlCell);

      var statusCell = document.createElement("td");
      var badge = document.createElement("span");
      badge.className = "status-badge " + statusClass(item.status);
      badge.textContent = statusLabel(item.status);
      statusCell.appendChild(badge);
      row.appendChild(statusCell);

      mappingBody.appendChild(row);
    });
  }

  function shorten(url) {
    if (!url) { return ""; }
    return url.length > 96 ? url.slice(0, 93) + "…" : url;
  }

  function statusClass(status) {
    if (status === "matched") { return "matched"; }
    if (status === "invalid_url") { return "invalid"; }
    return "missing";
  }

  function statusLabel(status) {
    if (status === "matched") { return "已匹配"; }
    if (status === "invalid_url") { return "URL 非法"; }
    if (status === "missing_url") { return "缺少 URL"; }
    return status || "未知";
  }

  function generate() {
    if (!state.analysis || !state.analysis.can_generate) {
      toast("请先通过校验", true);
      return;
    }
    generateBtn.disabled = true;
    generateBtn.textContent = "正在生成…";
    postJson("/api/placeholder-replace/generate", payload(true))
      .then(function (result) {
        if (!result.ok) {
          var data = result.data || {};
          state.analysis = data.analysis || state.analysis;
          renderAnalysis();
          throw new Error(data.error || "生成失败");
        }
        state.analysis = result.data.analysis || state.analysis;
        state.generateResult = result.data;
        state.mapping = {};
        (state.analysis.mapping || []).forEach(function (item) {
          if (item.url) { state.mapping[item.placeholder] = item.url; }
        });
        state.mappingDirty = true;
        renderAnalysis();
        showResult(result.data);
      })
      .catch(function (error) {
        toast("生成失败：" + (error.message || error), true);
      })
      .then(function () {
        generateBtn.disabled = !(state.analysis && state.analysis.can_generate);
        generateBtn.textContent = "生成最终 Markdown";
      });
  }

  function showResult(data) {
    resultText.value = data.markdown || "";
    var notes = [];
    notes.push("已替换 " + (data.replaced_count || 0) + " 个占位符");
    if (data.skipped_code_count) {
      notes.push("代码块中跳过 " + data.skipped_code_count + " 个");
    }
    if ((data.warnings || []).length) {
      notes.push(data.warnings.join("；"));
    }
    resultNote.textContent = notes.join("；");
    downloadManifest.disabled = !data.updated_manifest;
    show(resultPanel);
    resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function baseName() {
    var name = state.markdownFilename || "document";
    return name.replace(/\.(md|markdown)$/i, "") || "document";
  }

  function downloadText(filename, text, mime) {
    var blob = new Blob([text], { type: mime || "text/plain;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function clearAll() {
    markdownFile.value = "";
    showdocFile.value = "";
    manifestFile.value = "";
    imageFiles.value = "";
    markdownText.value = "";
    showdocText.value = "";
    markdownName.textContent = "";
    showdocName.textContent = "";
    manifestName.textContent = "未上传 manifest（缩略图、alt 文本和 manifest 更新不可用）";
    imageCount.textContent = "未上传图片";
    state.markdownFilename = "";
    state.showdocFilename = "";
    state.manifest = null;
    state.manifestFilename = "";
    Object.keys(state.imageUrls).forEach(function (name) {
      URL.revokeObjectURL(state.imageUrls[name]);
    });
    state.imageUrls = {};
    state.generateResult = null;
    resetAnalysis();
  }

  markdownFile.addEventListener("change", function () {
    if (!markdownFile.files.length) { return; }
    var file = markdownFile.files[0];
    state.markdownFilename = file.name;
    markdownName.textContent = "已加载：" + file.name;
    readTextFile(file, function (text) {
      markdownText.value = text;
      resetAnalysis();
    });
  });

  showdocFile.addEventListener("change", function () {
    if (!showdocFile.files.length) { return; }
    var file = showdocFile.files[0];
    state.showdocFilename = file.name;
    showdocName.textContent = "已加载：" + file.name;
    readTextFile(file, function (text) {
      showdocText.value = text;
      resetAnalysis();
    });
  });

  manifestFile.addEventListener("change", function () {
    if (!manifestFile.files.length) { return; }
    var file = manifestFile.files[0];
    readTextFile(file, function (text) {
      try {
        state.manifest = JSON.parse(text);
        state.manifestFilename = file.name;
        var count = (state.manifest.images || []).length;
        manifestName.textContent = "已加载：" + file.name + "（" + count + " 张图片）";
        resetAnalysis();
      } catch (error) {
        state.manifest = null;
        manifestName.textContent = "manifest 解析失败";
        toast("manifest.json 解析失败", true);
      }
    });
  });

  imageFiles.addEventListener("change", function () {
    Object.keys(state.imageUrls).forEach(function (name) {
      URL.revokeObjectURL(state.imageUrls[name]);
    });
    state.imageUrls = {};
    var files = Array.from(imageFiles.files || []);
    files.forEach(function (file) {
      state.imageUrls[file.name] = URL.createObjectURL(file);
    });
    imageCount.textContent = files.length
      ? "已加载 " + files.length + " 张图片"
      : "未上传图片";
    if (state.analysis) { renderMapping(state.analysis); }
  });

  markdownText.addEventListener("input", resetAnalysis);
  showdocText.addEventListener("input", resetAnalysis);

  analyzeBtn.addEventListener("click", analyze);
  generateBtn.addEventListener("click", generate);
  clearBtn.addEventListener("click", clearAll);

  copyResult.addEventListener("click", function () {
    if (!resultText.value) { return; }
    navigator.clipboard.writeText(resultText.value).then(function () {
      toast("已复制最终 Markdown");
    }).catch(function (error) {
      toast("复制失败：" + (error.message || error), true);
    });
  });

  downloadMd.addEventListener("click", function () {
    if (!resultText.value) { return; }
    downloadText(baseName() + ".replaced.md", resultText.value, "text/markdown;charset=utf-8");
  });

  downloadManifest.addEventListener("click", function () {
    if (!state.generateResult || !state.generateResult.updated_manifest) {
      toast("没有可下载的 manifest", true);
      return;
    }
    downloadText(
      baseName() + ".manifest.replaced.json",
      JSON.stringify(state.generateResult.updated_manifest, null, 2),
      "application/json;charset=utf-8"
    );
  });

  downloadReport.addEventListener("click", function () {
    if (!state.generateResult) {
      toast("请先生成最终 Markdown", true);
      return;
    }
    var report = {
      analysis: state.analysis,
      replacement: {
        replaced_count: state.generateResult.replaced_count,
        skipped_code_count: state.generateResult.skipped_code_count,
        warnings: state.generateResult.warnings || []
      }
    };
    downloadText(
      baseName() + ".replace.report.json",
      JSON.stringify(report, null, 2),
      "application/json;charset=utf-8"
    );
  });
})();
