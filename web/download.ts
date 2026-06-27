// Multi-level download endpoints (issue #124, ADR-0007).
//
// Every node in the exploded hierarchy — page, document, image, filing, case —
// can be downloaded as the *actual artifacts*, for QA and the record:
//
//   - page    → the page PNG, the text-layer text, and each model's
//               transcription, served as individual files; plus a .zip that
//               bundles all three.
//   - image   → the filed PDF (the court's leaf record), one file per image,
//               deep-linkable to a page in the viewer. A separate .bundle route
//               zips the PDF together with every page artifact.
//   - document / filing / case → a .zip bundling the level's constituents
//               (page PNGs + transcription text for every page in scope, plus
//               the filed PDF for image/filing/case).
//
// This module is **read-only**: it reads structured data from the Python
// exports the server already shells to (`export-exploded` with a selector) and
// reads PNG/PDF *bytes* straight from the case dirs. It never writes the corpus;
// the only writes are to a private temp dir for building a zip, cleaned up after.
//
// Path-traversal safety: every byte we serve comes from a path we *construct*
// from export data and then confine — via realpath — to one of two roots
// (`extracted/pages` for PNGs, `intake/<stem>/files` for PDFs). A resolved path
// that escapes its root (`..`, an absolute id, or a symlink pointing out) is
// rejected before any read. Bundle members are confined the same way.

import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, basename } from "node:path";

import { safeJoin, pngRoot as pngRootFor, pdfRoot as pdfRootFor } from "./paths";

export interface DownloadConfig {
	caseDir: string;
	intakeDir: string;
	repoRoot: string;
}

// --- export data shapes (subset of the exploded lens we consume) ------------

interface Transcription {
	source: string; // "pdf_text" | "ai" | ...
	model: string | null;
	rev: number;
	createdAt: string | null;
	fidelity: number | null;
	text: string | null;
	agreement?: number;
	divergence?: unknown[];
}

interface Page {
	id: string;
	pageNumber: number;
	png: string; // "<imageId>/pNNN.png", relative to extracted/pages
	transcriptions: Transcription[];
}

interface Document {
	id: string;
	title: string;
	pageCount: number;
	pages: Page[];
}

interface Image {
	imageId: string;
	title: string;
	filename: string; // "<name>.pdf", relative to intake/<stem>/files
	documents: Document[];
}

// --- path safety ------------------------------------------------------------
//
// `safeJoin` and the root helpers live in ./paths and are shared with the
// static file handlers in index.ts so the traversal guard can't drift (#145).

function pngRoot(cfg: DownloadConfig): string {
	return pngRootFor(cfg.caseDir);
}

function pdfRoot(cfg: DownloadConfig): string {
	return pdfRootFor(cfg.intakeDir);
}

// --- export access ----------------------------------------------------------

async function runExport(cfg: DownloadConfig, args: string[]): Promise<any> {
	const out = await Bun.$`uv run lawnlord export-exploded --case-dir ${cfg.caseDir} ${args}`
		.cwd(cfg.repoRoot)
		.quiet()
		.text();
	return JSON.parse(out);
}

// --- transcription → file naming --------------------------------------------

/** A filesystem-safe slug for arbitrary ids/model names used in filenames. */
function slug(s: string): string {
	return s.replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "") || "x";
}

/** The text-layer reading for a page (the court's own pdf_text), if present. */
function textLayer(page: Page): Transcription | undefined {
	return page.transcriptions.find((t) => t.source === "pdf_text");
}

/** The model transcriptions for a page (everything that isn't pdf_text). */
function modelReadings(page: Page): Transcription[] {
	return page.transcriptions.filter((t) => t.source !== "pdf_text");
}

/** Stable label distinguishing one reading from another within a page. */
function readingLabel(t: Transcription): string {
	const parts = [t.source];
	if (t.model) parts.push(t.model);
	return slug(parts.join("-"));
}

// --- responses --------------------------------------------------------------

function attachment(filename: string): string {
	return `attachment; filename="${filename.replace(/"/g, "")}"`;
}

function notFound(msg = "Not found"): Response {
	return new Response(msg, { status: 404 });
}

function forbidden(): Response {
	return new Response("Forbidden", { status: 403 });
}

/** Serve a single PNG for a page, confined to extracted/pages. */
function pngResponse(cfg: DownloadConfig, page: Page): Response {
	const abs = safeJoin(pngRoot(cfg), page.png);
	if (!abs) return forbidden();
	return new Response(Bun.file(abs), {
		headers: {
			"content-type": "image/png",
			"content-disposition": attachment(`${slug(page.id)}.png`),
		},
	});
}

