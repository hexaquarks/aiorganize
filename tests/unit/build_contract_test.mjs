import { build } from "vite";

// Use the installed build tool, with no extension plugins or writes to the source installation.
await build({
	configFile: false,
	publicDir: false,
	logLevel: "error",
	build: {
		outDir: process.argv[2],
		target: "node22",
		minify: false,
		lib: {
			entry: process.argv[3],
			formats: ["es"],
			fileName: () => "contract.test.mjs",
		},
		rollupOptions: { external: [/^node:/] },
	},
});
