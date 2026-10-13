import { mount, unmount } from "svelte";
import App from "./App.svelte";
import { removeLegacyDatabaseCredentials } from "./settings";
import "./panel.css";

async function startPanel() {
	await removeLegacyDatabaseCredentials();

	const app = mount(App, { target: document.getElementById("app")! });

	window.addEventListener("pagehide", () => void unmount(app), { once: true });
}

void startPanel();
