(function () {
  let p = document.getElementById("autoglm-main-content");
  if (p) {
    let shadowRoot = p.shadowRoot;
    let floatBallContainer = shadowRoot.getElementById("autoglm-float-ball-container");
    let button = floatBallContainer.querySelector("button");

    if (button) {
      simulateMouseClick = (element, button = "left") => {
        if (element) {
          // 创建并触发 mousedown 事件
          const mousedownEvent = new MouseEvent("mousedown", {
            bubbles: true,
            cancelable: true,
            view: window,
            button: button === "right" ? 2 : 0,
          });
          element.dispatchEvent(mousedownEvent);

          // 创建并触发 mouseup 事件
          const mouseupEvent = new MouseEvent("mouseup", {
            bubbles: true,
            cancelable: true,
            view: window,
            button: button === "right" ? 2 : 0,
          });
          element.dispatchEvent(mouseupEvent);

          // 创建并触发 click 事件
          const clickEvent = new MouseEvent("click", {
            bubbles: true,
            cancelable: true,
            view: window,
            button: button === "right" ? 2 : 0,
          });
          element.dispatchEvent(clickEvent);
        }
      }
      simulateMouseClick(button, "left");
      console.log("Simulated click on the side panel button.", button);
    }
  }
})();