# 01 — The Brief

What the hackathon is, what we decided to build, and what is still outstanding.

**Read this folder first.** Everything else is evidence for the decisions made here.

---

## Files, most important first

### 1. [TODO.md](TODO.md) — what to do next
The live working document. Opens with a decision that changes the project (the
farm-to-group mapping already exists in the network model), then lists the
remaining physics, the graph-partitioning trap, the MCMC gaps, and the honesty
items for Friday's slides.

**If you read one file in this repository, read this one.**

### 2. [hackathon-brief.md](hackathon-brief.md) — the full context
Event logistics, organiser guidance, the domain concepts, and the candidate
project angle. Every claim is provenance-tagged, so you can see what is
confirmed and what is inference:

| Tag | Meaning |
|---|---|
| `[EMAIL]` | From the official TPSA announcement |
| `[ORGANISER]` | Verbal, from a PhD-student organiser |
| `[VERIFIED <date>]` | Checked against a live source on that date |
| `[MINE]` | Inference or judgement, not a sourced fact |
| `[AI-UNVERIFIED]` | LLM-generated, may be wrong |

Where this file and [../02-curtailment/ireland-high-voltage-grid.md](../02-curtailment/ireland-high-voltage-grid.md)
disagree, **that file wins** — it is the sourced one.

---

## The event

| | |
|---|---|
| **Dates** | Mon 7 – Fri 11 September 2026 |
| **Venue** | E3 Learning Foundry, TCD (teams may work anywhere) |
| **Run by** | TPSA CLG, TPSA student society, and TF Wind |
| **Format** | Day 1 briefing, then self-directed. Friday: each group presents |
| **Teams** | Up to 5 people |
| **Contact** | Caoimhe Burke (she/her), TPSA Secretary, tpsa@tcd.ie |

## The project, in three stages

Each stands alone if time runs out:

1. **Compute effectiveness.** For each transmission line, how much does each
   generator's output change the flow on it? This is a linear-algebra problem on
   the network graph and falls out of the DC power flow.
2. **Group on it.** Farms with similar effectiveness vectors are, by EirGrid's
   own definition, the same constraint group. Cluster, then compare against the
   real groups.
3. **Ask whether the grouping is any good.** EirGrid's groups are pre-defined for
   control-room speed, not optimality. Does dispatching by them waste more energy
   than a per-farm optimum? That difference, in MWh and euros, is the result.

## Corrections applied to this folder

- **The Braess reference is confirmed.** `[VERIFIED 05-09-26]` The grid briefing
  said Witthaut & Timme 2012 was "not independently confirmed"; the DOI resolves
  correctly via CrossRef to *Braess's paradox in oscillator networks,
  desynchronization and power outage*, **New J. Phys. 14 (2012) 083036**.
  Still open, and agreed by both files: **no source applies Braess's paradox to
  the Irish grid specifically.**
- **Outreach was dropped, deliberately.** `outreach-emails.md` held draft
  emails to ENTSO-E, Wind Energy Ireland and the CleanerGrid winners. It was
  deleted on 5 September: the project does not depend on anyone replying, and
  waiting on inboxes is not a good use of a five-day week.

---

## References

| File | Source | Notes |
|---|---|---|
| `hackathon-brief.md` | Written by Szymon Ablewicz, compiled 29 Aug 2026, revised 1 Sep 2026 | Synthesises the TPSA announcement email, verbal organiser guidance, and verified web sources |
| `TODO.md` | Written 5 Sep 2026 | Derived from a gap analysis of this repository |

**Primary source for the event itself:** TPSA Hackathon 2026 announcement email,
TPSA CLG / Theoretical Physics Student Association, Trinity College Dublin.

**Braess citation:** D. Witthaut and M. Timme, "Braess's paradox in oscillator
networks, desynchronization and power outage," *New Journal of Physics* **14**
(2012) 083036. DOI [10.1088/1367-2630/14/8/083036](https://doi.org/10.1088/1367-2630/14/8/083036).
Open access. Verified via CrossRef, 5 September 2026.
