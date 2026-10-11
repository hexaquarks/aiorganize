// Render the menu inside the panel so Chrome does not open a separate native macOS menu.
export function mountModelPicker(root, models, onOpen = () => {}) {
  const trigger = root.querySelector("#api-model");
  const list = root.querySelector("#model-options");
  const picker = root.querySelector("#model-picker");
  const label = root.querySelector("#selected-model");
  let options = [];
  let rebuilding = false;

  function setModels(items) {
    // Refreshing an open list replaces its focused option; keep the menu and focus in place.
    const focused = list.contains(document.activeElement);
    const expanded = !list.hidden;
    rebuilding = true;
    const value = trigger.value || items[0].id;
    models = items;
    list.replaceChildren();
    options = models.map(model => {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "model-option";
      option.setAttribute("role", "option");
      option.setAttribute("aria-label", model.name);
      option.tabIndex = -1;
      option.textContent = model.name;
      option.dataset.value = model.id;
      option.addEventListener("click", () => {
        setValue(model.id);
        close();
        trigger.focus();
        trigger.dispatchEvent(new Event("input", {bubbles: true}));
      });
      list.append(option);
      return option;
    });
    setValue(value);
    list.hidden = !expanded;
    trigger.setAttribute("aria-expanded", String(expanded));
    if (focused) options.find(option => option.dataset.value === value)?.focus();
    rebuilding = false;
  }

  function setValue(value) {
    trigger.value = value;
    label.textContent = models.find(model => model.id === value)?.name || value;
    for (const option of options) {
      option.setAttribute("aria-selected", String(option.dataset.value === value));
    }
  }

  function close() {
    list.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
  }

  function open(index = options.findIndex(option => option.dataset.value === trigger.value)) {
    if (trigger.matches(":disabled")) return;
    list.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    options[Math.max(0, index)].focus();
    options[Math.max(0, index)].scrollIntoView({block: "nearest"});
    onOpen();
  }

  trigger.addEventListener("click", () => list.hidden ? open() : close());
  trigger.addEventListener("keydown", event => {
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      open(event.key === "Home" ? 0 : event.key === "End" ? options.length - 1 : undefined);
    }
  });
  list.addEventListener("keydown", event => {
    const index = options.indexOf(document.activeElement);
    let next;
    if (event.key === "ArrowDown") next = (index + 1) % options.length;
    if (event.key === "ArrowUp") next = (index + options.length - 1) % options.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = options.length - 1;
    if (next !== undefined) {
      event.preventDefault();
      options[next].focus();
      options[next].scrollIntoView({block: "nearest"});
    } else if (event.key === "Escape") {
      event.preventDefault();
      close();
      trigger.focus();
    } else if (event.key === "Tab") {
      // Return focus to the trigger so Tab continues through the form in order.
      close();
      trigger.focus();
    }
  });
  root.addEventListener("click", event => {
    if (!picker.contains(event.target)) close();
  });
  picker.addEventListener("focusout", event => {
    if (!rebuilding && !picker.contains(event.relatedTarget)) close();
  });

  setModels(models);
  return {setValue, setModels, close};
}
