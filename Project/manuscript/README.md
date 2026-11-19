# Manuscript — Computer Standards & Interfaces

LaTeX source of the article, with Elsevier's `els-cas-templates` (`cas-dc`,
double column), numbered references (`elsarticle-num`). Upload the folder (or
the zip) to Overleaf as a new project; the default compiler (pdfLaTeX + BibTeX)
builds it. `highlights.txt` is the separate highlights file the journal asks for.

| Path | Content |
| --- | --- |
| `main.tex` | Front matter (title, authors, affiliations, abstract, highlights, keywords), section inputs, biographies |
| `sections/` | Sections 1–9 and the declarations |
| `tables/` | One file per table |
| `figures/` | F1–F3 as TikZ (editable), F4 and F5 as PDF (from `prototype/article/figures.py`), F6 as listings |
| `refs.bib` | References; preprints checked for a published version on 2026-11-19 |
| `supplementary/` | Supplementary material S1–S6 (`supplementary.tex`; tables in `generated/` from `prototype/article/supplementary.py`) |

Every number in Section 6 comes from a result file in `Project/experiments/article/`
and is listed, with its source, in section 16 of the article plan.

## Still to complete

1. Rui Sousa's affiliation (`main.tex`): he is listed under affiliation 3, which
   is CIICESI since the affiliations were renumbered.
2. Zenodo DOI for the artefacts: create the release `article-v1.0` with the
   Zenodo integration on; then replace "DOI to be added" in
   `sections/10-declarations.tex` and in `refs.bib` (key `artefacts`).
3. Passport-style photographs of the four authors, if the submission system
   asks for them now (`\bio{figures/<file>}`).

Done on 2026-11-19: funding, CRediT, ORCIDs, biographies, generative-AI
declaration (authors); R. Sousa's review, applied with the keyed policy
commitment and the WP5 rerun; Table 2 and the references checked against their
sources; supplementary material S1–S6.
