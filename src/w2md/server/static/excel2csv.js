(function () {
  var dropzone = document.getElementById("dropzone");
  var fileInput = document.getElementById("file-input");
  var dropPanel = document.getElementById("drop-panel");
  var statusPanel = document.getElementById("status-panel");
  var result = document.getElementById("result");
  var statusText = document.getElementById("status-text");
  var reportFile = document.getElementById("report-file");
  var sheetTabs = document.getElementById("sheet-tabs");
  var dataTable = document.getElementById("data-table");
  var downloadBtn = document.getElementById("download-btn");
  var zipBtn = document.getElementById("zip-btn");
  var resetBtn = document.getElementById("reset-btn");

  var current = { filename: "", sheets: [], zipUrl: "", activeIndex: 0 };

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

  function renderTable(rows) {
    dataTable.innerHTML = "";
    if (!rows.length) {
      var empty = document.createElement("p");
      empty.textContent = "该工作表没有数据";
      document.getElementById("table-wrap").appendChild(empty);
      return;
    }
    var thead = document.createElement("thead");
    var headRow = document.createElement("tr");
    var first = rows[0] || [];
    for (var c = 0; c < first.length; c++) {
      var th = document.createElement("th");
      th.textContent = first[c] === null || first[c] === undefined ? "" : String(first[c]);
      headRow.appendChild(th);
    }
    thead.appendChild(headRow);
    dataTable.appendChild(thead);

    var tbody = document.createElement("tbody");
    for (var r = 1; r < rows.length; r++) {
      var tr = document.createElement("tr");
      for (var c2 = 0; c2 < first.length; c2++) {
        var td = document.createElement("td");
        var value = rows[r][c2];
        td.textContent = value === null || value === undefined ? "" : String(value);
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
    dataTable.appendChild(tbody);
  }

  function renderSheets() {
    sheetTabs.innerHTML = "";
    for (var i = 0; i < current.sheets.length; i++) {
      (function (index) {
        var button = document.createElement("button");
        button.className = "sheet-tab" + (index === current.activeIndex ? " active" : "");
        button.textContent = current.sheets[index].name;
        button.addEventListener("click", function () {
          current.activeIndex = index;
          renderSheets();
        });
        sheetTabs.appendChild(button);
      })(i);
    }
    var sheet = current.sheets[current.activeIndex];
    if (sheet) { renderTable(sheet.preview || []); }
  }

  function reset() {
    current = { filename: "", sheets: [], zipUrl: "", activeIndex: 0 };
    sheetTabs.innerHTML = "";
    dataTable.innerHTML = "";
    hide(result);
    hide(statusPanel);
    hideError();
    show(dropPanel);
  }

  function convertFile(file) {
    show(statusPanel);
    hide(dropPanel);
    hide(result);
    statusText.textContent = "正在转换 " + file.name + " …";

    fetch("/api/excel2csv/convert?filename=" + encodeURIComponent(file.name), {
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
      current.sheets = res.data.sheets || [];
      current.zipUrl = res.data.zip_url || "";
      current.activeIndex = 0;
      reportFile.textContent = res.data.filename;
      renderSheets();
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
    var sheet = current.sheets[current.activeIndex];
    if (!sheet) { return; }
    var anchor = document.createElement("a");
    anchor.href = sheet.csv_url;
    anchor.download = sheet.name + ".csv";
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
  });

  zipBtn.addEventListener("click", function () {
    if (!current.zipUrl) { return; }
    var anchor = document.createElement("a");
    anchor.href = current.zipUrl;
    anchor.download = (current.filename.replace(/\.xlsx$/i, "") || "excel") + "-csv.zip";
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
  });

  resetBtn.addEventListener("click", reset);
})();
