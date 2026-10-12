import { mount, unmount } from "svelte";
import App from "./App.svelte";
import "./panel.css";

const app = mount(App, { target: document.getElementById("app")! });

window.addEventListener("pagehide", () => void unmount(app), { once: true });
