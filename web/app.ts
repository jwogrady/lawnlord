// Page-by-page review over the case's TRUE structure: case → filing → image →
// page. A "filing" is the submission event the court records (from the
// metadata); an image is the filed PDF. The left rail is the case table of
// contents at that level. Boundary-detected "documents" are ADDITIVE analysis
// (an exhibit/part label on a page) — never the organizing root. lawnlord's
// score + note ride on top; rate (good–bad), note, flag → human-reviewed. The
// gap vs lawnlord's score is the point.

type Review = {
	rating: number;
	notes: string;
	flag: boolean;
	reviewed: boolean;
} | null;

type Filing = { title: string; type: string; date: string };
type DocPart = { title: string; family: string } | null;

type Page = {
	id: string;
	filing: Filing;
	image: string;
	declaredPages: number | null;
	actualPages: number | null;
	mismatch: boolean;
	page: number;
	document: DocPart; // additive: the sub-unit (exhibit/part) this page is in
	actual: string; // the filed page, rendered
	text: string; // our textual representation (what's in DuckDB)
	textSource: string; // pdf | ocr | none
	masterPage: number; // page in the assembled reconstruction PDF
	score: number; // lawnlord confidence, 0..1
	note: string;
	review: Review;
};

type Integrity = {
	renderedPages: number;
	declaredPages: number;
	images: {
		image: string;
		rendered: number;
		actual: number;
		declared: number;
	}[];
	ok: boolean;
	errors: string[];
	flags: string[];
};

type Data = {
	case: string;
	masterPdf?: string;
	integrity?: Integrity;
	pages: Page[];
};

// The Original layer: the court's record, verbatim. Two modes (see memory):
// Original = court metadata only; Enhanced = our additive classification.
type Party = { role: string; name: string; representation: string };
type RegEntry = {
	date: string;
	type: string;
	party: string;
	description: string;
	filing: { title: string; image: string; declaredPages: number } | null;
};
type Manifest = {
	case: string;
	court?: string;
	judicialOfficer?: string;
	caseType?: string;
	status?: string;
	dateFiled?: string;
	parties: Party[];
	registerOfActions: RegEntry[];
};

const app = document.getElementById("app") as HTMLElement;
const progressEl = document.getElementById("progress") as HTMLElement;
const modeEl = document.getElementById("mode") as HTMLElement;

let data: Data;
let manifest: Manifest = { case: "", parties: [], registerOfActions: [] };
let mode: "original" | "enhanced" =
	(localStorage.getItem("lawnlord-mode") as "original" | "enhanced") ??
	"enhanced";
let idx = 0;

