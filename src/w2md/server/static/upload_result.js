(function () {
  var markdownFile = document.getElementById("markdown-file");
  var uploadFile = document.getElementById("upload-file");
  var manifestFile = document.getElementById("manifest-file");
  var imageFiles = document.getElementById("image-files");
  var markdownText = document.getElementById("markdown-text");
  var markdownName = document.getElementById("markdown-name");
  var uploadName = document.getElementById("upload-name");
  var uploadSummaryList = document.getElementById("upload-summary-list");
  var manifestName = document.getElementById("manifest-name");
  var imageCount = document.getElementById("image-count");
  var analyzeBtn = document.getElementById("analyze-btn");
  var generateBtn = document.getElementById("generate-btn");
  var exportCsv = document.getElementById("export-csv");
  var clearBtn = document.getElementById("clear-btn");
  var allowMismatch = document.getElementById("allow-mismatch");
  var analysisPanel = document.getElementById("analysis-panel");
  var mappingPanel = document.getElementById("mapping-panel");
  var mappingBody = document.getElementById("mapping-body");
  var mappingSummary = document.getElementById("mapping-summary");
  var resultPanel = document.getElementById("result-panel");
  var resultText = document.getElementById("result-text");
  var resultNote = document.getElementById("result-note");
  var consistency = document.getElementById("consistency");
  var copyResult = document.getElementById("copy-result");
  var downloadMd = document.getElementById("download-md");
  var downloadCsv = document.getElementById("download-csv");
  var downloadReport = document.getElementById("download-report");
  var downloadHtml = document.getElementById("download-html");
  var toastEl = document.getElementById("toast");

  var MAX_THUMBNAILS = 120;
  var CSV_COLUMNS = [
    "序号", "occurrence_id", "占位符", "原始文件名", "原始路径",
    "上传文件名", "上传路径", "大小", "SHA-256", "原始SHA-256",
    "上传SHA-256", "章节", "上下文前置文字", "上下文后置文字",
    "状态", "失败原因", "是否在Markdown中", "行号"
  ];

  var state = {
    markdownFilename: "",
    uploadFilename: "",
    manifestFilename: "",
    uploadResult: null,
    manifest: null,
    analysis: null,
    result: null,
    imageUrls: {},
    filesByName: {},
    toastTimer: null
  };

  function show(el) { el.classList.remove("hidden"); }
  function hide(el) { el.classList.add("hidden"); }

  function toast(message, isError) {
    if (state.toastTimer) { clearTimeout(state.toastTimer); }
    toastEl.textContent = message;
    toastEl.classList.toggle("toast-error", !!isError);
    show(toastEl);
    state.toastTimer = setTimeout(function () { hide(toastEl); }, isError ? 5600 : 3400);
  }

  function readTextFile(file, callback) {
    var reader = new FileReader();
    reader.onload = function () { callback(String(reader.result || "")); };
    reader.readAsText(file, "utf-8");
  }

  function currentMode() {
    var selected = document.querySelector('input[name="mode"]:checked');
    return selected ? selected.value : "partial";
  }

  function resetAnalysis() {
    state.analysis = null;
    state.result = null;
    generateBtn.disabled = true;
    exportCsv.disabled = true;
    hide(analysisPanel);
    hide(mappingPanel);
    hide(resultPanel);
  }

  function payload() {
    return {
      markdown: markdownText.value,
      upload_result: state.uploadResult,
      manifest: state.manifest,
      mode: currentMode(),
      allow_mismatch: !!allowMismatch.checked,
      markdown_name: state.markdownFilename,
      upload_result_name: state.uploadFilename,
      manifest_name: state.manifestFilename
    };
  }

  function postJson(url, data) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    }).then(function (response) {
      return window.qtParseApiResponse(response).then(function (body) {
        return { ok: response.ok, status: response.status, data: body };
      });
    });
  }

  function analyze() {
    if (!markdownText.value.trim()) {
      toast("请先选择或粘贴带占位符的 Markdown", true);
      return;
    }
    if (!state.uploadResult) {
      toast("请先导入 upload_result.json（由浏览器扩展导出）", true);
      return;
    }

    analyzeBtn.disabled = true;
    analyzeBtn.textContent = "正在校验…";
    postJson("/api/upload-result/analyze", payload())
      .then(function (response) {
        if (!response.ok) {
          throw new Error((response.data && response.data.error) || "校验失败");
        }
        state.analysis = response.data;
        state.result = null;
        hide(resultPanel);
        renderAnalysis();
        toast(
          "校验完成：成功 " + number(response.data.counts && response.data.counts.success) +
          "，失败 " + number(response.data.counts && response.data.counts.failed) +
          "，未上传 " + number(response.data.counts && response.data.counts.not_uploaded)
        );
      })
      .catch(function (error) {
        toast("校验失败：" + (error.message || error), true);
      })
      .then(function () {
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = "预览替换结果";
      });
  }

  function renderAnalysis() {
    var analysis = state.analysis;
    if (!analysis) { return; }
    var counts = analysis.counts || {};
    document.getElementById("count-manifest").textContent = number(counts.manifest_images);
    document.getElementById("count-target").textContent = number(counts.target_images);
    document.getElementById("count-placeholders").textContent = number(counts.markdown_placeholders);
    document.getElementById("count-success").textContent = number(counts.success);
    document.getElementById("count-failed").textContent = number(counts.failed);
    document.getElementById("count-not-uploaded").textContent = number(counts.not_uploaded);
    document.getElementById("count-unmatched").textContent = number(counts.unmatched);
    document.getElementById("count-pending").textContent =
      number(counts.pending) + number(counts.interrupted);
    document.getElementById("count-converted").textContent = number(counts.converted);
    document.getElementById("count-unsupported").textContent = number(counts.unsupported);
    document.getElementById("count-oversized").textContent = number(counts.oversized);
    document.getElementById("count-conversion-failed").textContent =
      number(counts.conversion_failed);
    document.getElementById("count-embedded").textContent = number(counts.embedded);
    document.getElementById("count-special").textContent = number(counts.special_placeholders);
    document.getElementById("count-unexpected").textContent = number(counts.unexpected_upload);
    document.getElementById("count-review").textContent = number(counts.needs_review);
    document.getElementById("count-unknown").textContent = number(counts.placeholders_not_in_manifest);
    document.getElementById("count-missing-md").textContent = number(counts.manifest_not_in_markdown);
    document.getElementById("count-code").textContent = number(counts.code_block_placeholders);

    var match = analysis.document_id_match;
    if (analysis.document_id && analysis.upload_document_id) {
      consistency.textContent = match
        ? "document_id 一致：" + analysis.document_id
        : "document_id 不一致：manifest " + analysis.document_id +
          " / upload_result " + analysis.upload_document_id;
      consistency.style.color = match ? "" : "var(--error)";
    } else {
      consistency.textContent = analysis.manifest_provided
        ? "未检测到完整 document_id，无法交叉校验文档一致性。"
        : "未提供 manifest.json：只能按上传记录推断，缺失清单可能不完整。";
      consistency.style.color = "";
    }

    renderMessages("error-list", analysis.errors || []);
    renderMessages("warning-list", analysis.warnings || []);
    renderTable(analysis);
    show(analysisPanel);
    show(mappingPanel);
    generateBtn.disabled = !analysis.can_generate;
    exportCsv.disabled = false;
  }

  function renderMessages(id, messages) {
    var list = document.getElementById(id);
    list.innerHTML = "";
    if (!messages || !messages.length) {
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

  function renderTable(analysis) {
    mappingBody.innerHTML = "";
    var images = (analysis.images || []).filter(function (image) {
      return image.in_target || image.is_special;
    });
    if (!images.length && analysis.targets && analysis.targets.length) {
      images = analysis.targets;
    }
    if (!images.length) {
      var emptyRow = document.createElement("tr");
      var cell = document.createElement("td");
      cell.colSpan = 6;
      cell.textContent = "没有可处理的图片";
      emptyRow.appendChild(cell);
      mappingBody.appendChild(emptyRow);
      mappingSummary.textContent = "";
      return;
    }

    var replaced = 0;
    var kept = 0;
    var special = 0;
    images.forEach(function (image) {
      if (image.is_special) { special += 1; }
      if (image.upload_status === "success" && image.in_markdown) { replaced += 1; }
      if (!image.is_special && image.upload_status !== "success" && image.in_markdown) {
        kept += 1;
      }
      mappingBody.appendChild(buildRow(image));
    });
    var unexpected = analysis.unexpected_uploads || [];
    unexpected.forEach(function (record) {
      mappingBody.appendChild(buildUnexpectedRow(record));
    });
    mappingSummary.textContent =
      "替换 " + replaced + " 张 · 保留普通占位符 " + kept + " 张 · 特殊占位符 " +
      special + " 张 · 共 " + images.length + " 条" +
      (unexpected.length ? " · 意外上传 " + unexpected.length + " 条" : "");
  }

  function buildUnexpectedRow(record) {
    var row = document.createElement("tr");

    var orderCell = document.createElement("td");
    orderCell.textContent = "#" + (record.sequence != null ? String(record.sequence).padStart(6, "0") : "?");
    row.appendChild(orderCell);

    var thumbCell = document.createElement("td");
    var empty = document.createElement("div");
    empty.className = "mapping-thumb-empty";
    empty.textContent = "清单外";
    thumbCell.appendChild(empty);
    row.appendChild(thumbCell);

    var textCell = document.createElement("td");
    textCell.className = "text-cell";
    var token = document.createElement("strong");
    token.className = "placeholder-code";
    token.textContent = record.placeholder || record.occurrence_id || "未知位置";
    var fileName = document.createElement("span");
    fileName.textContent = record.file_name || "";
    textCell.appendChild(token);
    textCell.appendChild(fileName);
    row.appendChild(textCell);

    var resultCell = document.createElement("td");
    var badge = document.createElement("span");
    badge.className = "status-badge failed";
    badge.textContent = "意外上传";
    resultCell.appendChild(badge);
    row.appendChild(resultCell);

    var urlCell = document.createElement("td");
    var reason = document.createElement("div");
    reason.className = "result-reason";
    reason.textContent = record.reason || record.error || "上传记录中的图片不在当前 manifest 内";
    urlCell.appendChild(reason);
    row.appendChild(urlCell);

    var contextCell = document.createElement("td");
    contextCell.className = "context-cell";
    contextCell.textContent = "不在 manifest 内，未替换";
    row.appendChild(contextCell);

    return row;
  }

  function buildRow(image) {
    var row = document.createElement("tr");
    row.setAttribute("data-placeholder", image.placeholder || "");

    var orderCell = document.createElement("td");
    orderCell.textContent = image.sequence != null
      ? "#" + String(image.sequence).padStart(6, "0")
      : "#";
    row.appendChild(orderCell);

    var thumbCell = document.createElement("td");
    var thumbUrl = image.file_name ? state.imageUrls[image.file_name] : null;
    if (!thumbUrl && image.local_file) {
      thumbUrl = state.imageUrls[basename(image.local_file)];
    }
    if (thumbUrl) {
      var img = document.createElement("img");
      img.className = "mapping-thumb";
      img.src = thumbUrl;
      img.alt = image.alt_text || "";
      thumbCell.appendChild(img);
    } else {
      var empty = document.createElement("div");
      empty.className = "mapping-thumb-empty";
      empty.textContent = "无缩略图";
      thumbCell.appendChild(empty);
    }
    row.appendChild(thumbCell);

    var textCell = document.createElement("td");
    textCell.className = "text-cell";
    var token = document.createElement("strong");
    token.className = "placeholder-code";
    token.textContent = image.placeholder || "";
    var fileName = document.createElement("span");
    var names = [];
    if (image.source_file_name) { names.push("原：" + image.source_file_name); }
    if (image.upload_file_name && image.upload_file_name !== image.source_file_name) {
      names.push("传：" + image.upload_file_name);
    }
    fileName.textContent = names.join(" · ") ||
      image.file_name || image.local_file || image.alt_text || "";
    textCell.appendChild(token);
    textCell.appendChild(fileName);
    row.appendChild(textCell);

    var resultCell = document.createElement("td");
    resultCell.className = "result-cell";
    var badge = document.createElement("span");
    badge.className = "status-badge " + statusClass(image);
    badge.textContent = statusLabel(image);
    resultCell.appendChild(badge);
    row.appendChild(resultCell);

    var urlCell = document.createElement("td");
    if (image.upload_status === "success" && image.url) {
      var link = document.createElement("a");
      link.className = "result-url";
      link.href = image.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = image.url;
      urlCell.appendChild(link);
      if (!image.in_markdown) {
        var note = document.createElement("div");
        note.className = "result-reason";
        note.style.color = "var(--muted)";
        note.textContent = "Markdown 中没有该占位符，未替换";
        urlCell.appendChild(note);
      }
    } else {
      var reason = document.createElement("div");
      reason.className = "result-reason";
      if (image.compatibility === "embedded") {
        reason.textContent = "嵌入文件不自动替换，请自行在 ShowDoc 上传";
      } else {
        reason.textContent = image.is_special
          ? "特殊占位符保持不动：" + (image.reason || image.compatibility_reason || "")
          : (image.reason || "保留原占位符");
      }
      urlCell.appendChild(reason);
    }
    row.appendChild(urlCell);

    var contextCell = document.createElement("td");
    contextCell.className = "context-cell";
    var section = document.createElement("div");
    section.className = "section";
    section.textContent = image.section || "未识别章节";
    var context = document.createElement("div");
    context.className = "context";
    context.textContent = (image.context_before ? "…" + image.context_before : "") +
      (image.context_after ? "【图】" + image.context_after + "…" : "");
    contextCell.appendChild(section);
    contextCell.appendChild(context);
    row.appendChild(contextCell);

    return row;
  }

  function statusClass(image) {
    if (image.upload_status === "success") { return "success"; }
    if (image.upload_status === "failed" || image.upload_status === "unmatched" ||
        image.upload_status === "conversion_failed" ||
        image.upload_status === "unsupported") {
      return "failed";
    }
    if (image.upload_status === "oversized" || image.upload_status === "pending" ||
        image.upload_status === "interrupted") {
      return "review";
    }
    if (image.needs_review) { return "review"; }
    return "pending";
  }

  function statusLabel(image) {
    if (image.upload_status === "success") {
      return image.in_markdown ? "成功，替换为 URL" : "成功，正文无占位符";
    }
    if (image.upload_status === "failed") { return "失败，保留占位符"; }
    if (image.upload_status === "not_uploaded") { return "未上传，保留占位符"; }
    if (image.upload_status === "unmatched") { return "无法匹配，保留占位符"; }
    if (image.upload_status === "pending") { return "待定，保留占位符"; }
    if (image.upload_status === "interrupted") { return "中断，保留占位符"; }
    if (image.upload_status === "unsupported") { return "不支持，保留特殊占位符"; }
    if (image.upload_status === "oversized") { return "超限，保留特殊占位符"; }
    if (image.upload_status === "conversion_failed") { return "转换失败，保留特殊占位符"; }
    return image.upload_status || "未知";
  }

  function requestGenerate(confirmed) {
    var body = payload();
    body.confirmed = !!confirmed;
    generateBtn.disabled = true;
    generateBtn.textContent = confirmed ? "正在生成…" : "正在准备缩略图…";

    buildThumbnails()
      .then(function (thumbnails) {
        body.thumbnails = thumbnails;
        return postJson("/api/upload-result/generate", body);
      })
      .then(function (response) {
        var data = response.data || {};
        if (response.status === 409 || (data.requires_confirmation && !confirmed)) {
          var counts = data.counts || {};
          var message = (data.error || "仍有图片未成功。") + "\n\n" +
            "失败 " + number(counts.failed) +
            " · 未上传 " + number(counts.not_uploaded) +
            " · 待定/中断 " + (number(counts.pending) + number(counts.interrupted)) +
            " · 无法匹配 " + number(counts.unmatched) +
            " · 特殊占位符 " + number(counts.special_images) +
            "\n\n仍要按部分成功模式生成吗？未成功的普通图片会保留占位符，特殊占位符保持不动。";
          if (window.confirm(message)) {
            return requestGenerate(true);
          }
          toast("已取消生成");
          return null;
        }
        if (!response.ok) {
          if (data.analysis) {
            state.analysis = data.analysis;
            renderAnalysis();
          }
          throw new Error(data.error || "生成失败");
        }
        state.result = data;
        if (data.analysis) {
          state.analysis = data.analysis;
          renderAnalysis();
        }
        renderResult(data);
        if (!data.ok) {
          toast("已生成中间结果，但后续校验发现问题，请查看报告", true);
        } else {
          toast("已生成：" + data.replaced_count + " 张替换成功，" +
            (data.remaining_placeholders || []).length + " 个占位符保留");
        }
        return null;
      })
      .catch(function (error) {
        toast("生成失败：" + (error.message || error), true);
      })
      .then(function () {
        generateBtn.textContent = "生成最终 Markdown";
        generateBtn.disabled = !state.analysis || !state.analysis.can_generate;
      });
  }

  function renderResult(data) {
    resultText.value = data.markdown || "";
    var notes = [];
    notes.push("已替换 " + number(data.replaced_count) + " 个占位符");
    if (data.skipped_code_count) { notes.push("代码块跳过 " + data.skipped_code_count + " 个"); }
    if (data.skipped_missing_count) { notes.push("保留 " + data.skipped_missing_count + " 个占位符"); }
    var specialCount = data.analysis && data.analysis.counts
      ? number(data.analysis.counts.special_images) : 0;
    if (specialCount) { notes.push("特殊占位符保持不动 " + specialCount + " 张"); }
    if ((data.warnings || []).length) { notes.push(data.warnings.join("；")); }
    if ((data.post_errors || []).length) { notes.push("后续校验异常：" + data.post_errors.join("；")); }
    resultNote.textContent = notes.join("；");
    downloadMd.disabled = !(data.artifacts && data.artifacts.markdown);
    downloadCsv.disabled = !(data.artifacts && data.artifacts.csv);
    downloadReport.disabled = !(data.artifacts && data.artifacts.report);
    downloadHtml.disabled = !(data.artifacts && data.artifacts.html);
    show(resultPanel);
    resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // ---------------------------------------------------------------------
  // Thumbnails for missing_images.html

  function missingImages() {
    if (!state.analysis) { return []; }
    return (state.analysis.images || []).filter(function (image) {
      if (image.is_special) { return true; }
      return image.in_target && image.upload_status !== "success";
    });
  }

  function buildThumbnails() {
    var missing = missingImages();
    if (!missing.length) { return Promise.resolve({}); }
    var limited = missing.slice(0, MAX_THUMBNAILS);
    if (missing.length > MAX_THUMBNAILS) {
      toast("缺失图片较多，missing_images.html 只嵌入前 " + MAX_THUMBNAILS + " 张缩略图", true);
    }

    return Promise.all(limited.map(function (image) {
      var file = state.filesByName[image.file_name || basename(image.local_file)];
      if (!file) { return Promise.resolve(null); }
      return downscale(file).then(function (dataUrl) {
        return dataUrl ? { image: image, dataUrl: dataUrl } : null;
      }).catch(function () { return null; });
    })).then(function (items) {
      var thumbnails = {};
      items.forEach(function (item) {
        if (!item) { return; }
        if (item.image.placeholder) { thumbnails[item.image.placeholder] = item.dataUrl; }
        if (item.image.file_name) { thumbnails[item.image.file_name] = item.dataUrl; }
      });
      return thumbnails;
    });
  }

  function downscale(file) {
    if (file.type === "image/emf" || file.type === "image/wmf" || file.type === "image/tiff") {
      return Promise.resolve(null);
    }
    return new Promise(function (resolve) {
      var url = URL.createObjectURL(file);
      var image = new Image();
      image.onload = function () {
        try {
          var max = 320;
          var scale = Math.min(1, max / Math.max(image.naturalWidth, image.naturalHeight));
          var canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
          canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
          var context = canvas.getContext("2d");
          context.fillStyle = "#ffffff";
          context.fillRect(0, 0, canvas.width, canvas.height);
          context.drawImage(image, 0, 0, canvas.width, canvas.height);
          resolve(canvas.toDataURL("image/jpeg", 0.72));
        } catch (error) {
          resolve(null);
        } finally {
          URL.revokeObjectURL(url);
        }
      };
      image.onerror = function () {
        URL.revokeObjectURL(url);
        resolve(null);
      };
      image.src = url;
    });
  }

  // ---------------------------------------------------------------------
  // Exports

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

  function artifact(key, fallbackName) {
    if (state.result && state.result.artifacts && state.result.artifacts[key]) {
      return state.result.artifacts[key];
    }
    return null;
  }

  function downloadArtifact(key, fallbackName) {
    var item = artifact(key);
    if (!item) {
      toast("请先生成最终 Markdown", true);
      return;
    }
    downloadText(item.filename || fallbackName, item.content, item.mime);
  }

  function exportMissingCsv() {
    var item = artifact("csv");
    if (item) {
      downloadText(item.filename, item.content, item.mime);
      return;
    }
    if (!state.analysis) {
      toast("请先预览替换结果", true);
      return;
    }
    var rows = csvRows();
    downloadText("missing_images.csv", csvText(rows), "text/csv;charset=utf-8");
  }

  function csvRows() {
    var rows = [];
    (state.analysis.images || []).forEach(function (image) {
      if (!image.is_special && (!image.in_target || image.upload_status === "success")) {
        return;
      }
      rows.push({
        "序号": image.sequence != null ? image.sequence : "",
        "occurrence_id": image.occurrence_id || "",
        "占位符": image.placeholder || "",
        "原始文件名": image.source_file_name || "",
        "原始路径": image.source_file || "",
        "上传文件名": image.upload_file_name || "",
        "上传路径": image.upload_file || "",
        "大小": image.size != null ? image.size : "",
        "SHA-256": image.upload_sha256 || image.source_sha256 || image.sha256 || "",
        "原始SHA-256": image.source_sha256 || image.sha256 || "",
        "上传SHA-256": image.upload_sha256 || "",
        "章节": image.section || "",
        "上下文前置文字": image.context_before || "",
        "上下文后置文字": image.context_after || "",
        "状态": image.upload_status || "",
        "失败原因": image.reason || image.compatibility_reason || "",
        "是否在Markdown中": image.in_markdown ? "是" : "否",
        "行号": image.line != null ? image.line : ""
      });
    });
    (state.analysis.unexpected_uploads || []).forEach(function (record) {
      rows.push({
        "序号": "",
        "occurrence_id": record.occurrence_id || "",
        "占位符": record.placeholder || "",
        "原始文件名": record.file_name || "",
        "原始路径": "",
        "上传文件名": "",
        "上传路径": "",
        "大小": "",
        "SHA-256": record.sha256 || "",
        "原始SHA-256": record.sha256 || "",
        "上传SHA-256": record.sha256 || "",
        "章节": "",
        "上下文前置文字": "",
        "上下文后置文字": "",
        "状态": "unexpected_upload",
        "失败原因": record.reason || record.error || "清单外的上传记录",
        "是否在Markdown中": "",
        "行号": ""
      });
    });
    return rows;
  }

  function csvText(rows) {
    var lines = [CSV_COLUMNS.map(csvCell).join(",")];
    rows.forEach(function (row) {
      lines.push(CSV_COLUMNS.map(function (column) {
        return csvCell(row[column]);
      }).join(","));
    });
    return "﻿" + lines.join("\r\n") + "\r\n";
  }

  function csvCell(value) {
    var text = value == null ? "" : String(value);
    if (/[",\r\n]/.test(text)) {
      return '"' + text.replace(/"/g, '""') + '"';
    }
    return text;
  }

  function copyResultText() {
    if (!resultText.value) {
      toast("没有可复制的 Markdown", true);
      return;
    }
    navigator.clipboard.writeText(resultText.value).then(function () {
      toast("已复制最终 Markdown");
    }).catch(function (error) {
      toast("复制失败：" + (error.message || error), true);
    });
  }

  // ---------------------------------------------------------------------
  // Loading and reset

  function renderUploadSummary(data) {
    uploadSummaryList.innerHTML = "";
    if (!data) { return; }
    var entries = [
      ["manifest_document_id", data.manifest_document_id || "（未提供）"],
      ["expected_count", data.expected_count],
      ["detected_request_count", data.detected_request_count],
      ["success_unique_count", data.success_unique_count],
      ["failed_count", data.failed_count],
      ["not_uploaded_count", data.not_uploaded_count],
      ["unmatched_count", data.unmatched_count],
      ["uploads", (data.uploads || []).length],
      ["missing", (data.missing || []).length]
    ];
    entries.forEach(function (entry) {
      if (entry[1] === undefined || entry[1] === null) { return; }
      var item = document.createElement("li");
      item.textContent = entry[0] + "：" + entry[1];
      uploadSummaryList.appendChild(item);
    });
  }

  function clearImages() {
    Object.keys(state.imageUrls).forEach(function (name) {
      URL.revokeObjectURL(state.imageUrls[name]);
    });
    state.imageUrls = {};
    state.filesByName = {};
  }

  function clearAll() {
    markdownFile.value = "";
    uploadFile.value = "";
    manifestFile.value = "";
    imageFiles.value = "";
    markdownText.value = "";
    markdownName.textContent = "";
    uploadName.textContent = "";
    uploadSummaryList.innerHTML = "";
    manifestName.textContent = "未上传 manifest（无法交叉校验与生成完整缺失清单）";
    imageCount.textContent = "未选择图片，缺失清单没有缩略图";
    state.markdownFilename = "";
    state.uploadFilename = "";
    state.manifestFilename = "";
    state.uploadResult = null;
    state.manifest = null;
    clearImages();
    resetAnalysis();
  }

  function basename(path) {
    if (!path) { return ""; }
    var parts = String(path).replace(/\\/g, "/").split("/");
    return parts[parts.length - 1];
  }

  function number(value) {
    return value == null ? 0 : value;
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

  uploadFile.addEventListener("change", function () {
    if (!uploadFile.files.length) { return; }
    var file = uploadFile.files[0];
    readTextFile(file, function (text) {
      try {
        state.uploadResult = JSON.parse(text);
        state.uploadFilename = file.name;
        uploadName.textContent = "已加载：" + file.name;
        renderUploadSummary(state.uploadResult);
        resetAnalysis();
      } catch (error) {
        state.uploadResult = null;
        uploadName.textContent = "upload_result.json 解析失败";
        uploadSummaryList.innerHTML = "";
        toast("upload_result.json 解析失败：" + (error.message || error), true);
      }
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
        manifestName.textContent = "manifest.json 解析失败";
        toast("manifest.json 解析失败", true);
      }
    });
  });

  imageFiles.addEventListener("change", function () {
    clearImages();
    var files = Array.from(imageFiles.files || []);
    files.forEach(function (file) {
      state.filesByName[file.name] = file;
      state.imageUrls[file.name] = URL.createObjectURL(file);
    });
    imageCount.textContent = files.length
      ? "已选择 " + files.length + " 张图片"
      : "未选择图片，缺失清单没有缩略图";
    if (state.analysis) { renderTable(state.analysis); }
  });

  markdownText.addEventListener("input", resetAnalysis);
  allowMismatch.addEventListener("change", resetAnalysis);
  Array.prototype.forEach.call(
    document.querySelectorAll('input[name="mode"]'),
    function (input) { input.addEventListener("change", resetAnalysis); }
  );

  analyzeBtn.addEventListener("click", analyze);
  generateBtn.addEventListener("click", function () { requestGenerate(false); });
  exportCsv.addEventListener("click", exportMissingCsv);
  clearBtn.addEventListener("click", clearAll);
  copyResult.addEventListener("click", copyResultText);

  downloadMd.addEventListener("click", function () {
    downloadArtifact("markdown", "final_markdown.md");
  });
  downloadCsv.addEventListener("click", function () {
    downloadArtifact("csv", "missing_images.csv");
  });
  downloadReport.addEventListener("click", function () {
    downloadArtifact("report", "replacement_report.json");
  });
  downloadHtml.addEventListener("click", function () {
    downloadArtifact("html", "missing_images.html");
  });
})();
