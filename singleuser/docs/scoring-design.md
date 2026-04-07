# Scoring Design — Rationale & Decisions

## The problem: LLMs score CVs too literally

CVs are high-level summaries, not exhaustive technical inventories. A single bullet point
like "Designed and implemented a container-based computing platform for resource-intensive,
interactive workloads on HPC systems" may represent years of deep work in distributed
systems, microservices, and infrastructure engineering — none of which is spelled out
explicitly.

A naive LLM scorer will penalise the candidate for "lacking microservices experience"
because the word never appears, even when the underlying competence is clearly inferable.
This is especially bad in brutal mode, which was originally written to actively discourage
inference ("transferable experience does NOT compensate for missing core domain expertise").

Real-world evidence: a candidate who had reached advanced interview stages for a senior
role received a 5/10 in brutal mode, with the gap cited as "lacks microservices for HPC"
— despite having built exactly that.

---

## Fix 1: inference preamble (`_PROMPT_CV_INFERENCE`)

A shared block of text injected into both normal and brutal mode prompts:

> CVs are high-level summaries, not exhaustive technical inventories. A single bullet
> point may represent years of deep work. You MUST make reasonable professional inferences:
> if an entry clearly implies relevant experience, treat that experience as present. Do NOT
> penalise for the absence of an explicit keyword when the underlying competence is clearly
> inferable. Only flag something as a gap when there is genuinely no evidence of it —
> direct or implied.

Key design choices:
- Applied to **both** modes — inference is not a "lenient" feature, it is correct behaviour.
- Brutal mode keeps its conservative scoring rubric and domain-mismatch penalty; it just
  no longer treats "keyword not present" as equivalent to "skill not present".
- The old brutal mode line "transferable soft skills or tangential experience do NOT
  compensate for missing core domain expertise" was removed because it was being
  interpreted by the LLM as a reason to ignore clearly implied technical experience,
  not just to ignore vague soft-skill hand-waving.

---

## Fix 2: personal notes (`_notes.txt` / `NOTES_PATH`)

Even with better inference, some things simply cannot be inferred from a CV:
- Publications and research not listed
- Depth of experience behind a terse bullet
- Skills deliberately omitted for brevity
- Languages, certifications, context

Solution: a free-text notes file (`data/_notes.txt`) the user fills in once. Contents
are injected into every scoring prompt as:

> Additional context provided by the candidate (treat as authoritative): ...

Design choices:
- **"Treat as authoritative"** — the LLM must not second-guess or discount this context.
  Without that instruction, LLMs tend to weight PDF content over plain text.
- Stored as a plain `.txt` file alongside `_cv.pdf` in the data directory, following
  the same conventions as the rest of the app.
- UI: a "Notes" button in the navbar, turns yellow when notes are non-empty so the user
  always knows whether extra context is active.
- Notes are **not** a substitute for a good CV — they are an escape hatch for context
  that CVs structurally cannot carry.

---

## When to re-score

After changing either the CV or the notes, existing scores are **not** automatically
invalidated (only CV changes invalidate scores via the `cv_hash` check). If you update
your notes, manually re-score roles that matter — the notes are not hashed.

---

## Known limitations of score provenance

Each score cache file records `cv_hash`, `scored_at`, and (when applicable) `notes_used`.
The following are **not** currently tracked:

**1. Model version / infrastructure fingerprint**
OpenAI returns a `system_fingerprint` in every response identifying the exact model
snapshot and infrastructure. We currently discard it. If OpenAI silently updates the
model, two scores computed at different times with identical inputs may differ, with no
way to tell why. Storing `system_fingerprint` alongside each score would make this
detectable.

**2. Job description snapshot**
Scores are computed against the job JSON at scoring time, but the JSON can be overwritten
by a re-scrape or manual edit. If the job description changes after scoring, the cached
score is silently stale. A hash of the job fields used in the prompt would allow
detecting this.

**3. Notes hash**
`notes_used` stores the full notes text, but there is no hash of it. The current design
does not auto-invalidate scores when notes change (by intent — re-score manually). A
`notes_hash` field would let the UI warn "notes have changed since this score was
computed" without forcing a re-score.
