import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
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
					this.emitFile({ type: "asset", fileName, source: readFileSync(resolve("extension", fileName)) });
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
		outDir: "../dist/extension",
		emptyOutDir: true,
		target: "chrome123",
		rollupOptions: {
			input: { panel: resolve("extension/panel.ts"), background: resolve("extension/background.ts") },
			output: { entryFileNames: "runtime/[name].js", assetFileNames: "runtime/[name][extname]" },
		},
	},
});
