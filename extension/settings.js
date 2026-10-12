import {SUPPORTED_MODELS} from "./model-catalog.js";
import {fetchModels, ModelListError} from "./models.js";
import {mountModelPicker} from "./model-picker.js";

const DEFAULT_MODEL = SUPPORTED_MODELS[0].id;

async function restrictStorage() {
  await chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
  await chrome.storage.session.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
}

export async function getSettings() {
  await restrictStorage();
  const local = await chrome.storage.local.get(["connection", "apiKey", "model"]);
  const session = await chrome.storage.session.get(["connection", "apiKey"]);
  const connection = session.connection || local.connection;
  if (connection) {
    return {
      ...connection,
      model: connection.verifiedAt ? connection.model : DEFAULT_MODEL,
      remember: !session.connection,
    };
  }
  // Keep legacy keys, but discard unverified model preferences so setup uses the current default.
  return {
    apiKey: session.apiKey || local.apiKey || "",
    model: DEFAULT_MODEL,
    remember: Boolean(local.apiKey),
    verifiedAt: null,
  };
}

async function saveSettings({apiKey, model, remember, verifiedAt}) {
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

async function clearKey() {
  await restrictStorage();
  await chrome.storage.session.remove(["connection", "apiKey"]);
  await chrome.storage.local.remove(["connection", "apiKey", "model"]);
}

export async function mountSettings(root, testConnection) {
  const main = root.querySelector("main");
  const form = root.querySelector("#api-settings");
  const key = root.querySelector("#api-key");
  const model = root.querySelector("#api-model");
  const remember = root.querySelector("#remember-key");
  const submit = root.querySelector("#test-connection");
  const feedback = root.querySelector("#settings-status");
  let saved = {apiKey: "", model: DEFAULT_MODEL};
  let editing = true;
  let testing = false;

  let availableModels = [...SUPPORTED_MODELS];
  let loadedForKey = "";
  let loadedAt = 0;
  let discovery = null;
  let discoveryTimer = null;
  const modelStatus = root.querySelector("#model-discovery-status");
  const refreshButton = root.querySelector("#refresh-models");
  const modelPicker = mountModelPicker(root, availableModels, () => { refreshModels(); });

  function resetModels() {
    clearTimeout(discoveryTimer);
    discovery?.abort();
    discovery = null;
    loadedForKey = "";
    availableModels = [...SUPPORTED_MODELS];
    preserveSelection();
    modelStatus.textContent = "Supported models · enter your key to check account availability.";
  }

  function preserveSelection() {
    if (!availableModels.some(item => item.id === model.value)) {
      // Keep an existing selection visible without growing the menu past fifteen choices.
      availableModels = availableModels.slice(0, 14);
      availableModels.push({
        id: model.value, name: SUPPORTED_MODELS.find(item => item.id === model.value)?.name || model.value,
        note: "Not listed for this key. Test the connection to check access.",
      });
    }
    modelPicker.setModels(availableModels);
  }

  async function refreshModels(force = false) {
    const apiKey = key.value.trim();
    const cached = loadedForKey === apiKey && Date.now() - loadedAt < 300000;
    clearTimeout(discoveryTimer);
    if (!apiKey || testing || (!force && cached) || discovery) return;
    const controller = new AbortController();
    discovery = controller;
    refreshButton.disabled = true;
    modelStatus.textContent = "Loading available models…";
    try {
      const items = await fetchModels(apiKey, controller.signal);
      if (controller.signal.aborted || key.value.trim() !== apiKey) return;
      availableModels = items.map(item => ({
        ...item,
        name: SUPPORTED_MODELS.find(fallback => fallback.id === item.id)?.name || item.name,
      }));
      availableModels.sort((a, b) => Number(b.id === DEFAULT_MODEL) - Number(a.id === DEFAULT_MODEL));
      preserveSelection();
      loadedForKey = apiKey;
      loadedAt = Date.now();
      modelStatus.textContent = items.length ?
        `${items.length} account models loaded · default first, then newest.` :
        "No supported models found for this key. Check project access or refresh.";
      update();
    } catch (error) {
      if (!controller.signal.aborted) {
        modelStatus.textContent = error instanceof ModelListError ? error.message :
          "Could not reach the model list. Check your connection and refresh.";
      }
    } finally {
      if (discovery === controller) discovery = null;
      refreshButton.disabled = testing || Boolean(discovery) || !key.value.trim();
    }
  }

  function selectedModel() {
    return model.value;
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
    refreshButton.disabled = testing || Boolean(discovery) || !key.value.trim();
    if (testing) modelPicker.close();
    submit.disabled = testing || !key.value.trim() || !selectedModel();
    const modelNote = availableModels.find(item => item.id === model.value)?.note;
    root.querySelector("#model-note").textContent = modelNote || "Test to verify model compatibility.";
    root.dispatchEvent(new Event("connectionchange"));
  }

  function fillDraft() {
    key.value = saved.apiKey;
    key.type = "password";
    root.querySelector("#reveal-key").setAttribute("aria-label", "Show API key");
    modelPicker.setValue(saved.model || DEFAULT_MODEL);
    preserveSelection();
    remember.checked = Boolean(saved.remember);
    feedback.hidden = true;
  }

  function openEditor() {
    if (testing) return;
    if (!editing) fillDraft();
    editing = true;
    refreshModels();
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
    else {
      update();
      refreshModels();
    }
  } catch {
    feedback.hidden = false;
    feedback.textContent = "Could not load settings. Reload the extension.";
    update();
  }

  for (const field of [key, model, remember]) {
    field.addEventListener("input", () => { feedback.hidden = true; update(); });
  }
  key.addEventListener("input", () => {
    resetModels();
    update();
    if (key.value.trim()) discoveryTimer = setTimeout(() => { refreshModels(); }, 600);
  });
  key.addEventListener("blur", () => { refreshModels(); });
  refreshButton.addEventListener("click", () => { refreshModels(true); });
  root.querySelector("#reveal-key").addEventListener("click", event => {
    key.type = key.type === "password" ? "text" : "password";
    event.currentTarget.setAttribute("aria-label", key.type === "password" ? "Show API key" : "Hide API key");
  });
  for (const id of ["settings-toggle", "edit-connection"]) {
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
    clearTimeout(discoveryTimer);
    discovery?.abort();
    discovery = null;
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
    resetModels();
    fillDraft();
    openEditor();
  });
}
