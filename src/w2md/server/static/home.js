(function () {
  var glow = document.getElementById("mouseGlow");
  var mouseX = 0;
  var mouseY = 0;
  var glowX = 0;
  var glowY = 0;

  document.addEventListener("mousemove", function (event) {
    mouseX = event.clientX;
    mouseY = event.clientY;
    glow.classList.add("active");
  });

  document.addEventListener("mouseleave", function () {
    glow.classList.remove("active");
  });

  function animateGlow() {
    glowX += (mouseX - glowX) * 0.08;
    glowY += (mouseY - glowY) * 0.08;
    glow.style.left = glowX + "px";
    glow.style.top = glowY + "px";
    requestAnimationFrame(animateGlow);
  }
  animateGlow();

  function createRipple(event, container, card, soft) {
    var rect = card.getBoundingClientRect();
    var x = event.clientX - rect.left;
    var y = event.clientY - rect.top;
    var size = Math.max(rect.width, rect.height) * 0.65;

    var ripple = document.createElement("span");
    ripple.className = "ripple";
    ripple.style.width = size + "px";
    ripple.style.height = size + "px";
    ripple.style.left = (x - size / 2) + "px";
    ripple.style.top = (y - size / 2) + "px";
    if (soft) {
      ripple.style.background = "radial-gradient(circle, rgba(180, 220, 195, 0.32) 0%, rgba(200, 230, 210, 0.12) 50%, transparent 70%)";
      ripple.style.animationDuration = "1s";
    }
    container.appendChild(ripple);
    ripple.addEventListener("animationend", function () { ripple.remove(); });
  }

  var cards = document.querySelectorAll("[data-card]");
  for (var i = 0; i < cards.length; i++) {
    (function (card) {
      var container = card.querySelector(".ripple-container");
      card.addEventListener("mouseenter", function (event) {
        createRipple(event, container, card, false);
      });
      var lastRipple = 0;
      card.addEventListener("mousemove", function (event) {
        var now = Date.now();
        if (now - lastRipple > 380) {
          createRipple(event, container, card, true);
          lastRipple = now;
        }
      });
    })(cards[i]);
  }

  var blobs = document.querySelectorAll(".fluid-blob");
  document.addEventListener("mousemove", function (event) {
    var cx = (event.clientX / window.innerWidth - 0.5) * 22;
    var cy = (event.clientY / window.innerHeight - 0.5) * 22;
    for (var j = 0; j < blobs.length; j++) {
      var factor = (j + 1) * 0.22;
      blobs[j].style.transform = "translate(" + (cx * factor) + "px, " + (cy * factor) + "px)";
    }
  });
})();
