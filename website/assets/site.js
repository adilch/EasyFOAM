// Gallery: show only the tutorials on the chosen topic.
(function () {
  var buttons = document.querySelectorAll(".filter");
  if (!buttons.length) return;
  var cards = document.querySelectorAll(".card");
  var empty = document.querySelector(".empty");
  function show(topic) {
    var shown = 0;
    cards.forEach(function (card) {
      var match = !topic || card.dataset.topics.split("|").indexOf(topic) >= 0;
      card.hidden = !match;
      if (match) shown += 1;
    });
    if (empty) empty.hidden = shown > 0;
    buttons.forEach(function (button) {
      button.classList.toggle("on", button.dataset.topic === topic);
    });
  }
  buttons.forEach(function (button) {
    button.addEventListener("click", function () { show(button.dataset.topic); });
  });
})();

// Tutorial pages: click a picture to see it full size.
(function () {
  var box = document.querySelector(".lightbox");
  if (!box) return;
  var picture = box.querySelector("img");
  document.querySelectorAll("a.zoom").forEach(function (link) {
    link.addEventListener("click", function (event) {
      event.preventDefault();
      picture.src = link.getAttribute("href");
      box.hidden = false;
    });
  });
  function close() { box.hidden = true; picture.removeAttribute("src"); }
  box.addEventListener("click", close);
  document.addEventListener("keydown", function (event) { if (event.key === "Escape") close(); });
})();

// Tutorial pages: mark the step being read in the list on the left.
(function () {
  var links = document.querySelectorAll(".contents li a");
  if (!links.length || !("IntersectionObserver" in window)) return;
  var byId = {};
  links.forEach(function (link) { byId[link.getAttribute("href").slice(1)] = link; });
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      if (!entry.isIntersecting) return;
      links.forEach(function (link) { link.classList.remove("here"); });
      var link = byId[entry.target.id];
      if (link) link.classList.add("here");
    });
  }, { rootMargin: "-80px 0px -65% 0px" });
  document.querySelectorAll("section.step").forEach(function (section) { observer.observe(section); });
})();
