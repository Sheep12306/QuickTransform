(function () {
  function friendlyError(status, text) {
    var hint = "";
    if (status === 413) {
      hint = "上传文件超过服务器大小限制";
    } else if (status === 502 || status === 504) {
      hint = "后端服务不可用或处理超时";
    } else if (status === 404) {
      hint = "接口不存在或部署未完成";
    }
    var plain = String(text || "")
      .replace(/<[^>]*>/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 180);
    return new Error(
      "服务器返回 " + status +
      (hint ? "（" + hint + "）" : "") +
      "：" + plain
    );
  }

  function qtParseApiResponse(response) {
    var contentType = (response.headers.get("Content-Type") || "").toLowerCase();
    if (contentType.indexOf("application/json") >= 0) {
      return response.json();
    }
    return response.text().then(function (text) {
      throw friendlyError(response.status, text);
    });
  }

  function qtParseXhrResponse(xhr) {
    var contentType = (xhr.getResponseHeader("Content-Type") || "").toLowerCase();
    var text = xhr.responseText || "";
    if (contentType.indexOf("application/json") >= 0) {
      try {
        return JSON.parse(text || "{}");
      } catch (error) {
        throw friendlyError(xhr.status, text);
      }
    }
    throw friendlyError(xhr.status, text);
  }

  window.qtParseApiResponse = qtParseApiResponse;
  window.qtParseXhrResponse = qtParseXhrResponse;
})();
