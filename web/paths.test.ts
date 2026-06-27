// Path-confinement guard tests (#145). safeJoin is the single guard shared by
// the download endpoints and the static /files, /pages, /png handlers, so we
// test it directly: a legitimate in-root path (incl. a subdir) must resolve,
// and a traversal attempt and a symlink-escape attempt must be rejected.

import { afterAll, beforeAll, expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, symlinkSync, writeFileSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { safeJoin } from "./paths";

let base: string; // a fake CASE_DIR
let root: string; // the confined root, e.g. <base>/extracted/pages
let secret: string; // a file outside the root we must never reach

beforeAll(() => {
	base = realpathSync(mkdtempSync(join(tmpdir(), "lawnlord-paths-")));
	root = join(base, "extracted", "pages");
	mkdirSync(join(root, "img1"), { recursive: true });
	writeFileSync(join(root, "img1", "p001.png"), "PNG");

	// A secret outside the root, and a symlink inside the root pointing at it.
	secret = join(base, "secret.txt");
	writeFileSync(secret, "TOP SECRET");
	symlinkSync(secret, join(root, "escape.png"));
});

afterAll(() => {
	rmSync(base, { recursive: true, force: true });
});

test("resolves a legitimate in-root path, including a subdirectory", () => {
	const abs = safeJoin(root, "img1/p001.png");
	expect(abs).toBe(join(root, "img1", "p001.png"));
});

test("rejects a `..` traversal attempt", () => {
	expect(safeJoin(root, "../../secret.txt")).toBeNull();
	expect(safeJoin(root, "img1/../../../secret.txt")).toBeNull();
});

test("rejects an absolute component", () => {
	// resolve() would let an absolute rel override the join; safeJoin must not.
	expect(safeJoin(root, secret)).toBeNull();
});

test("rejects a null byte", () => {
	expect(safeJoin(root, "p001.png\0")).toBeNull();
});

test("rejects a symlink within the root that points outside it", () => {
	expect(safeJoin(root, "escape.png")).toBeNull();
});

test("a missing in-root path is returned (let the read 404), not rejected", () => {
	const abs = safeJoin(root, "img1/p999.png");
	expect(abs).toBe(join(root, "img1", "p999.png"));
});
