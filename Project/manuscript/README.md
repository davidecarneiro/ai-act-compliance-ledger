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

1. Rui Sousa's affiliation (`main.tex`): he is listed under affiliation 3, which
   is now CIICESI after the affiliations were renumbered.
2. Passport-style photographs of the four authors (`\bio{figures/<file>}`).
3. Zenodo DOI for the artefacts (`refs.bib`, key `artefacts`).
4. Table 2: three cells marked CHECK (measured cost in CT/Sigstore, Regueiro et al., Shi et al.).
5. `refs.bib`: entries marked CHECK; preprints checked for a published version.
6. Supplementary material the text refers to: the full audit-question matrix
   (Section 6.7) and the Annex IV coverage (Section 7.3); planned S1–S6 in the article plan.

Done on 2026-11-19: funding, CRediT, ORCIDs, biographies, generative-AI
declaration (authors); R. Sousa's review (dates and presumptions of Directive
2024/2853, qualification under eIDAS, redaction of the policy, Fabric
validation, style), applied with the keyed policy commitment and the WP5 rerun.
