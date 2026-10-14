import { isRecord } from "./types";

export function modelErrorName(error: unknown): string {
	if (isRecord(error) && typeof error.name === "string") {
		return error.name;
	}

	return "";
}

export function modelErrorStatus(error: unknown): number | undefined {
	if (isRecord(error) && typeof error.status === "number") {
		return error.status;
	}

	return undefined;
}
