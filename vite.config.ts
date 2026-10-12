import { readFileSync } from "node:fs";
import { resolve } from "node:path";
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
				for (const fileName of ["manifest.json", "background.js", "icons/brand.png"]) {
					this.emitFile({ type: "asset", fileName, source: readFileSync(resolve("extension", fileName)) });
				}
				this.emitFile({ type: "asset", fileName: "LICENSE", source: readFileSync("LICENSE") });
			},
		},
	],
	build: {
		outDir: "../dist/extension",
		emptyOutDir: true,
		target: "chrome123",
		rollupOptions: {
			input: { panel: resolve("extension/panel.html") },
			output: { entryFileNames: "runtime/[name].js", assetFileNames: "runtime/[name][extname]" },
		},
	},
});
