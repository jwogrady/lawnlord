// Path-traversal confinement, shared by every byte-serving route (#145).
//
// Both the download endpoints (web/download.ts) and the static file handlers
// (/files, /pages, /png in web/index.ts) construct a filesystem path from
// caller-supplied data and must confine it to a fixed root. They share the one
// `safeJoin` below so the symlink-resolving guard can't drift between them.

import { realpathSync } from "node:fs";
import { join, resolve } from "node:path";

/**
 * Resolve `rel` under `root` and confine it there. Returns the absolute path
 * only if it stays inside `root` after symlink resolution; otherwise null.
 * `root` itself is realpath'd so a symlinked case dir is handled correctly.
 *
 * Rejects null bytes, lexical escapes (`..`, absolute components), and symlinks
 * inside the root that resolve to a target outside it — before any read.
 */
export function safeJoin(root: string, rel: string): string | null {
	// Reject obvious escapes early (an absolute rel would override the join).
	if (rel.includes("\0")) return null;
	const realRoot = realpathSync(resolve(root));
	const candidate = resolve(realRoot, rel);
	// Lexical confinement first (catches `..` even when the file is missing).
	if (candidate !== realRoot && !candidate.startsWith(realRoot + "/")) {
		return null;
	}
	// Symlink confinement: if the path exists, its realpath must also be inside.
	try {
		const real = realpathSync(candidate);
		if (real !== realRoot && !real.startsWith(realRoot + "/")) return null;
		return real;
	} catch {
		// Path doesn't exist yet — lexical check already passed; let the read 404.
		return candidate;
	}
}

/** The PNG root for a case: extracted/pages under the case dir. */
export function pngRoot(caseDir: string): string {
	return join(caseDir, "extracted", "pages");
}

/** The filed-PDF root for a case: files/ under the intake dir. */
export function pdfRoot(intakeDir: string): string {
	return join(intakeDir, "files");
}
