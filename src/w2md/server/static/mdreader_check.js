/* Optional check/repair features for the Markdown reader.
   The reader itself is the primary surface; this script only manages the
   collapsible panel and never changes the reader unless "应用到阅读器" is used. */
(function () {
  var source = document.getElementById("source");
  var checkToggle = document.getElementById("check-toggle");
  var checkPanel = document.getElementById("check-panel");
  var checkSub = document.getElementById("check-sub");
  var manifestFile = document.getElementById("manifest-file");
  var manifestName = document.getElementById("manifest-name");
  var specialList = document.getElementById("special-list");
  var analyzeBtn = document.getElementById("analyze-btn");
  var generateBtn = document.getElementById("generate-btn");
  var checkHint = document.getElementById("check-hint");
  var clearCheckBtn = document.getElementById("clear-check");
  var resultPanel = document.getElementById("result-panel");
  var resultText = document.getElementById("result-text");
  var resultNote = document.getElementById("result-note");
  var copyResult = document.getElementById("copy-result");
  var downloadMd = document.getElementById("download-md");
  var applyResult = document.getElementById("apply-result");
  var downloadManifest = document.getElementById("download-manifest");
  var toastEl = document.getElementById("toast");

  var EMPTY_HINT = "导入 manifest.json 后，这里会列出 unsupported / oversized / conversion_failed 图片。";
  var MANIFEST_HINT = "未导入 manifest（检查功能不可用）";

  var state = {
    manifest: null,
    manifestFilename: "",
    urls: {},
    analysis: null,
    result: null,
    lastFinalCheck: null,
    listSignature: "",
    cardEntries: [],
    activePlaceholder: "",
    analyzeTimer: null,
    analyzeSeq: 0,
    applying: false,
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

  function number(value) {
    return value == null ? 0 : value;
  }

  function pad(value) {
    return String(value == null ? 0 : value).padStart(6, "0");
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

  function resetResult() {
    state.result = null;
    state.lastFinalCheck = null;
    hide(resultPanel);
  }

  function payload() {
    return {
      markdown: source.value,
      manifest: state.manifest,
      urls: state.urls
    };
  }

  function cancelAnalyze() {
    if (state.analyzeTimer) {
      clearTimeout(state.analyzeTimer);
      state.analyzeTimer = null;
    }
    state.analyzeSeq += 1;
  }

  function scheduleAnalyze() {
    if (!state.manifest) { return; }
    if (state.analyzeTimer) { clearTimeout(state.analyzeTimer); }
    state.analyzeTimer = setTimeout(function () {
      state.analyzeTimer = null;
      analyze(false);
    }, 420);
  }

  function analyze(showToast) {
    if (!state.manifest) {
      toast("请先在检查面板导入 manifest.json", true);
      return;
    }
    if (!source.value.trim()) {
      toast("请先打开或粘贴 Markdown 源码", true);
      return;
    }
    var sequence = ++state.analyzeSeq;
    analyzeBtn.disabled = true;
    analyzeBtn.textContent = "正在检查…";
    postJson("/api/special-images/analyze", payload())
      .then(function (response) {
        if (sequence !== state.analyzeSeq) { return; }
        if (!response.ok) {
          throw new Error((response.data && response.data.error) || "检查失败");
        }
        state.analysis = response.data;
        renderAnalysis();
        if (showToast) {
          var counts = response.data.counts || {};
          toast(
            "检查完成：特殊图片 " + number(counts.special_images) +
            " 张，待处理 " + number(counts.pending) +
            " 张，普通占位符残留 " + number(counts.normal_residue_occurrences) + " 个"
          );
        }
      })
      .catch(function (error) {
        if (sequence !== state.analyzeSeq) { return; }
        toast("检查失败：" + (error.message || error), true);
      })
      .then(function () {
        if (sequence !== state.analyzeSeq) { return; }
        analyzeBtn.disabled = false;
        analyzeBtn.textContent = "重新检查";
      });
  }

  function renderAnalysis() {
    var analysis = state.analysis;
    if (!analysis) { return; }
    var counts = analysis.counts || {};

    document.getElementById("count-special").textContent = number(counts.special_images);
    document.getElementById("count-in-markdown").textContent = number(counts.in_markdown);
    document.getElementById("count-pending").textContent = number(counts.pending);

    if (state.manifest) {
      manifestName.textContent =
        "已加载：" + (state.manifestFilename || "manifest.json") +
        "（" + number(counts.manifest_images) + " 张图片 / 特殊 " +
        number(counts.special_images) + " 张）";
    }

    checkSub.textContent =
      "特殊占位符 " + number(counts.in_markdown) +
      " 个 · 待处理 " + number(counts.pending) +
      " 个 · 普通占位符残留 " + number(counts.normal_residue_occurrences) + " 个";

    renderChecks(analysis);
    renderMessages("error-list", analysis.errors || []);
    renderMessages("warning-list", analysis.warnings || []);
    renderList(analysis);
    generateBtn.disabled = !analysis.can_generate;
    checkHint.textContent = analysis.can_generate
      ? "检查通过，可以生成修正后的 Markdown"
      : "填写 URL 后会自动检查；仍有待处理项时不能生成";
  }

  function renderChecks(analysis) {
    var counts = analysis.counts || {};
    var normal = number(counts.normal_residue_occurrences);
    setCheck(
      "check-normal",
      String(normal),
      normal ? "存在残留，请先完成普通图片回填" : "无残留",
      normal ? "error" : "ok"
    );

    var pending = number(counts.pending);
    setCheck(
      "check-pending",
      pending + " / " + number(counts.in_markdown),
      pending ? "仍有特殊图片未填写 URL" : "全部已填写",
      pending ? "error" : "ok"
    );

    var invalid = number(counts.invalid_url);
    var filled = number(counts.matched);
    var inMarkdown = number(counts.in_markdown);
    setCheck(
      "check-url",
      inMarkdown ? filled + " / " + inMarkdown : "0",
      invalid
        ? invalid + " 个 URL 非法"
        : (!inMarkdown
          ? "无需填写"
          : (filled === inMarkdown ? "格式有效" : "还有 " + (inMarkdown - filled) + " 个待填写")),
      invalid ? "error" : (inMarkdown && filled < inMarkdown ? "warn" : "ok")
    );

    var duplicates = number(counts.occurrence_id_duplicates);
    setCheck(
      "check-occurrence",
      duplicates ? duplicates + " 组" : "唯一",
      duplicates ? "manifest 中存在重复" : "通过",
      duplicates ? "error" : "ok"
    );

    var unknown = number(counts.unknown_placeholders);
    setCheck(
      "check-unknown",
      String(unknown),
      unknown ? "Markdown 中有 manifest 未包含的占位符" : "通过",
      unknown ? "error" : "ok"
    );

    if (state.lastFinalCheck) {
      renderFinalCheck(state.lastFinalCheck);
    } else {
      setCheck("check-final", "—", "生成后检查", "idle");
    }
  }

  function renderFinalCheck(check) {
    if (!check) {
      setCheck("check-final", "—", "生成后检查", "idle");
      return;
    }
    if (check.passed) {
      setCheck(
        "check-final",
        "0",
        "通过（正文无残留" + (check.code_block ? "，代码块 " + check.code_block + " 个" : "") + "）",
        "ok"
      );
      return;
    }
    setCheck(
      "check-final",
      String(number(check.remaining_total)),
      "未通过，仍有占位符残留",
      "error"
    );
  }

  function setCheck(id, value, stateText, level) {
    var item = document.getElementById(id);
    if (!item) { return; }
    item.classList.remove("idle", "ok", "warn", "error");
    item.classList.add(level || "idle");
    document.getElementById(id + "-value").textContent = value;
    document.getElementById(id + "-state").textContent = stateText;
  }

  function setIdleChecks() {
    ["normal", "pending", "url", "occurrence", "unknown", "final"].forEach(function (name) {
      var id = "check-" + name;
      var item = document.getElementById(id);
      if (!item) { return; }
      item.classList.remove("idle", "ok", "warn", "error");
      item.classList.add("idle");
      document.getElementById(id + "-value").textContent = "—";
      document.getElementById(id + "-state").textContent =
        name === "final" ? "生成后检查" : "等待检查";
    });
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

  function renderList(analysis) {
    var items = analysis.items || [];
    var signature = items.map(function (item) {
      return [
        item.index,
        item.occurrence_id,
        item.placeholder,
        item.compatibility
      ].join(":");
    }).join("|");

    if (signature !== state.listSignature) {
      rebuildList(items);
      state.listSignature = signature;
      return;
    }
    items.forEach(function (item, index) {
      var entry = state.cardEntries[index];
      if (entry) { updateCard(entry, item); }
    });
  }

  function rebuildList(items) {
    specialList.innerHTML = "";
    state.cardEntries = [];

    if (!items.length) {
      var hint = document.createElement("p");
      hint.className = "empty-hint";
      hint.textContent = state.manifest
        ? "manifest 中没有特殊图片（unsupported / oversized / conversion_failed）。"
        : EMPTY_HINT;
      specialList.appendChild(hint);
      return;
    }

    items.forEach(function (item) {
      var entry = buildCard(item);
      state.cardEntries.push(entry);
      specialList.appendChild(entry.card);
      updateCard(entry, item);
    });
  }

  function buildCard(item) {
    var entry = { item: item };
    var card = document.createElement("article");
    card.className = "special-card";
    card.setAttribute("data-placeholder", item.placeholder);

    var top = document.createElement("div");
    top.className = "special-card-top";

    var sequence = document.createElement("span");
    sequence.className = "special-seq";
    sequence.textContent = "#" + pad(item.sequence);
    top.appendChild(sequence);

    var compatibility = document.createElement("span");
    compatibility.className = "compat-badge compat-" + item.compatibility;
    compatibility.textContent = item.compatibility_label || item.compatibility;
    top.appendChild(compatibility);

    var status = document.createElement("span");
    status.className = "special-status";
    top.appendChild(status);

    var locateBtn = document.createElement("button");
    locateBtn.type = "button";
    locateBtn.className = "locate-btn";
    locateBtn.textContent = "定位";
    locateBtn.addEventListener("click", function (event) {
      event.stopPropagation();
      locate(entry.item, card);
    });
    top.appendChild(locateBtn);

    card.appendChild(top);

    var token = document.createElement("code");
    token.className = "special-token";
    token.textContent = item.placeholder;
    card.appendChild(token);

    var meta = document.createElement("div");
    meta.className = "special-meta";
    card.appendChild(meta);

    var reason = document.createElement("div");
    reason.className = "special-reason";
    card.appendChild(reason);

    var input = document.createElement("input");
    input.type = "url";
    input.className = "special-url";
    input.spellcheck = false;
    input.placeholder = "粘贴 ShowDoc 图片 URL（https://…）";
    input.addEventListener("input", function () {
      state.urls[entry.item.placeholder] = input.value;
      resetResult();
      status.textContent = "检查中…";
      status.className = "special-status pending";
      input.classList.remove("invalid");
      scheduleAnalyze();
    });
    card.appendChild(input);

    var error = document.createElement("div");
    error.className = "special-error";
    card.appendChild(error);

    card.addEventListener("click", function (event) {
      if (event.target.closest("input, button, label, a")) { return; }
      locate(entry.item, card);
    });

    entry.card = card;
    entry.status = status;
    entry.meta = meta;
    entry.reason = reason;
    entry.input = input;
    entry.error = error;
    return entry;
  }

  function updateCard(entry, item) {
    var card = entry.card;
    entry.item = item;

    card.classList.toggle("not-in-markdown", !item.in_markdown);
    card.classList.toggle("active", item.placeholder === state.activePlaceholder);

    entry.status.className = "special-status " + item.status;
    entry.status.textContent = item.status_label || item.status;

    var pieces = [item.occurrence_id || "无 occurrence_id"];
    if (item.file_name) { pieces.push(item.file_name); }
    if (item.section) { pieces.push(item.section); }
    if (item.in_markdown) {
      pieces.push("第 " + item.line + " 行 × " + item.occurrence_count);
    } else if (item.code_occurrence_count) {
      pieces.push("仅代码块 × " + item.code_occurrence_count);
    } else {
      pieces.push("正文中无占位符");
    }
    entry.meta.textContent = pieces.join(" · ");

    entry.reason.textContent = item.reason || "";
    entry.error.textContent = item.error || "";
    entry.input.classList.toggle("invalid", item.status === "invalid_url");

    if (document.activeElement !== entry.input) {
      entry.input.value = valueFor(item);
    }
    entry.input.title = item.in_markdown
      ? "填写该特殊图片在 ShowDoc 中的图片 URL"
      : "Markdown 正文中没有该特殊占位符";
  }

  function valueFor(item) {
    if (Object.prototype.hasOwnProperty.call(state.urls, item.placeholder)) {
      return state.urls[item.placeholder];
    }
    return item.url || "";
  }

  function locate(item, card) {
    var occurrence = item.occurrences && item.occurrences[0];
    if (!occurrence) {
      if (item.code_occurrence_count) {
        toast("该占位符只出现在代码块中，不会替换，也无法在正文中定位", true);
      } else {
        toast("Markdown 正文中没有这个占位符，无法定位", true);
      }
      return;
    }

    state.activePlaceholder = item.placeholder;
    state.cardEntries.forEach(function (entry) {
      entry.card.classList.toggle(
        "active",
        entry.item && entry.item.placeholder === state.activePlaceholder
      );
    });

    var start = offsetForLineColumn(source.value, occurrence.line, occurrence.column);
    var end = start + item.placeholder.length;
    source.focus({ preventScroll: true });
    source.setSelectionRange(start, end);

    var totalLines = source.value.split(/\r\n|\r|\n/).length;
    var maxScroll = Math.max(0, source.scrollHeight - source.clientHeight);
    if (totalLines > 1 && maxScroll > 0) {
      var ratio = (occurrence.line - 1) / (totalLines - 1);
      source.scrollTop = Math.max(
        0,
        Math.min(maxScroll, ratio * maxScroll - source.clientHeight * 0.3)
      );
    }

    var pane = source.closest(".pane");
    if (pane) {
      pane.classList.add("flash");
      setTimeout(function () { pane.classList.remove("flash"); }, 900);
      pane.scrollIntoView({ behavior: "smooth", block: "center" });
    }

    if (card && card.scrollIntoView) {
      card.scrollIntoView({ block: "nearest" });
    }
  }

  function offsetForLineColumn(text, line, column) {
    var currentLine = 1;
    var index = 0;
    while (currentLine < line && index < text.length) {
      var character = text.charAt(index);
      if (character === "\r") {
        index += 1;
        if (text.charAt(index) === "\n") { index += 1; }
        currentLine += 1;
      } else if (character === "\n") {
        index += 1;
        currentLine += 1;
      } else {
        index += 1;
      }
    }
    return Math.min(text.length, index + Math.max(0, column - 1));
  }

  function generate() {
    if (!state.analysis || !state.analysis.can_generate) {
      toast("请先通过检查", true);
      return;
    }
    generateBtn.disabled = true;
    generateBtn.textContent = "正在生成…";
    postJson("/api/special-images/generate", payload())
      .then(function (response) {
        if (!response.ok) {
          var data = response.data || {};
          if (data.analysis || data.items) {
            state.analysis = data.analysis || data;
            if (data.final_check) { state.lastFinalCheck = data.final_check; }
            renderAnalysis();
          }
          throw new Error(data.error || "生成失败");
        }
        state.analysis = response.data.analysis || state.analysis;
        state.result = response.data;
        state.lastFinalCheck = response.data.final_check || null;
        renderAnalysis();
        showResult(response.data);
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
    notes.push("已替换 " + number(data.replaced_count) + " 个特殊占位符");
    if (data.skipped_code_count) {
      notes.push("代码块中跳过 " + data.skipped_code_count + " 个");
    }
    var check = data.final_check || {};
    notes.push(check.passed ? "最终占位符残留检查通过" : "最终占位符残留检查未通过");
    if ((data.warnings || []).length) {
      notes.push(data.warnings.join("；"));
    }
    resultNote.textContent = notes.join("；");
    downloadManifest.disabled = !data.updated_manifest;
    checkHint.textContent = "已生成修正后的 Markdown";
    show(resultPanel);
    resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function copyResultText() {
    if (!resultText.value) {
      toast("没有可复制的 Markdown", true);
      return;
    }
    navigator.clipboard.writeText(resultText.value).then(function () {
      toast("已复制修正后的 Markdown");
    }).catch(function (error) {
      toast("复制失败：" + (error.message || error), true);
    });
  }

  function applyToReader() {
    if (!state.result || !state.result.markdown) {
      toast("请先生成修正后的 Markdown", true);
      return;
    }
    state.applying = true;
    source.value = state.result.markdown;
    source.dispatchEvent(new Event("input", { bubbles: true }));
    state.applying = false;
    toast("已应用到阅读器，源码和预览已更新");
    if (state.manifest) { analyze(false); }
  }

  function baseName() {
    var name = document.getElementById("report-file").textContent || "document";
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

  function resetCheckState() {
    cancelAnalyze();
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = "重新检查";
    manifestFile.value = "";
    manifestName.textContent = MANIFEST_HINT;
    state.manifest = null;
    state.manifestFilename = "";
    state.urls = {};
    state.analysis = null;
    state.lastFinalCheck = null;
    state.listSignature = "";
    state.cardEntries = [];
    state.activePlaceholder = "";
    resetResult();
    specialList.innerHTML = "";
    var hint = document.createElement("p");
    hint.className = "empty-hint";
    hint.textContent = EMPTY_HINT;
    specialList.appendChild(hint);
    document.getElementById("count-special").textContent = "0";
    document.getElementById("count-in-markdown").textContent = "0";
    document.getElementById("count-pending").textContent = "0";
    checkSub.textContent = "导入 manifest 后，可检查并补齐 unsupported / oversized / conversion_failed 图片";
    renderMessages("error-list", []);
    renderMessages("warning-list", []);
    setIdleChecks();
    generateBtn.disabled = true;
    checkHint.textContent = "填写图片 URL 后会自动检查";
  }

  function applyManifest(parsed, label) {
    state.manifest = parsed;
    state.manifestFilename = label || "";
    state.urls = {};
    state.listSignature = "";
    resetResult();
    var count = parsed && Array.isArray(parsed.images) ? parsed.images.length : 0;
    manifestName.textContent = "已加载：" + (label || "manifest.json") +
      "（" + count + " 张图片，正在检查…）";
    if (source.value.trim()) {
      analyze(false);
    }
  }

  checkToggle.addEventListener("click", function () {
    var willOpen = checkPanel.classList.contains("hidden");
    checkPanel.classList.toggle("hidden");
    checkToggle.setAttribute("aria-expanded", willOpen ? "true" : "false");
    checkToggle.textContent = willOpen ? "收起检查" : "检查与修正";
    if (willOpen) {
      checkPanel.scrollIntoView({ behavior: "smooth", block: "start" });
      if (!state.manifest) {
        toast("导入 manifest.json 后即可检查特殊图片");
      } else if (source.value.trim()) {
        analyze(false);
      }
    }
  });

  manifestFile.addEventListener("change", function () {
    if (!manifestFile.files.length) { return; }
    var file = manifestFile.files[0];
    readTextFile(file, function (text) {
      var parsed;
      cancelAnalyze();
      try {
        parsed = JSON.parse(text);
      } catch (error) {
        toast("manifest.json 解析失败：" + (error.message || error), true);
        return;
      }
      applyManifest(parsed, file.name);
    });
  });

  source.addEventListener("input", function () {
    if (state.applying) { return; }
    resetResult();
    if (state.manifest) { scheduleAnalyze(); }
  });

  analyzeBtn.addEventListener("click", function () { analyze(true); });
  generateBtn.addEventListener("click", generate);
  clearCheckBtn.addEventListener("click", resetCheckState);
  copyResult.addEventListener("click", copyResultText);
  applyResult.addEventListener("click", applyToReader);

  downloadMd.addEventListener("click", function () {
    if (!resultText.value) {
      toast("请先生成修正后的 Markdown", true);
      return;
    }
    downloadText(baseName() + ".special.md", resultText.value, "text/markdown;charset=utf-8");
  });

  downloadManifest.addEventListener("click", function () {
    if (!state.result || !state.result.updated_manifest) {
      toast("没有可下载的 manifest", true);
      return;
    }
    downloadText(
      baseName() + ".manifest.special.json",
      JSON.stringify(state.result.updated_manifest, null, 2),
      "application/json;charset=utf-8"
    );
  });

  document.addEventListener("qt:reader-file-loaded", function () {
    resetCheckState();
    hide(checkPanel);
    checkToggle.setAttribute("aria-expanded", "false");
    checkToggle.textContent = "检查与修正";
  });

  var resetBtn = document.getElementById("reset-btn");
  if (resetBtn) {
    resetBtn.addEventListener("click", function () {
      resetCheckState();
      hide(checkPanel);
      checkToggle.setAttribute("aria-expanded", "false");
      checkToggle.textContent = "检查与修正";
    });
  }

  setIdleChecks();
})();
