import {mountPanel} from "./panel.js";
import {mountSettings} from "./settings.js";

let propose;
// Only the unpacked development build has nativeMessaging and the companion module.
if (chrome.runtime.getManifest().permissions.includes("nativeMessaging")) {
  const {developmentCompanion} = await chrome.storage.local.get("developmentCompanion");
  if (developmentCompanion) propose = (await import("./companion-client.js")).requestProposal;
}
export const panel = mountPanel(document, propose);
await mountSettings(document);
