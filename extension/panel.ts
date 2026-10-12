import { mount, unmount } from "svelte";
import App from "./App.svelte";
import { loadDevSettings } from "./dev-settings";
import "./panel.css";

async function startPanel() {
	await loadDevSettings();

	const app = mount(App, { target: document.getElementById("app")! });

	window.addEventListener("pagehide", () => void unmount(app), { once: true });
}

void startPanel();
