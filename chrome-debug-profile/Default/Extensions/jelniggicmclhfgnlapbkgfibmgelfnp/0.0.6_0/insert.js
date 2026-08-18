console.log("insert.js loaded");
console.log(window.__basement_public_path__);

window.onload = function () {
  const viewportWidth = Math.max(
    document.documentElement.clientWidth || 0,
    window.innerWidth || 0,
  );
  console.log("viewportWidth: ", viewportWidth);
  const viewportHeight = Math.max(
    document.documentElement.clientHeight || 0,
    window.innerHeight || 0,
  );
  console.log("viewportWidth: ", viewportHeight);
  // 存储当前视口可见的 HTML 信息
  let visibleHTML = "";

  // 遍历当前视口的所有坐标点
  for (let x = 0; x < viewportWidth; x += 10) {
    for (let y = 0; y < viewportHeight; y += 10) {
      // 获取当前坐标点处的元素
      const element = document.elementFromPoint(x, y);
      if (element) {
        // 将元素的 HTML 内容添加到可见 HTML 信息中
        visibleHTML += element.outerHTML;
      }
    }
  }

  // 打印当前视口可见的 HTML 信息
  console.log("visibleHTML: ", visibleHTML);

  const promptTextarea = document.getElementById("prompt-textarea");

  console.log("promptTextarea: ", promptTextarea);
};
