(function () {
  function qtParseApiResponse(response) {
    var contentType = (response.headers.get("Content-Type") || "").toLowerCase();
    if (contentType.indexOf("application/json") >= 0) {
      return response.json();
    }
    return response.text().then(function (text) {
      var hint = "";
      if (response.status === 413) {
        hint = "上传文件超过服务器大小限制";
      } else if (response.status === 502 || response.status === 504) {
        hint = "后端服务不可用或处理超时";
      } else if (response.status === 404) {
        hint = "接口不存在或部署未完成";
      }
      var plain = String(text || "")
        .replace(/<[^>]*>/g, " ")
        .replace(/\s+/g, " ")
        .trim()
        .slice(0, 180);
      throw new Error(
        "服务器返回 " + response.status +
        (hint ? "（" + hint + "）" : "") +
        "：" + plain
      );
    });
  }

  window.qtParseApiResponse = qtParseApiResponse;
})();
