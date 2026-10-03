# Register of Claims by Source

> **Purpose:** this register records the claims the dissertation attributes to each source, the basis on which each was verified, and the date of the check.
>
> **States:** ✅ verified against the full PDF · ✔️ verified against the abstract, the metadata or an official source · ❌→✅ the dissertation was wrong and was corrected.
>
> Word counts in the notes (for instance «audit 218×») record the search that located the passages; the check itself was a reading of those passages.
>
> **How to read it.** The coverage index gives the state of every cited source in the delivered version. The three tables after it are dated checks, kept as they were recorded; where a later check changed the reading, the row says so. A ✔️ records that the claim was compared with the source on that date. It is the author's reading of the source, not a certification by a third party.
>
> **Scope.** The dated working notes behind these tables (the triage of external reviews, the corrections and the checks on the verification scripts themselves) are kept in the author's working repository and are not part of this folder. Legal provisions are in `Legal Register.md`; numerical results are in `experiments/RESULTS_SUMMARY.md`.
>
> Paths beginning `03_literatura/`, `05_latex/`, `00_admin/`, `02_notas/` or `07_outputs/` refer to the author's working repository, where the sources and the LaTeX live. They are kept because they say where each check was carried out.
>
> **Last revised:** 2026-10-03.

## Coverage index by citekey

