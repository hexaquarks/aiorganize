const DEFAULT_MODEL = "gpt-4.1-mini";

async function restrictStorage() {
  // Page scripts must never be able to read stored credentials.
  await chrome.storage.local.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
  await chrome.storage.session.setAccessLevel({accessLevel: "TRUSTED_CONTEXTS"});
}

export async function getSettings() {
  await restrictStorage();
  const local = await chrome.storage.local.get(["apiKey", "model"]);
  const session = await chrome.storage.session.get("apiKey");
  return {
    apiKey: session.apiKey || local.apiKey || "",
    model: local.model || DEFAULT_MODEL,
    remember: Boolean(local.apiKey),
  };
}

export async function saveSettings({apiKey, model, remember}) {
  await restrictStorage();
  const previous = await getSettings();
  const key = apiKey.trim() || previous.apiKey;
  const selectedModel = model.trim() || DEFAULT_MODEL;
  if (!key || /[\r\n]/.test(key)) throw new Error("Enter a valid API key.");
  if (!/^[a-zA-Z0-9._:-]{1,100}$/.test(selectedModel)) throw new Error("Enter a valid OpenAI model name.");
  await chrome.storage.session.set({apiKey: key});
  await chrome.storage.local.set({model: selectedModel});
  if (remember) await chrome.storage.local.set({apiKey: key});
  else await chrome.storage.local.remove("apiKey");
}

export async function clearKey() {
  await chrome.storage.session.remove("apiKey");
  await chrome.storage.local.remove("apiKey");
}

export async function mountSettings(root) {
  const form = root.querySelector("#api-settings");
  const key = root.querySelector("#api-key");
  const model = root.querySelector("#api-model");
  const remember = root.querySelector("#remember-key");
  const status = root.querySelector("#settings-status");

  try {
    const settings = await getSettings();
    model.value = settings.model;
    remember.checked = settings.remember;
    key.placeholder = settings.apiKey ? "Key configured; enter a new key to replace" : "Your OpenAI API key";
  } catch {
    status.textContent = "Could not load API settings. Reload the extension.";
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    try {
      await saveSettings({apiKey: key.value, model: model.value, remember: remember.checked});
      key.value = "";
      key.placeholder = "Key configured; enter a new key to replace";
      status.textContent = remember.checked ? "Key saved on this device." : "Key saved for this browser session.";
    } catch (error) {
      status.textContent = error.message;
    }
  });
  root.querySelector("#forget-key").addEventListener("click", async () => {
    try {
      await clearKey();
      key.value = "";
      key.placeholder = "Your OpenAI API key";
      remember.checked = false;
      status.textContent = "API key removed.";
    } catch {
      status.textContent = "Could not remove the key. Reload the extension and retry.";
    }
  });
}
