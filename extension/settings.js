import {mountModelPicker} from "./model-picker.js";

export const DEFAULT_MODEL = "gpt-4.1-mini";
// Keep the picker small; custom IDs still have to pass the same connection test.
export const SUPPORTED_MODELS = [
  {id: DEFAULT_MODEL, name: "GPT-4.1 mini", note: "Fast and affordable for grouping tabs."},
  {id: "gpt-4.1", name: "GPT-4.1", note: "More capable for complex topics."},
];

async function restrictStorage() {
  await chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
  await chrome.storage.session.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
}

export async function getSettings() {
  await restrictStorage();
  const local = await chrome.storage.local.get(["connection", "apiKey", "model"]);
  const session = await chrome.storage.session.get(["connection", "apiKey"]);
  const connection = session.connection || local.connection;
  if (connection) return {...connection, remember: !session.connection};
  // Previously saved keys remain available, but must be verified before use.
  return {
    apiKey: session.apiKey || local.apiKey || "",
    model: local.model || DEFAULT_MODEL,
    remember: Boolean(local.apiKey),
    verifiedAt: null,
  };
}

export async function saveSettings({apiKey, model, remember, verifiedAt}) {
  await restrictStorage();
  if (!apiKey || !verifiedAt) throw new Error("Test the connection before saving it.");
  const connection = {apiKey, model, verifiedAt};
  const target = remember ? chrome.storage.local : chrome.storage.session;
  const other = remember ? chrome.storage.session : chrome.storage.local;
  // One record keeps the tested key, model, and verification time together.
  await target.set({connection});
  await other.remove("connection");
  await chrome.storage.session.remove("apiKey");
  await chrome.storage.local.remove(["apiKey", "model"]);
}

export async function clearKey() {
  await restrictStorage();
  await chrome.storage.session.remove(["connection", "apiKey"]);
  await chrome.storage.local.remove(["connection", "apiKey", "model"]);
}

