import { defineConfig } from "vitest/config";

export default defineConfig({
	define: { "import.meta.env.APP_API_URL": JSON.stringify("http://127.0.0.1:8765") },
	test: {
		include: ["tests/unit/*.test.ts"],
		environment: "node",
	},
});
