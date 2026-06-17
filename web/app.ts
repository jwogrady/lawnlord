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

// Append-only correction history. rev 0 is the original extraction (immutable,
// from compare.json); each entry here is a re-extraction or human edit.
type Revision = {
	rev: number;
	text: string;
	source: string; // ocr | human | revert
	at: string;
	note?: string;
	confidence?: number | null;
};

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
	revisions: Revision[]; // corrections appended after rev 0 (the original)
	proposal: Proposal; // AI summary + analysis, #28: pending until accept/decline
};

// AI summary + analysis as a #28 proposal — additive, never overwrites the
// record; the human accepts or declines it.
type Analysis = {
	docType?: string;
	parties?: string[];
	dates?: string[];
	amounts?: string[];
	keyPoints?: string[];
	flags?: string[];
};
type Proposal = {
	status: "pending" | "accepted" | "declined";
	summary: string;
	analysis: Analysis;
	model: string;
	at: string;
} | null;

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
let origImage = ""; // the filing PDF shown in Original mode
let origPage = 1; // which page of that PDF the viewer is parked on

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

// The full revision chain for a page: rev 0 is the original extraction (from
// compare.json), followed by every appended correction. The last entry is current.
function allRevisions(p: Page): Revision[] {
	return [
		{
			rev: 0,
			text: p.text,
			source: p.textSource || "original",
			at: "",
			note: "original extraction",
		},
		...(p.revisions ?? []),
	];
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

// The AI panel: a button to run the pass, and (once run) the summary + analysis
// as a proposal the human accepts or declines. The transcription it produces
// lands in the revision history (source "ai"), not here.
function renderAiPanel(p: Page): string {
	const pr = p.proposal;
	const list = (label: string, items?: string[]) =>
		items && items.length
			? `<div class="arow"><span class="alabel">${label}</span><span class="aval">${items.map((x) => esc(x)).join(" · ")}</span></div>`
			: "";
	if (!pr) {
		return `<section class="ai">
      <div class="ai-h">AI — transcribe · summarize · analyze</div>
      <button id="analyze" class="ai-run">✨ Analyze this page with AI</button>
      <span id="aistate" class="savestate"></span>
    </section>`;
	}
	const a = pr.analysis ?? {};
	const badge =
		pr.status === "accepted"
			? `<span class="pstat ok">✓ accepted</span>`
			: pr.status === "declined"
				? `<span class="pstat no">✗ declined</span>`
				: `<span class="pstat pend">proposal · pending</span>`;
	return `<section class="ai ${pr.status}">
    <div class="ai-h">AI summary + analysis ${badge}<span class="aimodel">${esc(pr.model)}</span></div>
    <div class="asum">${esc(pr.summary)}</div>
    <div class="ameta">
      ${list("type", a.docType ? [a.docType] : [])}
      ${list("parties", a.parties)}
      ${list("dates", a.dates)}
      ${list("amounts", a.amounts)}
      ${a.keyPoints?.length ? `<div class="arow"><span class="alabel">key points</span><ul class="apts">${a.keyPoints.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
      ${a.flags?.length ? `<div class="arow"><span class="alabel">flags</span><ul class="apts flags">${a.flags.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>` : ""}
    </div>
    <div class="actions">
      <button id="accept" class="primary"${pr.status === "accepted" ? " disabled" : ""}>accept</button>
      <button id="decline"${pr.status === "declined" ? " disabled" : ""}>decline</button>
      <button id="reanalyze">⟳ re-analyze</button>
      <span id="aistate" class="savestate"></span>
    </div>
  </section>`;
}

function render(): void {
	renderModeToggle();
	if (mode === "original") {
		renderOriginal();
		return;
	}
	renderEnhanced();
}

// ORIGINAL — the court's register of actions, verbatim, alongside the court's
// own filing as a native PDF (selectable text, real paging) — not a render of
// it. No extracted text, scores, parts, or reconstruction.
function renderOriginal(): void {
	const m = manifest;
	progressEl.textContent = `${m.registerOfActions.length} docket entries · ${m.case}`;
	// the filings the court actually has documents for, in docket order
	const withDoc = m.registerOfActions.filter((e) => e.filing);
	if (!origImage && withDoc[0]?.filing) origImage = withDoc[0].filing.image;
	const cur = withDoc.find((e) => e.filing?.image === origImage);
	const roa = m.registerOfActions
		.map((e) => {
			const f = e.filing;
			const isCur = !!f && f.image === origImage;
			const badge = e.type ? `<span class="fam">${esc(e.type)}</span>` : "";
			const pp = f ? `${f.declaredPages} pp` : "no document";
			const title = f ? esc(f.title) : esc(e.description || e.type);
			return `<button class="docitem${isCur ? " cur" : ""}" data-image="${f ? esc(f.image) : ""}"${f ? "" : " disabled"}>
        <span class="doctitle"><span class="docn">${esc(e.date)}</span> ${title}</span>
        <span class="docmeta">${badge}${pp}${e.party ? ` · ${esc(e.party)}` : ""}</span>
      </button>`;
		})
		.join("");
	const pp = cur?.filing?.declaredPages ?? 0;
	if (origPage > pp) origPage = 1;
	// one pill per declared PDF page — clicking parks the viewer on that page
	const pagePills =
		pp > 0
			? `<div class="pages">${Array.from(
					{ length: pp },
					(_, i) =>
						`<button class="pageitem${i + 1 === origPage ? " cur" : ""}" data-page="${i + 1}">p.${i + 1}</button>`,
				).join("")}</div>`
			: "";
	const viewer = cur?.filing
		? `<section class="score-bar"><span class="doc">${esc(cur.filing.title)}</span>
        <span class="pageid">${esc(cur.filing.image)} · ${cur.filing.declaredPages} pp · filed ${esc(cur.date)}</span></section>
      ${pagePills}
      <section class="single"><figcaption>FILED DOCUMENT — original (court record)</figcaption>
        <iframe class="pdf" src="/filings/${encodeURIComponent(cur.filing.image)}#page=${origPage}&view=FitH" title="${esc(cur.filing.title)}"></iframe></section>`
		: `<section class="score-bar"><span class="note">Select a filing from the register.</span></section>`;
	app.innerHTML = `<aside class="docs"><div class="docs-h">Register of actions — ${esc(m.case)}</div>${roa}</aside>
    <section class="pane">${viewer}</section>`;
	for (const el of app.querySelectorAll(".docitem")) {
		(el as HTMLButtonElement).onclick = () => {
			const image = (el as HTMLElement).dataset.image;
			if (image) {
				origImage = image;
				origPage = 1; // new filing → back to its first page
				render();
			}
		};
	}
	for (const el of app.querySelectorAll(".pageitem")) {
		(el as HTMLButtonElement).onclick = () => {
			origPage = Number((el as HTMLElement).dataset.page);
			render();
		};
	}
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

	// the correction chain — rev 0 (original) then every appended edit/re-extract
	const revs = allRevisions(p);
	const curRev = revs[revs.length - 1];
	const fmtAt = (s: string) => (s ? s.slice(0, 16).replace("T", " ") : "");
	const history = revs
		.map((r) => {
			const isCur = r.rev === curRev.rev;
			const conf =
				r.confidence != null
					? ` · ${Math.round(r.confidence * 100)}% conf`
					: "";
			const meta = `rev ${r.rev} · ${esc(r.source)}${r.at ? ` · ${esc(fmtAt(r.at))}` : ""}${r.note ? ` · ${esc(r.note)}` : ""}${conf}`;
			const action = isCur
				? `<span class="revcur">current</span>`
				: `<button class="revert" data-rev="${r.rev}">revert</button>`;
			return `<div class="rev${isCur ? " cur" : ""}"><span class="revmeta">${meta}</span>${action}</div>`;
		})
		.join("");
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
          <figcaption>OUR TEXT — ${esc(curRev.source)}${curRev.rev ? ` (rev ${curRev.rev})` : ""}${
						data.masterPdf
							? ` · <a href="/${esc(data.masterPdf)}#page=${p.masterPage}" target="_blank" rel="noopener">reconstructed PDF ↗</a>`
							: ""
					}</figcaption>
          <textarea id="textedit" class="textedit" spellcheck="false">${esc(curRev.text)}</textarea>
          <div class="textctl">
            <button id="reextract">⟳ re-extract from image</button>
            <button id="savetext">save correction</button>
            <span id="savestate" class="savestate"></span>
          </div>
          <details class="revs"><summary>revision history (${revs.length})</summary>${history}</details>
        </figure>
      </section>
      ${renderAiPanel(p)}
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

	// correction loop: re-extract from the image, save a human edit, or revert —
	// each POSTs and appends a revision; nothing is overwritten.
	const editEl = document.getElementById("textedit") as HTMLTextAreaElement;
	const stateEl = document.getElementById("savestate") as HTMLElement;
	async function applyRevisions(history: Revision[]): Promise<void> {
		p.revisions = history;
		render();
	}
	(document.getElementById("reextract") as HTMLButtonElement).onclick =
		async () => {
			stateEl.textContent = "extracting…";
			const res = await fetch("/api/extract", {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify({ id: p.id, image: p.actual }),
			});
			const out = await res.json();
			if (!out.ok) {
				stateEl.textContent = `re-extract failed: ${out.error ?? "error"}`;
				return;
			}
			await applyRevisions(out.history);
		};
	(document.getElementById("savetext") as HTMLButtonElement).onclick =
		async () => {
			const res = await fetch("/api/revise", {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify({ id: p.id, text: editEl.value }),
			});
			await applyRevisions((await res.json()).history);
		};
	for (const el of document.querySelectorAll(".revert")) {
		(el as HTMLButtonElement).onclick = async () => {
			const rev = Number((el as HTMLElement).dataset.rev);
			const target = allRevisions(p).find((r) => r.rev === rev);
			if (!target) return;
			const res = await fetch("/api/revise", {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify({
					id: p.id,
					text: target.text,
					source: "revert",
					note: `reverted to rev ${rev}`,
				}),
			});
			await applyRevisions((await res.json()).history);
		};
	}

	// AI pass: run / accept / decline. Transcription appends to history; the
	// summary + analysis are a proposal the human decides on.
	const aiState = document.getElementById("aistate") as HTMLElement | null;
	async function runAi(): Promise<void> {
		if (aiState) aiState.textContent = "analyzing… (sends the page to the API)";
		const res = await fetch("/api/ai-page", {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify({ id: p.id, image: p.actual }),
		});
		const out = await res.json();
		if (!out.ok) {
			if (aiState) aiState.textContent = `AI failed: ${out.error ?? "error"}`;
			return;
		}
		p.revisions = out.history;
		p.proposal = out.proposal;
		render();
	}
	const analyzeBtn = document.getElementById("analyze");
	if (analyzeBtn) (analyzeBtn as HTMLButtonElement).onclick = runAi;
	const reanalyzeBtn = document.getElementById("reanalyze");
	if (reanalyzeBtn) (reanalyzeBtn as HTMLButtonElement).onclick = runAi;
	async function decide(status: "accepted" | "declined"): Promise<void> {
		const res = await fetch("/api/proposal", {
			method: "POST",
			headers: { "content-type": "application/json" },
			body: JSON.stringify({ id: p.id, status }),
		});
		const out = await res.json();
		if (out.ok) {
			p.proposal = out.proposal;
			render();
		}
	}
	const acceptBtn = document.getElementById("accept");
	if (acceptBtn)
		(acceptBtn as HTMLButtonElement).onclick = () => decide("accepted");
	const declineBtn = document.getElementById("decline");
	if (declineBtn)
		(declineBtn as HTMLButtonElement).onclick = () => decide("declined");

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
