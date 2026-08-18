(function () {
  // 保存原始的 window.open 方法
  const originalWindowOpen = window.open;

  // 重写 window.open 方法
  window.open = function (url, target, features) {
    // 获取当前活动标签页的信息
    console.log("window.open: ", url, target, features);
    if (target === "_blank" || target === "" || !target) {
      // 如果目标是新页面或空（默认新页面），则发送消息给后台脚本进行处理
      // chrome.runtime.sendMessage({ action: 'redirect', url: url });

      // 返回 null 以阻止新页面的打开
      // window.location.href = url;
      window.wanFangDataUrl = url;
      return null;
    } else {
      // 否则，使用原始的 window.open 方法
      return originalWindowOpen.apply(this, arguments);
    }
  };
})();