function esc(s: string): string {
	return (s ?? "").replace(
		/[&<>"]/g,
		(c) =>
			({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string,
	);
}

function reviewedCount(): number {
	return data.pages.filter((p) => p.review?.reviewed).length;
}

// One group per filed image (case → filing → image). Each carries the rendered
// vs declared page counts so the TOC shows whether the output matches the docket.
type FilingGroup = {
	filing: Filing;
	image: string;
	declared: number | null;
	rendered: number;
	mismatch: boolean;
	first: number;
	reviewed: number;
	idxs: number[];
};

function filingGroups(): FilingGroup[] {
	const out: FilingGroup[] = [];
	const at = new Map<string, number>();
	data.pages.forEach((p, i) => {
		if (!at.has(p.image)) {
			at.set(p.image, out.length);
			out.push({
				filing: p.filing,
				image: p.image,
				declared: p.declaredPages,
				rendered: 0,
				mismatch: p.mismatch,
				first: i,
				reviewed: 0,
				idxs: [],
			});
		}
		const g = out[at.get(p.image) as number];
		g.rendered++;
		g.idxs.push(i);
		if (p.review?.reviewed) g.reviewed++;
	});
	return out;
}

async function load(): Promise<void> {
	const [pagesRes, manRes] = await Promise.all([
		fetch("/api/pages"),
		fetch("/api/manifest"),
	]);
	data = await pagesRes.json();
	manifest = await manRes.json();
	idx = data.pages.findIndex((p) => !p.review?.reviewed);
	if (idx < 0) idx = 0;
	render();
}

function renderModeToggle(): void {
	modeEl.innerHTML = `
    <button class="modebtn${mode === "original" ? " on" : ""}" data-mode="original" title="Court metadata only">Original</button>
    <button class="modebtn${mode === "enhanced" ? " on" : ""}" data-mode="enhanced" title="Our additive classification + analysis">Enhanced</button>`;
	for (const el of modeEl.querySelectorAll(".modebtn")) {
		(el as HTMLButtonElement).onclick = () => {
			mode = (el as HTMLElement).dataset.mode as "original" | "enhanced";
			localStorage.setItem("lawnlord-mode", mode);
			render();
		};
	}
}

function render(): void {
	renderModeToggle();
	if (mode === "original") {
		renderOriginal();
		return;
	}
	renderEnhanced();
}

// ORIGINAL — the court's register of actions, verbatim, plus the filed page
// (the court's own document). No text, scores, parts, or reconstruction.
function renderOriginal(): void {
	const m = manifest;
	progressEl.textContent = `${m.registerOfActions.length} docket entries · ${m.case}`;
	const filings = filingGroups();
	const curImg = data.pages[idx]?.image;
	const roa = m.registerOfActions
		.map((e) => {
			const f = e.filing;
			const target = f ? filings.find((g) => g.image === f.image) : undefined;
			const first = target ? target.first : -1;
			const isCur = !!f && f.image === curImg;
			const badge = e.type ? `<span class="fam">${esc(e.type)}</span>` : "";
			const pp = f ? `${f.declaredPages} pp` : "no document";
			const title = f ? esc(f.title) : esc(e.description || e.type);
			return `<button class="docitem${isCur ? " cur" : ""}" data-first="${first}"${first < 0 ? " disabled" : ""}>
        <span class="doctitle"><span class="docn">${esc(e.date)}</span> ${title}</span>
        <span class="docmeta">${badge}${pp}${e.party ? ` · ${esc(e.party)}` : ""}</span>
      </button>`;
		})
		.join("");
	const p = data.pages[idx];
	const viewer = p
		? `<section class="score-bar"><span class="doc">${esc(p.filing.title)}</span>
        <span class="pageid">${esc(p.image)} · p.${p.page} of ${p.actualPages ?? "?"}</span></section>
      <section class="single"><figure><figcaption>FILED PAGE — original (court record)</figcaption>
        <img src="${p.actual}" alt="filed page" /></figure></section>
      <section class="review"><div class="actions">
        <button id="prev"${idx === 0 ? " disabled" : ""}>‹ prev</button>
        <button id="next"${idx === data.pages.length - 1 ? " disabled" : ""}>next ›</button>
      </div></section>`
		: `<section class="score-bar"><span class="note">Select a filing from the register.</span></section>`;
	app.innerHTML = `<aside class="docs"><div class="docs-h">Register of actions — ${esc(m.case)}</div>${roa}</aside>
    <section class="pane">${viewer}</section>`;
	for (const el of app.querySelectorAll(".docitem")) {
		(el as HTMLButtonElement).onclick = () => {
			const f = Number((el as HTMLElement).dataset.first);
			if (f >= 0) {
				idx = f;
				render();
			}
		};
	}
	const prev = document.getElementById("prev") as HTMLButtonElement | null;
	const next = document.getElementById("next") as HTMLButtonElement | null;
	if (prev)
		prev.onclick = () => {
			if (idx > 0) idx--;
			render();
		};
	if (next)
		next.onclick = () => {
			if (idx < data.pages.length - 1) idx++;
			render();
		};
}

function renderEnhanced(): void {
	const p = data.pages[idx];
	const myScore = Math.round(p.score * 100);
	const rating = p.review ? p.review.rating : myScore; // default to lawnlord's
	progressEl.textContent = `${reviewedCount()} / ${data.pages.length} reviewed · ${data.case}`;

	// The left rail is the case TOC at the court's level: filing → image. The
	// current filing expands into its pages; a count mismatch is flagged here.
	const sidebar = filingGroups()
		.map((g, n) => {
			const isCur = g.image === p.image;
			const cur = isCur ? " cur" : "";
			const done = g.reviewed === g.rendered ? " done" : "";
			const type = g.filing.type
				? `<span class="fam">${esc(g.filing.type)}</span>`
				: "";
			// rendered vs declared — flagged when they disagree (never hidden)
			const count =
				g.declared != null && g.declared !== g.rendered
					? `<span class="flagcount">${g.rendered}/${g.declared} pp ⚑</span>`
					: `${g.rendered} pp`;
			const pages = isCur
				? `<div class="pages">${g.idxs
						.map((gi) => {
							const pp = data.pages[gi];
							const st =
								gi === idx
									? " cur"
									: pp.review?.flag
										? " flag"
										: pp.review?.reviewed
											? " done"
											: "";
							const mk = pp.review?.flag ? "⚑" : pp.review?.reviewed ? "✓" : "";
							return `<button class="pageitem${st}" data-idx="${gi}" title="${esc(pp.document?.title ?? "")}">p.${pp.page}<span class="mk">${mk}</span></button>`;
						})
						.join("")}</div>`
				: "";
			return `<button class="docitem${cur}${done}" data-first="${g.first}">
        <span class="doctitle"><span class="docn">${n + 1}.</span> ${esc(g.filing.title)}</span>
        <span class="docmeta">${type}${esc(g.filing.date)} · ${count} · ${g.reviewed}/${g.rendered}</span>
      </button>${pages}`;
		})
		.join("");

	const typeBadge = p.filing.type
		? `<span class="fam">${esc(p.filing.type)}</span>`
		: "";
	// additive: the detected sub-unit (exhibit/part), shown as an annotation only
	// — and only when it's genuinely distinct from the filing (not the allcaps
	// echo of the filing's own name).
	const norm = (s: string) => (s ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");
	const part =
		p.document && norm(p.document.title) !== norm(p.filing.title)
			? `<span class="part">part: ${esc(p.document.title)}</span>`
			: "";
	const cnt =
		p.declaredPages != null
			? `p.${p.page} of ${p.actualPages ?? "?"}${
					p.declaredPages !== p.actualPages
						? ` ⚑ docket says ${p.declaredPages}`
						: ""
				}`
			: `p.${p.page}`;
	app.innerHTML = `
    <aside class="docs">
      <div class="docs-h">Case contents — ${esc(data.case)}</div>
      ${sidebar}
    </aside>
    <section class="pane">
      <section class="score-bar${p.review?.reviewed ? " done" : ""}">
        <span class="doc">${esc(p.filing.title)} ${typeBadge}</span>
        ${part}
        <span class="score">lawnlord <b>${myScore}</b>/100</span>
        <span class="note">${esc(p.note)}</span>
        <span class="pageid">${esc(p.image)} · ${cnt}${p.review?.reviewed ? " · ✓ reviewed" : ""}</span>
      </section>
      <section class="compare">
        <figure><figcaption>FILED PAGE — original</figcaption><img src="${p.actual}" alt="filed page" /></figure>
        <figure class="textfig">
          <figcaption>OUR TEXT${p.textSource ? ` — ${esc(p.textSource)}` : ""}${
						data.masterPdf
							? ` · <a href="/${esc(data.masterPdf)}#page=${p.masterPage}" target="_blank" rel="noopener">reconstructed PDF ↗</a>`
							: ""
					}</figcaption>
          <div class="textpane">${p.text ? esc(p.text) : '<span class="empty">— no text extracted on this page —</span>'}</div>
        </figure>
      </section>
      <section class="review">
        <label class="rng">
          <span class="bad">bad</span>
          <input id="rating" type="range" min="0" max="100" value="${rating}" />
          <span class="good">good</span>
          <output id="rval">${rating}</output>
        </label>
        <div class="gap">gap vs lawnlord: <b id="gap">${rating - myScore}</b></div>
        <textarea id="notes" placeholder="specific feedback / notes">${p.review ? esc(p.review.notes) : ""}</textarea>
        <label class="flag"><input id="flag" type="checkbox"${p.review?.flag ? " checked" : ""} /> flag this page</label>
        <div class="actions">
          <button id="prev"${idx === 0 ? " disabled" : ""}>‹ prev</button>
          <button id="save" class="primary">mark reviewed &amp; next ›</button>
          <button id="next"${idx === data.pages.length - 1 ? " disabled" : ""}>skip ›</button>
        </div>
      </section>
    </section>`;
	wire(p, myScore);
}

function wire(p: Page, myScore: number): void {
	const ratingEl = document.getElementById("rating") as HTMLInputElement;
	const rval = document.getElementById("rval") as HTMLElement;
	const gap = document.getElementById("gap") as HTMLElement;
	ratingEl.oninput = () => {
		rval.textContent = ratingEl.value;
		gap.textContent = String(Number(ratingEl.value) - myScore);
	};
	for (const el of document.querySelectorAll(".docitem")) {
		(el as HTMLButtonElement).onclick = () => {
			idx = Number((el as HTMLElement).dataset.first);
			render();
		};
	}
	for (const el of document.querySelectorAll(".pageitem")) {
		(el as HTMLButtonElement).onclick = () => {
			idx = Number((el as HTMLElement).dataset.idx);
			render();
		};
	}
	document.querySelector(".pageitem.cur")?.scrollIntoView({ block: "nearest" });
	(document.getElementById("prev") as HTMLButtonElement).onclick = () => {
		if (idx > 0) idx--;
		render();
	};
	(document.getElementById("next") as HTMLButtonElement).onclick = () => {
		if (idx < data.pages.length - 1) idx++;
		render();
	};
	(document.getElementById("save") as HTMLButtonElement).onclick = async () => {
		const notes = (document.getElementById("notes") as HTMLTextAreaElement)
			.value;
		const flag = (document.getElementById("flag") as HTMLInputElement).checked;
		const rating = Number(ratingEl.value);
		await fetch("/api/review", {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify({ id: p.id, rating, notes, flag }),
		});
		p.review = { rating, notes, flag, reviewed: true };
		if (idx < data.pages.length - 1) idx++;
		render();
	};
}

load();
