import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { defineConfig, loadEnv } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig(({ mode }) => {
	const development = mode === "development";
	const databaseTest = mode === "qdrant-test";
	const environment = development || databaseTest ? loadEnv(mode, process.cwd(), "QDRANT_") : {};

	if (databaseTest && (!environment.QDRANT_ENDPOINT || !environment.QDRANT_API_KEY)) {
		throw new Error("Live database tests require QDRANT_ENDPOINT and QDRANT_API_KEY in .env.");
	}

	let outDir = "../dist/extension";

	if (development) {
		outDir = "../dist/development";
	} else if (databaseTest) {
		outDir = "../dist/qdrant-test";
	}

	return {
		define: {
			"import.meta.env.QDRANT_ENDPOINT": JSON.stringify(environment.QDRANT_ENDPOINT || ""),
			"import.meta.env.QDRANT_API_KEY": JSON.stringify(environment.QDRANT_API_KEY || ""),
		},
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
							source: readFileSync(resolve("extension", fileName)),
						});
					}

					this.emitFile({ type: "asset", fileName: "LICENSE", source: readFileSync("LICENSE") });
				},
				writeBundle(_, bundle) {
					if (databaseTest) {
						return;
					}

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
