# Lawnlord User Experience

> **Status — vision document.** This describes lawnlord's *target user experience and roadmap*,
> not the shipped release. v0.1.0 is a command-line exploder with no dashboard or interactive
> workspace yet. See the [README](../README.md) and [CHANGELOG](../CHANGELOG.md) for what exists
> today.

## Overview

Lawnlord is a personal legal intelligence system designed to help a user understand a legal matter well enough to make informed decisions and generate exceptional filings.

The user experience should feel less like document management and more like operating a legal command center.

Users do not manage files.

Users manage cases.

The system's purpose is to continuously answer four questions:

1. What happened?
2. What can be proven?
3. What law applies?
4. What should be done next?

Every workflow, screen, analysis, and AI interaction should support those objectives.

---

# Core UX Philosophy

Traditional legal software focuses on documents.

Lawnlord focuses on understanding.

Traditional workflow:

```text
File → Folder → Search → Document
```

Lawnlord workflow:

```text
Evidence → Facts → Law → Strategy → Filing
```

The system should continuously transform raw information into actionable understanding.

---

# Primary User Journey

## Create or Open a Case

Users begin by selecting an existing case or creating a new one.

Example:

```text
Cases

• Smith v Jones
• Harris County Eviction Appeal
• Family Court Modification
• Property Damage Claim
```

Opening a case launches a dedicated legal workspace.

---

# Case Dashboard

The dashboard is the primary operating screen.

It immediately communicates:

- Current case status
- Evidence status
- Deadlines
- Risks
- Opportunities
- Recommended actions

Example:

```text
Smith v Jones

Case Health: Good

Claims
────────────────
8 Total
6 Supported
2 Weak

Evidence
────────────────
143 Items
17 Unreviewed

Deadlines
────────────────
Discovery Response
Due in 14 Days

Motion Hearing
Due in 21 Days

Strategy Alerts
────────────────
• Missing evidence for damages claim
• Opposing counsel cited questionable authority
• Motion to compel opportunity identified

Recommended Actions
────────────────
1. Review new court order
2. Add supporting evidence for damages
3. Draft response to motion to dismiss
```

The dashboard should function as a legal mission control center.

---

# Adding Information

Users add information by dragging files into a case.

Examples:

```text
MotionToDismiss.pdf
CourtOrder.pdf
ExhibitA.pdf
Emails.zip
Photos.zip
```

Users should never need to determine where files belong.

The system automatically:

- Classifies documents
- Performs OCR
- Extracts text
- Generates metadata
- Identifies entities
- Updates analysis

The user simply contributes information.

Lawnlord organizes it.

---

# Intake Experience

After files are added, the system processes them automatically.

Example:

```text
Processing Files

✓ OCR Complete
✓ Text Extracted
✓ Classified
✓ Facts Identified
✓ Evidence Linked
✓ Timeline Updated
✓ Analysis Refreshed
```

The user sees progress in terms of understanding rather than technical processing.

---

# Artifact Review Experience

Users review findings instead of manually reviewing files.

Example:

```text
Motion to Dismiss

Summary
────────────────

Claims Challenged
• Breach of Contract
• Fraud

Arguments Identified
• Failure to State a Claim
• Lack of Standing

Authorities Cited
• 3 Cases
• 2 Statutes

Potential Issues
• Missing exhibit references
• Outdated citation detected
```

The original document remains available but is secondary to the extracted understanding.

---

# Timeline Experience

The timeline provides a factual view of the case.

Example:

```text
Timeline

Jan 12
Lease Signed

Feb 15
Repair Request Submitted

Feb 20
Landlord Responded

Mar 3
Second Repair Request

Mar 18
Property Damage Documented

Apr 1
Lawsuit Filed
```

Events should be automatically extracted from all artifacts.

The timeline becomes one of the primary tools for understanding what happened.

---

# Evidence Experience

Users should be able to explore evidence directly.

Example query:

```text
Show evidence supporting retaliation.
```

Example result:

```text
Supporting Evidence

1. Email dated March 14
2. Text message dated March 18
3. Maintenance request dated March 20
4. Witness statement dated April 2

Assessment:
Strong Support
```

The system should think in terms of evidence and facts, not files and folders.

---

# Legal Research Experience

Users should be able to ask:

```text
What law applies here?
```

Example response:

```text
Relevant Authorities

Texas Property Code §92

Texas Rules of Civil Procedure

Related Cases

• Case A
• Case B
• Case C

Key Legal Issues

• Notice Requirements
• Habitability
• Retaliation
```

Research should be contextualized to the current case.

---

# Strategy Experience

Strategy is the most important capability.

The user should be able to ask:

```text
What should I do next?
```

Example response:

```text
Strategy Assessment

Strongest Position

• Written repair requests
• Photographic evidence
• Written admissions

Weakest Position

• Damages documentation incomplete
• Timeline gap in March

Recommended Actions

1. Obtain repair invoices
2. Gather witness statements
3. Prepare motion to compel

Potential Risks

• Discovery deadline approaching
• Missing expert support
```

The system should function as a strategist rather than a search engine.

---

# Drafting Experience

Drafting occurs only after sufficient understanding exists.

Users may request:

```text
Draft a response to the motion to dismiss.
```

The draft should be generated from:

- Facts
- Evidence
- Timeline
- Statutes
- Case law
- Court procedures
- Knowledge Base materials

Example:

```text
Draft Generated

Supporting Facts: 17
Supporting Exhibits: 8
Authorities Cited: 12

Issues Identified

• Missing damages citation
• Standing argument requires support
```

The drafting system should explain its reasoning.

---

# Explainability

Every conclusion should be traceable.

Example:

```text
Fact

Defendant received notice.

Supporting Sources

• Email.pdf page 3
• CertifiedMail.pdf page 1
• Exhibit B page 4
```

Nothing should appear as unexplained AI output.

Every conclusion should link back to source evidence and legal authority.

---

# Daily Workflow

Typical workflow:

```text
Open Case

Review New Information

Review Strategy Alerts

Review Deadlines

Ask Questions

Review Analysis

Generate Drafts

Continue Building Understanding
```

The user should leave every session with a clearer understanding of the case.

---

# Product Feel

Lawnlord should feel like:

- A legal war room
- A litigation intelligence platform
- A case command center
- An AI-assisted legal strategist

Lawnlord should not feel like:

- Dropbox
- Google Drive
- A PDF viewer
- A document repository
- A filing cabinet

---

# UX Success Criteria

A successful Lawnlord session should improve the user's ability to answer:

1. What happened?
2. What can be proven?
3. What law applies?
4. What should be done next?

Every feature in the system should exist to improve one or more of those answers.

---

# Guiding Principle

The user is not hiring Lawnlord to organize files.

The user is hiring Lawnlord to understand a case.

Understanding is the product.

Strategy is the outcome.

Filings are the artifact generated from that understanding.
