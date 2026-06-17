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
const PORT = Number(process.env.PORT ?? 4173);

async function loadReviews(): Promise<Record<string, unknown>> {
	const file = Bun.file(REVIEW_FILE);
	return (await file.exists()) ? await file.json() : {};
}

const server = Bun.serve({
	port: PORT,
	development: { hmr: true, console: true },
	routes: {
		"/": index,
		"/api/pages": async () => {
			const data = await Bun.file(join(COMPARE_DIR, "compare.json")).json();
			const reviews = await loadReviews();
			for (const page of data.pages) page.review = reviews[page.id] ?? null;
			data.reviewedCount = Object.keys(reviews).length;
			return Response.json(data);
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
		if (url.pathname.startsWith("/images/")) {
			const file = Bun.file(join(COMPARE_DIR, url.pathname));
			if (await file.exists()) return new Response(file);
		}
		return new Response("Not found", { status: 404 });
	},
});

console.log(`lawnlord compare reviewer → ${server.url}`);
console.log(`reviewing: ${COMPARE_DIR}`);
