// lawnlord compare reviewer — a local, single-user desktop tool.
// Bun serves the page, the compare artifact, and the review save endpoint.
// One workflow per page: compare (actual vs reconstructed) -> rate (good-bad
// range) -> note -> flag -> mark reviewed. Completing a page = human-reviewed.

import { join } from "node:path";

import index from "./index.html";

// The compare artifact (per-page images + compare.json) is case-specific data,
// produced by `lawnlord compare`. Defaults to the bundled sample so the page
// fires up out of the box; point COMPARE_DIR at a real case to review it.
const COMPARE_DIR = process.env.COMPARE_DIR ?? join(import.meta.dir, "sample");
const REVIEW_FILE = join(COMPARE_DIR, "review.json");
// Append-only correction history per page. The original extraction is rev 0
// (in compare.json, immutable); every re-extraction or human edit appends a new
// revision here — nothing is ever overwritten. "Current text" is the latest.
const REVISIONS_FILE = join(COMPARE_DIR, "revisions.json");
// AI summary + analysis are additive #28 proposals: Pending until a human
// accepts or declines. Kept separate from the immutable record and corrections.
const PROPOSALS_FILE = join(COMPARE_DIR, "proposals.json");
const REPO_ROOT = join(import.meta.dir, "..");
const PORT = Number(process.env.PORT ?? 4173);

type Revision = {
	rev: number;
	text: string;
	source: string; // ocr | human | revert
	at: string;
	note?: string;
	confidence?: number | null;
};

async function loadReviews(): Promise<Record<string, unknown>> {
	const file = Bun.file(REVIEW_FILE);
	return (await file.exists()) ? await file.json() : {};
}

async function loadRevisions(): Promise<Record<string, Revision[]>> {
	const file = Bun.file(REVISIONS_FILE);
	return (await file.exists()) ? await file.json() : {};
}

// Append a revision (rev 1, 2, … — rev 0 is the original in compare.json) and
// return the page's full appended history.
async function appendRevision(
	id: string,
	rev: Omit<Revision, "rev" | "at">,
): Promise<Revision[]> {
	const all = await loadRevisions();
	const hist = all[id] ?? [];
	all[id] = [
		...hist,
		{ ...rev, rev: hist.length + 1, at: new Date().toISOString() },
	];
	await Bun.write(REVISIONS_FILE, JSON.stringify(all, null, 2));
	return all[id];
}

// Re-run OCR on one page image by shelling out to the Python CLI (the engine
// lives there). The command prints ONLY JSON on stdout.
async function reextract(
	imageRel: string,
): Promise<{ text: string; confidence: number | null }> {
	const imgPath = join(COMPARE_DIR, imageRel);
	const out = await Bun.$`uv run lawnlord ocr-page ${imgPath}`
		.cwd(REPO_ROOT)
		.quiet()
		.text();
	return JSON.parse(out.trim());
}

type AiResult = {
	transcription: string;
	summary: string;
	analysis: Record<string, unknown>;
	model: string;
};

// Transcribe + summarize + analyze one page with Claude (Python CLI; sends the
// image to the Anthropic API — needs ANTHROPIC_API_KEY in this server's env).
async function aiPage(imageRel: string): Promise<AiResult> {
	const imgPath = join(COMPARE_DIR, imageRel);
	const out = await Bun.$`uv run lawnlord ai-page ${imgPath}`
		.cwd(REPO_ROOT)
		.quiet()
		.text();
	return JSON.parse(out.trim());
}

type Proposal = {
	status: "pending" | "accepted" | "declined";
	summary: string;
	analysis: Record<string, unknown>;
	model: string;
	at: string;
};

async function loadProposals(): Promise<Record<string, Proposal>> {
	const file = Bun.file(PROPOSALS_FILE);
	return (await file.exists()) ? await file.json() : {};
}

async function writeProposal(id: string, p: Proposal): Promise<void> {
	const all = await loadProposals();
	all[id] = p;
	await Bun.write(PROPOSALS_FILE, JSON.stringify(all, null, 2));
}

