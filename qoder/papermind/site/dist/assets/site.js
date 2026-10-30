(function () {
  var doc = document;
  doc.documentElement.classList.add("js");

  function onReady(fn) {
    if (doc.readyState === "loading") {
      doc.addEventListener("DOMContentLoaded", fn);
    } else {
      fn();
    }
  }

  onReady(function () {
    var copyBtn = doc.querySelector("[data-copy]");
    var codeEl = doc.getElementById("run-code");
    if (copyBtn && codeEl && navigator.clipboard) {
      copyBtn.addEventListener("click", function () {
        var text = codeEl.textContent.replace(/\u00a0/g, " ");
        navigator.clipboard.writeText(text).then(
          function () {
            copyBtn.textContent = "已复制";
            setTimeout(function () { copyBtn.textContent = "复制"; }, 1600);
          },
          function () {
            copyBtn.textContent = "复制失败";
            setTimeout(function () { copyBtn.textContent = "复制"; }, 1600);
          }
        );
      });
    } else if (copyBtn) {
      copyBtn.hidden = true;
    }
  });
})();