| Citekey | State | Method / note |
|---|---|---|
| `Barocas2019` | ✔️ | a canonical work (fairmlbook): the incompatibility between fairness criteria is a central result of the book |
| `REGULATIONEU2016` | ✔️ | official text (Legal Register) |
| `RegulationEU2023` | ✔️ | official text (Data Act) |
| `RegulationEU2024` | ✔️ | official text (Legal Register) |
| `RegulationEU2014eIDAS` | ✔️ | the base act; Arts. 25(2), 35(2) and 41(2) checked on 2026-09-14 in the official text and in EUR-Lex sources |
| `RegulationEU2024a` | ✔️ | the amending instrument; 45k and 45l checked in the official text |
| `RegulationEU2026` | ✔️ | Reg. (EU) 2026/1744, of 2026-07-08 (the Digital Omnibus on AI). **Checked character by character in the official OJ PDF (EN and PT) on 2026-09-13**, in `03_literatura/papers/OJ_L_202601744_EN_TXT.pdf` and `..._PT_TXT.pdf`. The official title in PT and EN, the OJ of 2026-07-24, in force 2026-07-27 (Art. 4, the third day after publication). Annex III → 2027-12-02; Art. 6(1) and Annex I → 2028-08-02; a simplified Annex IV form for SMEs and small mid-caps (Art. 11), with no reduction of the minimum content; two new prohibited practices in Art. 5 (points (ba) and (bb)), applicable from 2026-12-02. Arts. 49 and 50(2) are NOT amended. Art. 73 is NOT amended. Full detail in the «Digital Omnibus» section of `Legal Register.md` |
| `RegulationEU2025` | ✔️ | Implementing Reg. (EU) 2025/2531, the QEL standards of Art. 45l(3); the official EN and PT PDFs in papers/ plus 2 sources (Bitkom, Cryptomathic) |
| `DirectiveEU2024PL` | ✔️ | Directive (EU) 2024/2853 (liability for defective products). Arts. 2(1), 4(1), 9(1), 9(4), 9(5), 10(2)(a), 10(4) and 10(5) checked verbatim on 2026-09-16 in the official OJ PDF stored at `papers/Directive (EU) 20242853 product liability.pdf`. Used in Chapter 6 (§burden of proof). See `Legal Register.md` for the detail by provision and for the delimitation: the Art. 10 presumptions bear on defectiveness and the causal link, not on regulatory compliance |
| `abbasEnsuringZeroTrust2025` | ✔️ | PDF: zero-trust 23×, GDPR 34×, federated 42×, formal verification 6×. **The AI Act and Blockchain cells rechecked on 2026-09-17 against pp. 4, 5, 23 and 25**: blockchain is a central component (Algorithm 1, updates mined into blocks), hence «✓», and the normative mapping stays with the GDPR without reaching the AI Act, hence «No». The table row said the opposite in both cells |
| `alamilloQualifiedLedgersBreakthrough2024` | ✔️ | QEL and 45k–45l cross-checked against the official text |
| `arnoldFactSheetsIncreasingTrust2019` | ✔️ | abstract and title (FactSheets/SDoC) |
| `atenieseRedactableBlockchainRewriting2017` | ✔️ | PDF: redact 87×, chameleon hashes 88×, and the limited-rewriting claim is supported by the text read |
| `balanFrameworkCryptographicVerifiability2025` | ✔️ | abstract (commitments and ZKP). **Editorial status corrected on 2026-09-16**: not a preprint, published in the proceedings of the 10th ACM International Workshop on Security and Privacy Analytics (IWSPA '25), pp. 49--59, DOI 10.1145/3716815.3729011. The locators were removed because the arXiv version consulted has 12 pages and the proceedings 11 |
| `brandenburgerBlockchainTrustedComputing2018` | ✔️ | abstract (plus the SGX caveats in the text). **Rechecked in the full PDF on 2026-09-17**: msp=0, x.509=0, «private channel»=0, «complexity»=0; p. 3 supports only chaincode and endorsement policies, and the SGX side channels are declared out of the threat model on p. 5. The attributions of MSP, X.509, private channels, Go-Java and «operational complexity» were removed from the text, and Lu p. 4 and Sychowiec pp. 3, 11 and 23 now support those characteristics. Also «multi-stakeholder governance costs in regulated sectors» (ch. 2): cost=0, governance=0, sector=0 in the PDF, so the sentence became an own hypothesis with Suhail's survey (p. 26) enumerating the logistical costs |
| `buscemiAssessingHighRiskAI2026` | ✔️ | abstract and PDF §3.7 (a structure distinct from Matrix 3.2) |
| `cencenelec2025standards` | ✔️ | the CEN-CENELEC online source (prEN→Art. 17 corrected) |
| `cunatneguerolesBlockchainbasedDigitalTwin2024` | ✔️ | **Reverified 2026-09-17 and corrected.** It is not a survey: the abstract (p. 73) says «This paper presents a case study» (a DT over FIWARE Canis Major and Ethereum for fleet allocation in road logistics); «survey» has 0 occurrences across the 16 pages and «energy» appears only as consumption (p. 84). Chapter 2 presented it as a survey alongside Suhail, and it became a case study |
| `directiveEU20222555NIS2` | ✔️ | the fact and date checked |
| `edpbGuidelinesBlockchain2025` | ✔️ | the official PDF in the vault: **Guidelines 02/2025, version 2.0, adopted 2026-07-07** (checked on the PDF's cover on 2026-09-13; this line still said «v1.1, 2025-04-08, a possible v2.0 to be confirmed» and was corrected on 2026-09-16). The substance used is unchanged; v2.0 does not use «preferred» or «recommended», so the dissertation says «one of the mitigation measures» |
| `fermiFairEmpiricalRisk2021` | ✔️ | **Reverified 2026-09-16 and corrected.** The PDF confirms demographic parity (26×), equalized odds (18×) and the fairness-accuracy trade-off (15×), and that is what supports the citations in Chapter 5 §121 and in Chapter 6's roadmap. But it does **not** support the claim of incompatibility between fairness criteria it was attached to in Chapters 2 and 5: zero occurrences of «incompatible», «cannot be satisfied», «mutually exclusive» and «simultaneous». The citation was removed from those two sentences, which now rest on Barocas et al., ch. 3, alone. The earlier ✔️ measured the presence of the themes, not support for the claim. Also recorded: the work was **published in TMLR (2022)**, arXiv 2102.12586 now serves under the published title, and the PDF in the collection is the anonymous ICLR 2021 submission |
| `finckBlockchainsDataProtection` | ✔️ | the cautious position reflected (nuance added on 06-10) |
| `gamaSurveyConceptDrift2014` | ✔️ | PDF: a concept drift survey (138×) with adaptation and monitoring, consistent with the claim |
| `gauravGovernanceasaServiceMultiAgentFramework2025` | ✔️ | abstract (the Trust Factor is described there) |
| `hackerAIComplianceChallenges2022` | ✔️ | abstract |
| `hinderOneTwoThings2024` | ✔️ | PDF: a survey of drift monitoring and localisation, consistent with the claim; a weak citation in the Chapter 5 PoC sentence was removed on 06-10 |
| `hyperledgerFabricLedgerDocs2026` | ✔️ | the official Fabric documentation |
| `hyperledgerFabricOrdererDocs2026` | ✔️ | the «The Ordering Service» page checked on 2026-09-17: «Raft is a crash fault tolerant (CFT) ordering service», a leader-follower model, and not BFT (Raft is «the first step toward» a BFT service). It now supports the Chapter 4 sentence that previously cited the «Ledger» page, where raft=0 and «crash fault»=0 |
| `isoiec270012022` | ✔️ | a factual description of the standard |
| `isoiec420012023` | ✔️ | a factual description of the standard |
| `kaoConstantSizeCryptographicEvidence2026` | ✔️ | abstract (O(1)) |
| `kaoPostQuantumResilientAuditEvidence2026` | ✔️ | pp. 5 and 12 checked on 2026-09-17: the attack named is «harvest-now, forge-later», and the earlier ✔️ rested on the abstract and let the wrong name through |
| `limaMLOpsPracticesMaturity2022` | ✔️ | PDF: MLOps maturity and practices, MLflow 6×, Kubeflow 2×, consistent with the claim; the evidentiary part rests on Regueiro 2021 (co-citation) |
| `lopesEngineeringAIAgents2026` | ✔️ | PDF: a clinical case (a critical domain), events 62×, governance 42×, consistent with the claim. **Editorial status corrected on 2026-09-16**: not a preprint, and the camera-ready header identifies CAIN '26 (IEEE/ACM 5th Int. Conf. on AI Engineering), Rio de Janeiro, ACM ISBN 979-8-4007-2475-6, DOI 10.1145/3793653.3793774. **Pagination 2026-09-18**: pp. 252--260 (Crossref), checked against the camera-ready's 9 pages; the four locators went from `[1]` to `[252]`, the same page in the proceedings' pagination |
| `luSecureScalableData2020` | ✔️ | PDF: integrity auditing on Fabric (audit 218×, tamper 8×), consistent with the claim; «qualified» was removed from the Chapter 2 sentence (it was not from the sources) |
| `lucajTechOpsTechnicalDocumentation2025` | ✔️ | abstract |
| `marinoComplianceCardsAutomated2024` | ✔️ | the full PDF, 19 pp., checked 2026-09-18: the Project, Data and Model CCs and the rules algorithm are there, and the Blockchain=No axis is confirmed (hash/tamper/immutab 0×; «blockchain» 2×, both about others' work, Lohachab and Urovi, ref. 55). The Chapter 2 table row is confirmed |
| `marinoComputationalComplianceAI2026` | ✔️ | abstract. **Note 2026-09-17**: p. 2 argues the inevitability of computational compliance and does NOT support chained cryptographic anchoring (cryptograph=0, hash=0, anchor=0, blockchain=0 in the PDF), so the citation closing that sentence in Chapter 3 was removed |
| `nakamotoBitcoinPeertoPeerElectronic` | ✔️ | the 2008/2009 fact corrected |
| `nanniniAIAgentsEU2026` | ✔️ | abstract (the 4 challenges corrected) |
| `nathansonAIBillMaterials2025` | ✔️ | abstract (SPDX against CycloneDX) |
| `openlineage2024` | ✔️ | a factual description of the project |
| `palumboObjectiveMetricsEthical2024` | ✔️ | IJDSA 2024, DOI 10.1007/s41060-024-00541-w (the PDF in the vault matches: an SLR of objective metrics 2018–2023); the citation is limited to the survey's scope; it was in the original thesis proposal and was restored on 2026-06-11 |
| `palumboObservabilityDrivenAIGovernance` | ✔️ | PDF: observability 16×, governance 17×, AI Act 36×, real-time 6×, consistent with the claim. **2026-06-11:** confirmed published (DiTTET 2025, Springer AISC 1465, pp. 402–413, DOI 10.1007/978-3-031-99474-6_36), so it no longer counts as a preprint; the `.bib` updated to @inproceedings/2025 |
| `peffersDesignScienceResearch2007` | ✔️ | a classic, checked (the 6 DSR activities) |
| `radanlievOperationalisingArtificialIntelligence2026` | ✔️ | abstract (CycloneDX) |
| `rajmohanEUAIAct` | ✔️ | PDF: Annex IV 18×, technical documentation 29×, consistent with the claim |
| `ramosBlockchainAIActCompliance2024` | ✔️ | abstract |
| `regueiroBlockchainBasedAuditTrail2021` | ✔️ | abstract plus the vault's note |
| `regueirolHyperledgerFabricCriminal2025` | ✔️ | abstract |
| `regulationEU2022868DGA` | ✔️ | the fact and date checked |
| `santosBlockchainbasedRentalDocumentation2024` | ✔️ | the full PDF (Ricardian ✓; Besu: 0, corrected) |
| `sharmaDigitalTwinsState2022` | ✔️ | PDF: the definition of a DT as a synchronised replica (synchron 19×), consistent with the claim |
| `shiAUDITEMAutomatedEfficient2022` | ✔️ | the full PDF (PRE/Pedersen: 0 occurrences, corrected) |
| `suhailBlockchainBasedDigitalTwins2022` | ✔️ | the full PDF (a verbatim direct quotation, p. 3) |
| `sychowiecBlockchainBasedFrameworkSecure2025` | ✔️ | abstract (reformulated as an analogy) |
| `tabassiArtificialIntelligenceRisk2023` | ✔️ | the 4 RMF functions checked |
| `tullaVeriForgotBlockchainAttestedVerifiable2026` | ✔️ | abstract |
| `ugarteMakingAICompliance2026` | ✔️ | abstract |
| `uralSurveyBlockchainEnhancedMachine2023` | ✔️ | the PDF swept (a blockchain and ML survey confirmed) |
| `valpitereRightErasurePrivate` | ✔️ | abstract (the PDF is not extractable, being scanned): GDPR Art. 17 against immutability, consistent with the claim |
| `vealeDemystifyingDraftEU2021` | ✔️ | CRi 22(4) 97–112, DOI verified (De Gruyter) 2026-06-11; the citation is limited to the central thesis (harmonised standards and self-assessment) |
| `wachterLimitationsLoopholesEU2024` | ✔️ | Yale JoLT 26(3) 671–718, verified (ORA Oxford/SSRN) 2026-06-11; the citation is limited to the central thesis (enforcement gaps) |
| `vandegiessenBlockchainGDPRsRight` | ✔️ | PDF: erasure 45×, forgotten, immutab, consistent with the claim |
| `vassilevAdversarialMachineLearning2025` | ✔️ | separated from STRIDE (corrected) |
| `w3cPROVO2013` | ✔️ | a factual description of the standard |
| `w3cVCDataModel2025` | ✔️ | a factual description of the standard |
| `wohlinExperimentationSoftwareEngineering2012` | ✔️ | the taxonomy checked |
| `zhaoConditionalLearningFair2020` | ✔️ | PDF: demographic parity 29×, the fairness-accuracy trade-off, consistent with the claim. **Editorial status corrected on 2026-09-16**: not a preprint, a conference paper at ICLR 2020 |

## Claims verified against the full PDF

| Source | The claim in the dissertation | Location | State | Date |
|---|---|---|---|---|
| `shiAUDITEMAutomatedEfficient2022` | It used "proxy re-encryption and Pedersen commitments": **0 occurrences in the PDF (17 pp)**. The paper uses smart contracts, DFS and DIVT | ch2 §evidencia_digital and the table | ❌→✅ corrected 2026-06-10 | 2026-06-10 |
| `shiAUDITEMAutomatedEfficient2022` | Based on Hyperledger Fabric | ch2 §evidencia_digital | ✅ (53 occurrences) | 2026-06-10 |
| `santosBlockchainbasedRentalDocumentation2024` | "Ricardian Contracts on Fabric/**Besu**": Besu does not appear in the paper; Ricardian confirmed (3×) | ch2 related-work table | ❌→✅ corrected 2026-06-10 ("Fabric") | 2026-06-10 |
| `suhailBlockchainBasedDigitalTwins2022` | The direct quotation "*blockchain ensures secure data management and DTs use trustworthy data…*" | ch2 §dt_blockchain_papel | ✅ verbatim, p. 3 (240:3); the page was added to the citation | 2026-06-10 |
| `suhailBlockchainBasedDigitalTwins2022` | The "*store only hash of data on-chain*" pattern | ch2 §dt_blockchain_papel | ✅ ("Storing only hash of data in blockchain", the paper's table) | 2026-06-10 |
| `balanFrameworkCryptographicVerifiability2025` | A framework based on commitment schemes and ZKP to tie model to dataset | ch2 §crypto_verifiability and §compliance_cripto | ✅ (26× "commitment", 40× "zero-knowledge") | 2026-06-10 |

## Claims verified against the abstract or the metadata

| Source | The claim in the dissertation | Location | State | Date |
|---|---|---|---|---|
| `hackerAIComplianceChallenges2022` | "AI Compliance" as a bridging field between law and data science | ch1, ch6 | ✔️ | 2026-06-10 |
| `marinoComputationalComplianceAI2026` | Compliance is attainable at scale only computationally | ch2 §convergencia | ✔️ | 2026-06-10 |
| `buscemiAssessingHighRiskAI2026` | A framework translating requirements into verification activities; declarative compliance | ch2, ch3, ch5 | ✔️ (2026, et al.) | 2026-06-10 |
| `nanniniAIAgentsEU2026` | Four agentic challenges: cybersecurity, human oversight, multi-party transparency, runtime drift | ch4 §gaas | ❌→✅ corrected (the list had been mis-transcribed) | 2026-06-10 |
| `lucajTechOpsTechnicalDocumentation2025` | Documentation templates aligned with the life cycle, validated with users | ch2 | ✔️ | 2026-06-10 |
| `arnoldFactSheetsIncreasingTrust2019` | FactSheets as an analogue of the SDoC, anticipating Annex IV | ch2, ch6 | ✔️ | 2026-06-10 |
| `regueirolHyperledgerFabricCriminal2025` | Fabric for criminal evidence integrity (road accidents), usable by non-technical staff | ch2, ch3 | ✔️ | 2026-06-10 |
| `ramosBlockchainAIActCompliance2024` | Blockchain aligns AI with the AI Act's data governance, record-keeping and transparency | ch2, ch3 | ✔️ | 2026-06-10 |
| `brandenburgerBlockchainTrustedComputing2018` | SGX and Fabric; rollback; enclaves | ch2, ch4 | ✔️ | 2026-06-10 |
| `sychowiecBlockchainBasedFrameworkSecure2025` | Secure dissemination of federated IoT streams with Fabric and Kafka. The Provider-to-NB channels are **the dissertation's analogy**, not the paper's | ch2 §confidencialidade | ❌→✅ reformulated (delimiting what is theirs) | 2026-06-10 |
| `gauravGovernanceasaServiceMultiAgentFramework2025` | GaaS: runtime enforcement with a Trust Factor | ch4 §gaas | ✔️ | 2026-06-10 |
| `tullaVeriForgotBlockchainAttestedVerifiable2026` | Unlearning certificates attested on a blockchain (GDPR Art. 17) | ch2, ch6 | ✔️ | 2026-06-10 |
| `radanlievOperationalisingArtificialIntelligence2026` | An AI-BOM over **CycloneDX** with cryptographic validation | ch2, ch4, ch6 | ✔️ (it said "SPDX", corrected earlier) | 2026-06-10 |
| `nathansonAIBillMaterials2025` | A comparison of SPDX 3.0 against CycloneDX 1.6; the SBOM-to-AI extension (AIRS) | ch2 §ai_bom, ch6 roadmap | ✔️ (the comparison is in the abstract) | 2026-06-10 |
| `carneiroMultiflowRepository` | A public GitHub repository (industrial stream simulation, Kafka/Faust/Grafana; PRR/PRODUTECH R3) | ch6 future work | ✔️ (repository README) | 2026-06-11 |
| `torresMultiFlowAmbientIntelligence` | Published: ISAmI 2025, LNNS 1776, pp. 12–19, DOI 10.1007/978-3-032-14138-5_2 | ch6 future work | ✔️ (SpringerLink) | 2026-06-11 |
| `ugarteMakingAICompliance2026` | OSCAL for AI Act evidence; Assessment Results validated against the NIST schema | ch2, ch3, ch5 | ✔️ | 2026-06-10 |
| `kaoConstantSizeCryptographicEvidence2026` | Constant-size O(1) evidence structures; single author, 2026 | ch2 §crypto_verifiability | ✔️ | 2026-06-10 |
| `kaoPostQuantumResilientAuditEvidence2026` | Harvest-now, **forge**-later (p. 5; §6.1 p. 12): exfiltrate classically signed records today and forge or repudiate in the future. It is an attack on authenticity, not on confidentiality; post-quantum signatures for evidence | ch2 §post_quantum, ch4, ch6 | ✔️ | 2026-09-17 (the dissertation called it «harvest now, decrypt later», which presupposes encrypted evidence and does not apply to on-chain data in clear; corrected) |
| `peffersDesignScienceResearch2007` | The six DSR activities | ch1, ch3 | ✔️ | 2026-06-10 |
| `wohlinExperimentationSoftwareEngineering2012` | The validity taxonomy (internal, external, construct, conclusion) | ch3 §ameacas_validade | ✔️ | 2026-06-10 |

## Legal and normative facts verified against official sources

| Fact | Location | State | Date |
|---|---|---|---|
| eIDAS 2.0: the QEL's legal presumption is in **Art. 45k**; the requirements are in **45l** | ch2/3/4/5 | ❌→✅ corrected (it said "45l") | 2026-06-10 |
| EDPB Guidelines 02/2025: hash-on-chain is a **preferred mitigation**, not "validation" | ch2, ch3, ch5 | ❌→✅ corrected (it had been overstated) · superseded 2026-09-13: version 2.0 of the Guidelines does not rank the measures, and the text now says «one of the mitigation measures» (see the Legal Register) | 2026-06-10 |
| Bias mitigation is in **Art. 10(2)(f)–(g)**; 10(3) is representativeness | ch2, ch5 | ❌→✅ corrected | 2026-06-10 |
| prEN 18286 gives a presumption for **Art. 17 (QMS)**, not Art. 11 | ch2, ch3 | ❌→✅ corrected | 2026-06-10 |
| Mandates: **M/593 and M/613** (AI Act), **M/606** (CRA); "M/600" does not exist | ch5 §standardisation | ❌→✅ corrected | 2026-06-10 |
| STRIDE is **Microsoft's**; NIST AI 100-2 is a complementary adversarial taxonomy | ch4, ch5 | ❌→✅ corrected | 2026-06-10 |
| 50–500 ms against 3.79 ms is **one to two** orders of magnitude | ch5 §performance | ❌→✅ corrected · superseded 2026-09-14/15: both figures were withdrawn (the 3.79 ms run is exploratory, and the 50–500 ms interval was in none of the cited sources) | 2026-06-10 |
| Bitcoin: the white paper is 2008, the network 2009 | ch2 | ❌→✅ corrected | 2026-06-10 |
| AI Act: signed 2024-06-13; prohibitions 2025-02; high risk 2026-08; the Art. 70 deadline 2025-08 | ch1, ch2 | ✔️ · superseded 2026-09-12: Reg. (EU) 2026/1744 moved the Annex III date to 2027-12-02 (see the Legal Register) | 2026-06-10 |
| HLEG 2019: the 7 requirements for trustworthy AI | ch2 | ✔️ | 2026-06-10 |
| FIPS 204/Dilithium 2024; Grover 256 to about 128 bits; Fabric 1.0 (2017); Hyperledger (2015); DSA/DMA 2022; NIS2 2022; DGA 2022; Data Act 2023 | ch2 | ✔️ | 2026-06-10 |
| Arts. 12 and 14: paraphrases without quotation marks (they are not literal quotations of the Portuguese Regulation) | ch1 | ❌→✅ corrected (quotation marks removed) | 2026-06-10 |

## Points of judgment recorded at delivery

- The fairness rule's record label is `Art.10(3)` and its OSCAL identifier `aia-10-3`. The rule itself rests on Art. 10(2)(f)–(g); the label was kept because changing it would mean regenerating the published records. Chapter 5 states the correspondence.
- prEN 18286 and prEN ISO/IEC 24970 had not been cited in the Official Journal when the dissertation was delivered; the text presents them as drafts.