export async function mountSettings(root, testConnection) {
  const main = root.querySelector("main");
  const form = root.querySelector("#api-settings");
  const key = root.querySelector("#api-key");
  const model = root.querySelector("#api-model");
  const custom = root.querySelector("#custom-model");
  const remember = root.querySelector("#remember-key");
  const submit = root.querySelector("#test-connection");
  const feedback = root.querySelector("#settings-status");
  let saved = {apiKey: "", model: DEFAULT_MODEL};
  let editing = true;
  let testing = false;

  const modelPicker = mountModelPicker(root, SUPPORTED_MODELS);

  function selectedModel() {
    return custom.value.trim() || model.value;
  }

  function update() {
    const connected = Boolean(saved.apiKey && saved.verifiedAt) && !editing;
    main.dataset.connected = String(connected);
    form.hidden = !editing;
    root.querySelector("#ready").hidden = !connected;
    root.querySelector("#connection-actions").hidden = !saved.apiKey;
    root.querySelector("#cancel-settings").hidden = !editing || !saved.verifiedAt;
    root.querySelector("#badge").textContent = connected ? "✓ Connection verified" : "One-time setup";
    root.querySelector("#badge").classList.toggle("verified", connected);
    root.querySelector("#heading").textContent = connected ? "Less clutter. More focus." : "Connect your AI";
    root.querySelector("#intro").textContent = connected ? "Group your tabs by topic." :
      "Add an OpenAI API key to get started.";
    root.querySelector("#key-label").textContent = saved.apiKey ? "Replace key" : "OpenAI API key";
    root.querySelector("#cancel-settings").disabled = testing;
    form.setAttribute("aria-busy", String(testing));
    model.disabled = Boolean(custom.value.trim());
    if (testing || model.disabled) modelPicker.close();
    submit.disabled = testing || !key.value.trim() || !selectedModel();
    root.querySelector("#model-note").textContent = custom.value.trim() ?
      "Custom models must support structured outputs." : SUPPORTED_MODELS.find(item => item.id === model.value).note;
    root.dispatchEvent(new Event("connectionchange"));
  }

  function fillDraft() {
    key.value = saved.apiKey;
    key.type = "password";
    root.querySelector("#reveal-key").setAttribute("aria-label", "Show API key");
    const modelId = SUPPORTED_MODELS.some(item => item.id === saved.model) ? saved.model : DEFAULT_MODEL;
    modelPicker.setValue(modelId);
    custom.value = model.value === saved.model ? "" : saved.model;
    root.querySelector("#advanced").open = Boolean(custom.value);
    remember.checked = Boolean(saved.remember);
    feedback.hidden = true;
  }

  function openEditor() {
    if (testing) return;
    if (!editing) fillDraft();
    editing = true;
    update();
    key.focus();
  }

  function showSaved() {
    editing = false;
    key.value = "";
    const label = SUPPORTED_MODELS.find(item => item.id === saved.model)?.name || saved.model;
    const storageLabel = saved.remember ? "Remembered on this device" : "Session only";
    root.querySelector("#connection-detail").textContent = `${label} · ${storageLabel}`;
    const time = new Date(saved.verifiedAt);
    const verified = root.querySelector("#verified-time");
    verified.textContent = "Last tested just now";
    verified.dateTime = time.toISOString();
    verified.title = time.toLocaleString();
    if (Date.now() - time.getTime() > 60000) verified.textContent = `Last tested ${time.toLocaleString()}`;
    update();
  }

  try {
    saved = await getSettings();
    fillDraft();
    if (saved.apiKey && saved.verifiedAt) showSaved();
    else update();
  } catch {
    feedback.hidden = false;
    feedback.textContent = "Could not load settings. Reload the extension.";
    update();
  }

  for (const field of [key, model, custom, remember]) {
    field.addEventListener("input", () => { feedback.hidden = true; update(); });
  }
  root.querySelector("#reveal-key").addEventListener("click", event => {
    key.type = key.type === "password" ? "text" : "password";
    event.currentTarget.setAttribute("aria-label", key.type === "password" ? "Show API key" : "Hide API key");
  });
  for (const id of ["settings-toggle", "edit-connection", "manage-connection"]) {
    root.querySelector(`#${id}`).addEventListener("click", openEditor);
  }
  root.querySelector("#cancel-settings").addEventListener("click", showSaved);

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (testing || !key.value.trim()) return;
    const draft = {apiKey: key.value.trim(), model: selectedModel(), remember: remember.checked};
    if (/[\r\n]/.test(draft.apiKey) || !/^[a-zA-Z0-9._:-]{1,100}$/.test(draft.model)) {
      feedback.hidden = false;
      feedback.textContent = "Enter a valid key and model ID.";
      return;
    }
    testing = true;
    root.querySelector("#settings-fields").disabled = true;
    root.querySelector("#settings-toggle").disabled = true;
    root.querySelector("#connection-actions").inert = true;
    submit.classList.add("testing");
    root.querySelector("#test-label").textContent = "Testing connection…";
    feedback.hidden = false;
    feedback.className = "feedback checking";
    feedback.replaceChildren();
    const message = document.createElement("span");
    message.textContent = "Checking model access…";
    const note = document.createElement("small");
    note.textContent = "Your tabs are not sent during this test.";
    feedback.append(message, note);
    update();
    try {
      await testConnection(draft);
      draft.verifiedAt = new Date().toISOString();
      await saveSettings(draft);
      saved = draft;
      feedback.hidden = true;
      showSaved();
    } catch (error) {
      feedback.className = `feedback ${error.kind || "invalid"}`;
      feedback.replaceChildren();
      const message = document.createElement("span");
      message.textContent = error.kind ? error.message :
        "Could not verify the response. Retry or choose another model.";
      const note = document.createElement("small");
      note.textContent = saved.verifiedAt ? "Your previous connection is still saved." :
        "Your connection has not been saved.";
      const action = document.createElement(error.kind === "billing" ? "a" : "button");
      action.textContent = error.action || "Retry";
      if (error.kind === "billing") {
        action.href = "https://platform.openai.com/settings/organization/billing/overview";
        action.target = "_blank";
        action.rel = "noreferrer";
      } else {
        action.type = "button";
        action.className = "text-button";
        action.addEventListener("click", () => {
          if (error.kind === "auth") key.focus();
          else if (error.kind === "model") model.focus();
          else form.requestSubmit();
        });
      }
      feedback.append(message, note, action);
    } finally {
      testing = false;
      root.querySelector("#settings-fields").disabled = false;
      root.querySelector("#settings-toggle").disabled = false;
      root.querySelector("#connection-actions").inert = false;
      submit.classList.remove("testing");
      root.querySelector("#test-label").textContent = "Test & save connection";
      update();
    }
  });

  root.querySelector("#forget-key").addEventListener("click", async () => {
    if (testing) return;
    await clearKey();
    saved = {apiKey: "", model: DEFAULT_MODEL};
    fillDraft();
    openEditor();
  });
}