/** Serve a single PDF for an image, confined to intake/<stem>/files. */
function pdfResponse(cfg: DownloadConfig, image: Image): Response {
	if (!image.filename) return notFound("Image has no filed PDF");
	const abs = safeJoin(pdfRoot(cfg), image.filename);
	if (!abs) return forbidden();
	return new Response(Bun.file(abs), {
		headers: {
			"content-type": "application/pdf",
			"content-disposition": attachment(basename(image.filename)),
		},
	});
}

/** Serve one page-text artifact (.txt) — the text-layer or a model reading. */
function textResponse(t: Transcription | undefined, filename: string): Response {
	if (!t || t.text == null) return notFound("No such transcription");
	return new Response(t.text, {
		headers: {
			"content-type": "text/plain; charset=utf-8",
			"content-disposition": attachment(filename),
		},
	});
}

// --- bundle building ---------------------------------------------------------
//
// We materialize the level's files into a private temp dir, `zip -r -X` it
// (deterministic, no extra fields), stream the bytes, then remove the temp dir.
// Two member kinds: PNGs/PDFs copied from the (confined) case dirs, and text
// artifacts written from export data. Every copied source path is re-confined.

interface BundleMember {
	/** Path inside the archive, e.g. "doc_x/p001.png". */
	arcname: string;
	/** A confined absolute source path to copy, OR literal text content. */
	src?: string;
	text?: string;
}

function pageMembers(cfg: DownloadConfig, page: Page, prefix: string): BundleMember[] {
	const members: BundleMember[] = [];
	const png = safeJoin(pngRoot(cfg), page.png);
	if (png) members.push({ arcname: `${prefix}${slug(page.id)}.png`, src: png });
	const tl = textLayer(page);
	if (tl && tl.text != null) {
		members.push({ arcname: `${prefix}${slug(page.id)}.text-layer.txt`, text: tl.text });
	}
	for (const r of modelReadings(page)) {
		if (r.text == null) continue;
		members.push({
			arcname: `${prefix}${slug(page.id)}.${readingLabel(r)}.txt`,
			text: r.text,
		});
	}
	return members;
}

function imageMembers(cfg: DownloadConfig, image: Image, prefix: string): BundleMember[] {
	const members: BundleMember[] = [];
	if (image.filename) {
		const pdf = safeJoin(pdfRoot(cfg), image.filename);
		if (pdf) members.push({ arcname: `${prefix}${basename(image.filename)}`, src: pdf });
	}
	for (const doc of image.documents ?? []) {
		for (const page of doc.pages ?? []) {
			members.push(...pageMembers(cfg, page, prefix));
		}
	}
	return members;
}

/**
 * Build a deterministic .zip from `members` and return it as an attachment.
 * Members with no resolvable source/content are skipped; an empty member list
 * is a 404 (nothing to bundle).
 */
async function zipResponse(
	members: BundleMember[],
	zipName: string,
): Promise<Response> {
	const usable = members.filter((m) => m.src || m.text != null);
	if (usable.length === 0) return notFound("Nothing to bundle");

	const work = await mkdtemp(join(tmpdir(), "lawnlord-dl-"));
	try {
		// Stage every member under `work/<arcname>`, confined to `work`.
		for (const m of usable) {
			const dest = safeJoin(work, m.arcname);
			if (!dest) continue;
			await Bun.$`mkdir -p ${dirname(dest)}`.quiet();
			if (m.src) {
				await Bun.$`cp ${m.src} ${dest}`.quiet();
			} else {
				await Bun.write(dest, m.text ?? "");
			}
		}
		// -r recurse, -X strip extra file attributes, -q quiet. Deterministic
		// given identical staged bytes + names.
		const archive = join(work, "__bundle.zip");
		await Bun.$`cd ${work} && zip -r -X -q ${archive} . -x __bundle.zip`.quiet();
		const bytes = await Bun.file(archive).arrayBuffer();
		return new Response(bytes, {
			headers: {
				"content-type": "application/zip",
				"content-disposition": attachment(zipName),
			},
		});
	} finally {
		await rm(work, { recursive: true, force: true });
	}
}

// Local dirname (avoid importing both join+dirname noise above).
function dirname(p: string): string {
	const i = p.lastIndexOf("/");
	return i <= 0 ? "/" : p.slice(0, i);
}