const server = Bun.serve({
	port: PORT,
	development: { hmr: true, console: true },
	routes: {
		"/": index,
		// Original layer: the court's register of actions, verbatim.
		"/api/manifest": async () => {
			const file = Bun.file(join(COMPARE_DIR, "manifest.json"));
			return (await file.exists())
				? Response.json(await file.json())
				: Response.json({ registerOfActions: [] });
		},
		"/api/pages": async () => {
			const data = await Bun.file(join(COMPARE_DIR, "compare.json")).json();
			const reviews = await loadReviews();
			const revisions = await loadRevisions();
			const proposals = await loadProposals();
			for (const page of data.pages) {
				page.review = reviews[page.id] ?? null;
				page.revisions = revisions[page.id] ?? [];
				page.proposal = proposals[page.id] ?? null;
			}
			data.reviewedCount = Object.keys(reviews).length;
			return Response.json(data);
		},
		// AI pass: transcribe (→ revision) + summarize/analyze (→ proposal).
		"/api/ai-page": {
			POST: async (req) => {
				const { id, image } = (await req.json()) as {
					id: string;
					image: string;
				};
				try {
					const ai = await aiPage(image);
					const history = await appendRevision(id, {
						text: ai.transcription,
						source: "ai",
						note: `AI transcription (${ai.model})`,
					});
					const proposal: Proposal = {
						status: "pending",
						summary: ai.summary,
						analysis: ai.analysis,
						model: ai.model,
						at: new Date().toISOString(),
					};
					await writeProposal(id, proposal);
					return Response.json({ ok: true, history, proposal });
				} catch (err) {
					return Response.json(
						{ ok: false, error: String(err) },
						{ status: 500 },
					);
				}
			},
		},
		// Accept or decline a page's AI proposal (the #28 human decision).
		"/api/proposal": {
			POST: async (req) => {
				const { id, status } = (await req.json()) as {
					id: string;
					status: "pending" | "accepted" | "declined";
				};
				const all = await loadProposals();
				if (!all[id])
					return Response.json(
						{ ok: false, error: "no proposal for page" },
						{ status: 404 },
					);
				all[id].status = status;
				await Bun.write(PROPOSALS_FILE, JSON.stringify(all, null, 2));
				return Response.json({ ok: true, proposal: all[id] });
			},
		},
		// Re-extract a page's text from its image (appends an `ocr` revision).
		"/api/extract": {
			POST: async (req) => {
				const { id, image } = (await req.json()) as {
					id: string;
					image: string;
				};
				try {
					const { text, confidence } = await reextract(image);
					const history = await appendRevision(id, {
						text,
						source: "ocr",
						confidence,
						note: "re-extracted from image",
					});
					return Response.json({ ok: true, history });
				} catch (err) {
					return Response.json(
						{ ok: false, error: String(err) },
						{ status: 500 },
					);
				}
			},
		},
		// Save a human correction or a revert (appends a revision; never overwrites).
		"/api/revise": {
			POST: async (req) => {
				const { id, text, note, source } = (await req.json()) as {
					id: string;
					text: string;
					note?: string;
					source?: string;
				};
				const history = await appendRevision(id, {
					text,
					source: source ?? "human",
					note: note ?? "",
				});
				return Response.json({ ok: true, history });
			},
		},
		"/api/review": {
			POST: async (req) => {
				const body = (await req.json()) as {
					id: string;
					rating: number;
					notes?: string;
					flag?: boolean;
				};
				const reviews = await loadReviews();
				reviews[body.id] = {
					rating: body.rating, // good–bad range, 0..100
					notes: body.notes ?? "",
					flag: Boolean(body.flag),
					reviewed: true,
					at: new Date().toISOString(),
				};
				await Bun.write(REVIEW_FILE, JSON.stringify(reviews, null, 2));
				return Response.json({
					ok: true,
					reviewedCount: Object.keys(reviews).length,
				});
			},
		},
	},
	// Serve the per-page images (actual + reconstructed renders) from the artifact.
	async fetch(req) {
		const url = new URL(req.url);
		if (url.pathname === "/lawnlord.png") {
			return new Response(Bun.file(join(import.meta.dir, "lawnlord.png")));
		}
		if (url.pathname === "/favicon.ico") {
			return new Response(Bun.file(join(import.meta.dir, "favicon.ico")));
		}
		if (url.pathname.startsWith("/images/") || url.pathname.endsWith(".pdf")) {
			const file = Bun.file(join(COMPARE_DIR, url.pathname));
			if (await file.exists()) return new Response(file);
		}
		return new Response("Not found", { status: 404 });
	},
});

console.log(`lawnlord compare reviewer → ${server.url}`);
console.log(`reviewing: ${COMPARE_DIR}`);
