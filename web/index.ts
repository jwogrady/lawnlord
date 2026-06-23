// lawnlord Actual-lens viewer — a local, single-user desktop tool.
//
// Reproduces the Odyssey portal from the case's DuckDB *mirror* (not by
// re-parsing the zip): the register of actions, parties, and each filing as its
// native PDF, plus the captured Odyssey pages/*.html for snapshot parity. It
// ends at the image — no extracted text, no analysis (that's the Exploded lens).
//
// CASE_DIR points at a case built by `lawnlord import` (holds lawnlord.duckdb
// and intake/<stem>/ with files/ + pages/). The case JSON comes from the Python
// CLI (the DuckDB read lives there); this server only serves it and the files.

import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

import index from "./index.html";
import { handleDownload, type DownloadConfig } from "./download";

const CASE_DIR = process.env.CASE_DIR ?? ".";
const REPO_ROOT = join(import.meta.dir, "..");
const PORT = Number(process.env.PORT ?? 4173);

// The extracted intake dir (data.json + files/ + pages/): either CASE_DIR
// itself, or the single folder under CASE_DIR/intake that holds a data.json.
function resolveIntakeDir(): string {
	if (existsSync(join(CASE_DIR, "data.json"))) return CASE_DIR;
	const base = join(CASE_DIR, "intake");
	if (existsSync(base)) {
		for (const entry of readdirSync(base)) {
			const dir = join(base, entry);
			if (existsSync(join(dir, "data.json"))) return dir;
		}
	}
	throw new Error(
		`No intake found under ${CASE_DIR} (expected data.json, or intake/<stem>/data.json). ` +
			`Run \`lawnlord import <zip> --case-dir ${CASE_DIR}\` first.`,
	);
}

const INTAKE_DIR = resolveIntakeDir();

// Config for the multi-level download routes (issue #124): read-only access to
// the case's PNG/PDF dirs + the Python exports the server already shells to.
const DOWNLOAD_CONFIG: DownloadConfig = {
	caseDir: CASE_DIR,
	intakeDir: INTAKE_DIR,
	repoRoot: REPO_ROOT,
};

// Serve a file from the intake dir under a fixed subdir, blocking path escapes.
function serveFromIntake(sub: string, rest: string): Response {
	const decoded = decodeURIComponent(rest);
	if (decoded.includes("..")) return new Response("Forbidden", { status: 403 });
	const file = Bun.file(join(INTAKE_DIR, sub, decoded));
	return new Response(file);
}

const server = Bun.serve({
	port: PORT,
	development: { hmr: true, console: true },
	routes: {
		"/": index,
		// The Actual-lens payload, straight from the DuckDB mirror via the CLI.
		"/api/case": async () => {
			const out = await Bun.$`uv run lawnlord export-actual --case-dir ${CASE_DIR}`
				.cwd(REPO_ROOT)
				.quiet()
				.text();
			return new Response(out, {
				headers: { "content-type": "application/json" },
			});
		},
		// The Exploded-lens payload: images → documents → pages + transcription.
		"/api/exploded": async () => {
			const out = await Bun.$`uv run lawnlord export-exploded --case-dir ${CASE_DIR}`
				.cwd(REPO_ROOT)
				.quiet()
				.text();
			return new Response(out, {
				headers: { "content-type": "application/json" },
			});
		},
		// The spatial-anchor regions for one page (?page=ID) — normalized boxes the
		// on-image highlight renderer overlays (ADR-0009). Read-only.
		"/api/regions": async (req) => {
			const pageId = new URL(req.url).searchParams.get("page") ?? "";
			try {
				const out = await Bun.$`uv run lawnlord export-regions --case-dir ${CASE_DIR} --page ${pageId}`
					.cwd(REPO_ROOT)
					.quiet()
					.text();
				return new Response(out, {
					headers: { "content-type": "application/json" },
				});
			} catch (err) {
				// A nonzero exit (bad page id, locked DB) becomes a 500 the client
				// treats as transient — it stays text-only and retries, never caching.
				return new Response(JSON.stringify({ pageId, regions: [], error: String(err) }), {
					status: 500,
					headers: { "content-type": "application/json" },
				});
			}
		},
	},
	async fetch(req) {
		const url = new URL(req.url);
		// Multi-level artifact downloads (page/image/document/filing/case).
		if (url.pathname.startsWith("/download/")) {
			const res = await handleDownload(DOWNLOAD_CONFIG, url.pathname);
			if (res) return res;
		}
		if (url.pathname.startsWith("/files/")) {
			return serveFromIntake("files", url.pathname.slice("/files/".length));
		}
		if (url.pathname.startsWith("/pages/")) {
			return serveFromIntake("pages", url.pathname.slice("/pages/".length));
		}
		// Exploded-layer page PNGs (rendered by `lawnlord explode`).
		if (url.pathname.startsWith("/png/")) {
			const rest = decodeURIComponent(url.pathname.slice("/png/".length));
			if (rest.includes("..")) return new Response("Forbidden", { status: 403 });
			return new Response(Bun.file(join(CASE_DIR, "extracted", "pages", rest)));
		}
		return new Response("Not found", { status: 404 });
	},
});

console.log(`lawnlord Actual lens → ${server.url}`);
console.log(`case: ${CASE_DIR}\nintake: ${INTAKE_DIR}`);
