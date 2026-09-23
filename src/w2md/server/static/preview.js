(function () {
  var tick = String.fromCharCode(96);

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
    var codeRe = new RegExp(tick + "([^" + tick + "]+)" + tick, "g");
    s = s.replace(codeRe, "<code>$1</code>");
    s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, '<img src="$2" alt="$1">');
    s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
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

  function isFence(line) {
    var t = line.trim().slice(0, 3);
    return t === tick + tick + tick || t === "~~~";
  }

  function renderFence(lines, start, container) {
    var opener = lines[start].trim();
    var marker = opener.slice(0, 3);
    var language = opener.slice(3).trim();
    var codeLines = [];
    var i = start + 1;
    while (i < lines.length && lines[i].trim().slice(0, 3) !== marker) {
      codeLines.push(lines[i]);
      i++;
    }
    if (i < lines.length) { i++; }

    var pre = document.createElement("pre");
    pre.className = "code-block";
    var code = document.createElement("code");
    if (language) { code.className = "language-" + language; }
    code.textContent = codeLines.join("\n");
    pre.appendChild(code);
    container.appendChild(pre);
    return i;
  }

  function isBlockquote(lines) {
    return lines.every(function (line) { return line.trim().indexOf(">") === 0; });
  }

  function createBlockquote(lines) {
    var blockquote = document.createElement("blockquote");
    var content = lines.map(function (line) {
      return line.trim().replace(/^>\s?/, "");
    }).join(" ");
    blockquote.innerHTML = inlineMd(content);
    return blockquote;
  }

  function listType(line) {
    if (/^[-*+]\s+/.test(line)) { return "ul"; }
    if (/^\d+\.\s+/.test(line)) { return "ol"; }
    return null;
  }

  function isList(lines) {
    if (!lines.length) { return false; }
    var type = listType(lines[0].trim());
    if (!type) { return false; }
    return lines.every(function (line) { return listType(line.trim()) === type; });
  }

  function createList(lines) {
    var type = listType(lines[0].trim());
    var list = document.createElement(type);
    for (var i = 0; i < lines.length; i++) {
      var text = lines[i].trim().replace(/^([-*+]|\d+\.)\s+/, "");
      var li = document.createElement("li");
      li.innerHTML = inlineMd(text);
      list.appendChild(li);
    }
    return list;
  }

  function createBlockElement(lines) {
    if (isTableBlock(lines)) {
      return createTableElement(lines);
    }
    var heading = lines[0].match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      var el = document.createElement("h" + heading[1].length);
      el.innerHTML = inlineMd(heading[2]);
      return el;
    }
    if (lines.length === 1 && lines[0].trim() === "---") {
      return document.createElement("hr");
    }
    if (isBlockquote(lines)) {
      return createBlockquote(lines);
    }
    if (isList(lines)) {
      return createList(lines);
    }
    var paragraph = document.createElement("p");
    paragraph.innerHTML = inlineMd(lines.join(" "));
    return paragraph;
  }

  function render(markdown, container) {
    container.innerHTML = "";
    var lines = markdown.split("\n");
    var i = 0;
    while (i < lines.length) {
      if (isFence(lines[i])) {
        i = renderFence(lines, i, container);
        continue;
      }
      while (i < lines.length && lines[i].trim() === "") { i++; }
      if (i >= lines.length) { break; }
      var blockLines = [];
      while (i < lines.length && lines[i].trim() !== "") {
        blockLines.push(lines[i]);
        i++;
      }
      var el = createBlockElement(blockLines);
      if (el) { container.appendChild(el); }
    }
  }

  window.QuickPreview = { render: render };
})();
