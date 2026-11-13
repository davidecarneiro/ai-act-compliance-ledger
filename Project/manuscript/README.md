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
| `refs.bib` | References; entries marked `CHECK` must be compared with the publisher's version |

Every number in Section 6 comes from a result file in `Project/experiments/article/`
and is listed, with its source, in section 16 of the article plan.

## Still to complete (search for TODO and CHECK)

1. Funding statement (required by the journal).
2. CRediT roles: confirm the proposal in `sections/10-declarations.tex`.
3. ORCID of each author; Rui Sousa's affiliation.
4. Biographies (up to 100 words) and passport-style photographs.
5. Wording of the generative-AI declaration.
6. Zenodo DOI for the artefacts (`refs.bib`, key `artefacts`).
7. Table 2: three cells marked CHECK (measured cost in CT/Sigstore, Regueiro et al., Shi et al.).
8. `refs.bib`: entries marked CHECK; preprints checked for a published version.
9. Legal review by Rui Sousa: Section 2.1 and Table 1, Table 4 (column "Does not establish"), Section 7.3.
10. Supplementary material the text refers to: the full audit-question matrix (Section 6.7) and the Annex IV coverage (Section 7.3); planned S1–S6 in the article plan.
