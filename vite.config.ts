import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { defineConfig, loadEnv } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
	const development = mode === "development";
	const testing = mode === "test";
	const environment = loadEnv(mode, process.cwd(), "APP_API_URL");
	const apiUrl =
		process.env.APP_API_URL || environment.APP_API_URL || (development || testing ? "http://127.0.0.1:8765" : "");

	if (!apiUrl) {
		throw new Error("Set APP_API_URL to the deployed app backend before building a release.");
	}

	const endpoint = new URL(apiUrl);
	const localDevelopment = (development || testing) && endpoint.hostname === "127.0.0.1";

	if ((!localDevelopment && endpoint.protocol !== "https:") || endpoint.username || endpoint.password) {
		throw new Error("The app backend must use HTTPS. Local HTTP is allowed only for development and tests.");
	}

	if (endpoint.pathname !== "/" || endpoint.search || endpoint.hash) {
		throw new Error("APP_API_URL must be an origin without a path, query, or fragment.");
	}

	const outDir = development ? "../dist/development" : "../dist/extension";
	const manifest = JSON.parse(readFileSync(resolve("extension/manifest.json"), "utf8"));
	manifest.host_permissions = ["https://api.openai.com/*", `${endpoint.origin}/*`];

	return {
		define: { "import.meta.env.APP_API_URL": JSON.stringify(endpoint.origin) },
		root: "extension",
		base: "./",
		publicDir: false,
		plugins: [
			svelte({ configFile: resolve("svelte.config.js") }),
			tailwindcss(),
			{
				name: "extension-assets",
				generateBundle() {
					for (const fileName of ["manifest.json", "panel.html", "icons/brand.png"]) {
						this.emitFile({
							type: "asset",
							fileName,
							source:
								fileName === "manifest.json"
									? JSON.stringify(manifest)
									: readFileSync(resolve("extension", fileName)),
						});
					}

					this.emitFile({ type: "asset", fileName: "LICENSE", source: readFileSync("LICENSE") });
				},
				writeBundle(_, bundle) {
					// Keep an existing unpacked installation usable after each rebuild.
					for (const [fileName, asset] of Object.entries(bundle)) {
						if (!fileName.startsWith("runtime/")) {
							continue;
						}

						const destination = resolve("extension", fileName);

						mkdirSync(dirname(destination), { recursive: true });
						writeFileSync(destination, asset.type === "chunk" ? asset.code : asset.source);
					}
				},
			},
		],
		build: {
			outDir,
			emptyOutDir: true,
			target: "chrome123",
			rollupOptions: {
				input: { panel: resolve("extension/panel.ts"), background: resolve("extension/background.ts") },
				output: { entryFileNames: "runtime/[name].js", assetFileNames: "runtime/[name][extname]" },
			},
		},
	};
});
