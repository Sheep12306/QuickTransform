(function () {
  var markdownFile = document.getElementById("markdown-file");
  var uploadFile = document.getElementById("upload-file");
  var manifestFile = document.getElementById("manifest-file");
  var markdownText = document.getElementById("markdown-text");
  var uploadText = document.getElementById("upload-text");
  var manifestText = document.getElementById("manifest-text");
  var markdownName = document.getElementById("markdown-name");
  var uploadName = document.getElementById("upload-name");
  var uploadSummaryList = document.getElementById("upload-summary-list");
  var manifestName = document.getElementById("manifest-name");
  var analyzeBtn = document.getElementById("analyze-btn");
  var generateBtn = document.getElementById("generate-btn");
  var stepHint = document.getElementById("step-hint");
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
  var toastEl = document.getElementById("toast");

  var MANIFEST_HINT = "未提供 manifest：仍可替换，但无法校验文档一致性，缺失清单也不完整";
  var STEP_HINT = "先点击「一键替换」检查匹配结果，确认后才能生成";

  var state = {
    markdownFilename: "",
    uploadFilename: "",
    manifestFilename: "",
    uploadResult: null,
    manifest: null,
    analysis: null,
    result: null,
    uploadTimer: null,
    manifestTimer: null,
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
    hide(analysisPanel);
    hide(mappingPanel);
    hide(resultPanel);
    stepHint.textContent = STEP_HINT;
    stepHint.classList.remove("ready");
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
    analyzeBtn.textContent = "正在替换…";
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
          "检查完成：成功 " + number(response.data.counts && response.data.counts.success) +
          "，失败 " + number(response.data.counts && response.data.counts.failed) +
          "，未上传 " + number(response.data.counts && response.data.counts.not_uploaded)
        );
      })
      .catch(function (error) {
        toast("替换失败：" + (error.message || error), true);
      })
      .then(function () {
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = "① 一键替换";
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
    if (analysis.can_generate) {
      stepHint.textContent = "检查通过，可以生成最终 Markdown";
      stepHint.classList.add("ready");
    } else {
      stepHint.textContent = "检查未通过，请先处理下方错误信息";
      stepHint.classList.remove("ready");
    }
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
      cell.colSpan = 5;
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

    row.appendChild(buildLocateCell(image));
    return row;
  }

  function buildLocateCell(image) {
    var cell = document.createElement("td");
    cell.className = "context-cell";
    var section = document.createElement("div");
    section.className = "section";
    section.textContent = image.section || "未识别章节";
    section.title = image.section || "";

    var context = document.createElement("div");
    context.className = "context";
    context.title = "复制这一行到原文中搜索，可快速定位图片";
    var before = lastSentence(image.context_before);
    var after = firstSentence(image.context_after);
    if (before) {
      context.appendChild(document.createTextNode("…" + before + " "));
    }
    var marker = document.createElement("code");
    marker.className = "context-marker";
    marker.textContent = image.placeholder || "【图片】";
    context.appendChild(marker);
    if (after) {
      context.appendChild(document.createTextNode(" " + after + "…"));
    }
    if (!before && !after) {
      context.textContent = image.in_markdown
        ? "正文中没有可用的上下文"
        : "Markdown 正文中没有该占位符";
    }

    cell.appendChild(section);
    cell.appendChild(context);
    return cell;
  }

  function lastSentence(text) {
    var value = String(text || "").replace(/\s+/g, " ").trim();
    if (!value) { return ""; }
    var match = value.match(/([^。！？!?；;]+[。！？!?；;]?)\s*$/);
    return (match ? match[1] : value).trim();
  }

  function firstSentence(text) {
    var value = String(text || "").replace(/\s+/g, " ").trim();
    if (!value) { return ""; }
    var match = value.match(/^.*?[。！？!?；;]/);
    return (match ? match[0] : value).trim();
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
    generateBtn.textContent = confirmed ? "正在生成…" : "正在准备…";

    postJson("/api/upload-result/generate", body)
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
        generateBtn.textContent = "② 生成最终 Markdown";
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
    stepHint.textContent = "已生成最终 Markdown，可以复制或下载";
    stepHint.classList.add("ready");
    show(resultPanel);
    resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
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

  function downloadArtifact(key, fallbackName) {
    var item = state.result && state.result.artifacts && state.result.artifacts[key];
    if (!item) {
      toast("请先生成最终 Markdown", true);
      return;
    }
    downloadText(item.filename || fallbackName, item.content, item.mime);
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
  // Input loading

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

  function setUploadResult(parsed, label) {
    state.uploadResult = parsed;
    state.uploadFilename = label || "";
    renderUploadSummary(parsed);
    resetAnalysis();
  }

  function clearUploadResult(message) {
    state.uploadResult = null;
    state.uploadFilename = "";
    uploadSummaryList.innerHTML = "";
    uploadName.textContent = message || "未导入上传记录";
    resetAnalysis();
  }

  function applyUploadText(text, label) {
    if (!text.trim()) {
      clearUploadResult("未导入上传记录");
      return;
    }
    var parsed;
    try {
      parsed = JSON.parse(text);
    } catch (error) {
      clearUploadResult("JSON 解析失败：" + (error.message || error));
      return;
    }
    uploadName.textContent = label || "已粘贴 upload_result.json";
    setUploadResult(parsed, label || "粘贴的 upload_result.json");
  }

  function setManifest(parsed, label) {
    state.manifest = parsed;
    state.manifestFilename = label || "";
    var count = parsed && Array.isArray(parsed.images) ? parsed.images.length : 0;
    manifestName.textContent = "已加载：" + (label || "manifest.json") +
      "（" + count + " 张图片）";
    resetAnalysis();
  }

  function clearManifest(message) {
    state.manifest = null;
    state.manifestFilename = "";
    manifestName.textContent = message || MANIFEST_HINT;
    resetAnalysis();
  }

  function applyManifestText(text, label) {
    if (!text.trim()) {
      clearManifest();
      return;
    }
    var parsed;
    try {
      parsed = JSON.parse(text);
    } catch (error) {
      clearManifest("manifest.json 解析失败：" + (error.message || error));
      return;
    }
    setManifest(parsed, label || "粘贴的 manifest.json");
  }

  function clearAll() {
    markdownFile.value = "";
    uploadFile.value = "";
    manifestFile.value = "";
    markdownText.value = "";
    uploadText.value = "";
    manifestText.value = "";
    markdownName.textContent = "";
    uploadSummaryList.innerHTML = "";
    uploadName.textContent = "未导入上传记录";
    manifestName.textContent = MANIFEST_HINT;
    state.markdownFilename = "";
    state.uploadFilename = "";
    state.manifestFilename = "";
    state.uploadResult = null;
    state.manifest = null;
    resetAnalysis();
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
      uploadText.value = text;
      applyUploadText(text, file.name);
    });
  });

  manifestFile.addEventListener("change", function () {
    if (!manifestFile.files.length) { return; }
    var file = manifestFile.files[0];
    readTextFile(file, function (text) {
      manifestText.value = text;
      applyManifestText(text, file.name);
    });
  });

  uploadText.addEventListener("input", function () {
    if (state.uploadTimer) { clearTimeout(state.uploadTimer); }
    state.uploadTimer = setTimeout(function () {
      state.uploadTimer = null;
      applyUploadText(uploadText.value, "");
    }, 520);
  });

  manifestText.addEventListener("input", function () {
    if (state.manifestTimer) { clearTimeout(state.manifestTimer); }
    state.manifestTimer = setTimeout(function () {
      state.manifestTimer = null;
      applyManifestText(manifestText.value, "");
    }, 520);
  });

  markdownText.addEventListener("input", resetAnalysis);
  allowMismatch.addEventListener("change", resetAnalysis);
  Array.prototype.forEach.call(
    document.querySelectorAll('input[name="mode"]'),
    function (input) { input.addEventListener("change", resetAnalysis); }
  );

  analyzeBtn.addEventListener("click", analyze);
  generateBtn.addEventListener("click", function () { requestGenerate(false); });
  clearBtn.addEventListener("click", clearAll);
  copyResult.addEventListener("click", copyResultText);

  downloadMd.addEventListener("click", function () {
    downloadArtifact("markdown", "final_markdown.md");
  });
  downloadCsv.addEventListener("click", function () {
    downloadArtifact("csv", "missing_images.csv");
  });
})();