// --- public router -----------------------------------------------------------

/**
 * Handle a `/download/...` request, or return null if the path isn't ours.
 *
 * Scheme (all GET):
 *   /download/page/:id                       page bundle (.zip)
 *   /download/page/:id/png                   page PNG
 *   /download/page/:id/text                  page text-layer (.txt)
 *   /download/page/:id/reading/:label        one model reading (.txt)
 *   /download/image/:id                      filed PDF (one file)
 *   /download/image/:id/bundle               image bundle (.zip): PDF + pages
 *   /download/document/:id                   document bundle (.zip)
 *   /download/filing/:id                     filing bundle (.zip)
 *   /download/case                           whole-case bundle (.zip)
 */
export async function handleDownload(
	cfg: DownloadConfig,
	pathname: string,
): Promise<Response | null> {
	if (!pathname.startsWith("/download/")) return null;
	const parts = pathname
		.slice("/download/".length)
		.split("/")
		.map((p) => decodeURIComponent(p))
		.filter((p) => p.length > 0);
	if (parts.length === 0) return notFound();

	const [level, id, sub, subId] = parts;

	try {
		switch (level) {
			case "case":
				return await caseBundle(cfg);
			case "page":
				if (!id) return notFound();
				return await pageRoute(cfg, id, sub, subId);
			case "image":
				if (!id) return notFound();
				return await imageRoute(cfg, id, sub);
			case "document":
				if (!id) return notFound();
				return await documentBundle(cfg, id);
			case "filing":
				if (!id) return notFound();
				return await filingBundle(cfg, id);
			default:
				return notFound();
		}
	} catch (err) {
		console.error(`download error for ${pathname}:`, err);
		return new Response("Download failed", { status: 500 });
	}
}

async function fetchPage(cfg: DownloadConfig, id: string): Promise<Page | null> {
	const data = await runExport(cfg, ["--page", id]);
	return (data.page as Page) ?? null;
}

async function pageRoute(
	cfg: DownloadConfig,
	id: string,
	sub: string | undefined,
	subId: string | undefined,
): Promise<Response> {
	const page = await fetchPage(cfg, id);
	if (!page) return notFound("No such page");

	if (!sub) {
		return zipResponse(pageMembers(cfg, page, ""), `${slug(id)}.zip`);
	}
	switch (sub) {
		case "png":
			return pngResponse(cfg, page);
		case "text":
			return textResponse(textLayer(page), `${slug(id)}.text-layer.txt`);
		case "reading": {
			if (!subId) return notFound();
			const r = modelReadings(page).find((t) => readingLabel(t) === subId);
			return textResponse(r, `${slug(id)}.${subId}.txt`);
		}
		default:
			return notFound();
	}
}

async function imageRoute(
	cfg: DownloadConfig,
	id: string,
	sub: string | undefined,
): Promise<Response> {
	const data = await runExport(cfg, ["--image", id]);
	const image = data.image as Image | undefined;
	if (!image) return notFound("No such image");

	if (!sub) return pdfResponse(cfg, image); // the filed PDF, one file
	if (sub === "bundle") {
		return zipResponse(imageMembers(cfg, image, ""), `${slug(id)}.zip`);
	}
	return notFound();
}

async function documentBundle(cfg: DownloadConfig, id: string): Promise<Response> {
	const data = await runExport(cfg, ["--document", id]);
	const doc = data.document as Document | undefined;
	if (!doc) return notFound("No such document");
	const members: BundleMember[] = [];
	for (const page of doc.pages ?? []) members.push(...pageMembers(cfg, page, ""));
	return zipResponse(members, `${slug(id)}.zip`);
}

async function filingBundle(cfg: DownloadConfig, id: string): Promise<Response> {
	const data = await runExport(cfg, ["--filing", id]);
	const images = (data.images as Image[] | undefined) ?? [];
	if (!data.filing) return notFound("No such filing");
	const members: BundleMember[] = [];
	for (const image of images) {
		members.push(...imageMembers(cfg, image, `${slug(image.imageId)}/`));
	}
	return zipResponse(members, `filing-${slug(id)}.zip`);
}

async function caseBundle(cfg: DownloadConfig): Promise<Response> {
	const data = await runExport(cfg, []);
	const images = (data.images as Image[] | undefined) ?? [];
	const members: BundleMember[] = [];
	for (const image of images) {
		members.push(...imageMembers(cfg, image, `${slug(image.imageId)}/`));
	}
	return zipResponse(members, "case.zip");
}
