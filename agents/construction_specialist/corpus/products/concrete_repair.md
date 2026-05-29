# Concrete Repair Systems — Construction Specialist Corpus

> **Validated 2026-05-28 — committed to the Construction Specialist corpus (#198 Batch 2); orientation only, controlling authority is the manufacturer TDS and the EOR/design professional. Stamped into `CORPUS_VERSION`.**
>
> **Orientation only — not a substitute for the TDS or the EOR.** This reference orients the Construction Specialist on concrete repair for SSC's facade (LL11/FISP) and parking-garage (LL126) work. The controlling authority on any specific product is always its **current manufacturer technical data sheet (TDS)**; the controlling authority on any structural decision (capacity, load path, what to remove, whether a member is adequate) is always the **Engineer of Record (EOR)**. The agent must cite the source for a claim or flag it as general-knowledge-to-verify, and must never fabricate a standard's section number or a product's spec.

---

## 1. Repair-mortar system types

Repair materials are broadly grouped by binder. Selection depends on the substrate, exposure, structural vs. cosmetic role, thickness, and cure-time constraints — guidance for which is consolidated in **ACI PRC-546 (Concrete Repair — Guide)** and **ACI PRC-546.3 (Materials Selection for Concrete Repair — Guide)** [ACI 546.3-23 preview]. Material families:

- **Cementitious (Portland-cement-based) repair mortars/concretes** — the workhorse for structural and large-volume repair. Packaged, dry, rapid-hardening cementitious repair materials are specified under **ASTM C928** ("Standard Specification for Packaged, Dry, Rapid-Hardening Cementitious Materials for Concrete Repairs"). C928 distinguishes *concrete* materials (≥5% by mass aggregate retained) from *mortar* materials (<5% retained), and explicitly **excludes** materials whose principal binder is an organic compound such as bitumen, epoxy, or polyester [ASTM C928/C928M-20a].
- **Polymer-modified cementitious (PCC / PMC)** — Portland-cement mortar with a polymer (e.g., acrylic, SBR) added for improved bond, reduced permeability, and better freeze-thaw/de-icing-salt durability. Common for facade and deck patching where bond and durability matter. (Material family described in ACI 546.3.)
- **Epoxy and other polymer mortars** — resin-bound (epoxy, polyester, etc.); high strength and chemical resistance, used for thin/precision repairs, but with very different stiffness and thermal behavior from concrete (see §7 incompatibility). Outside the scope of ASTM C928 by definition.
- **Microsilica (silica-fume)-modified mortars** — cementitious mortars with silica fume for low permeability/high durability in chloride environments (parking decks). *(General industry characterization — confirm specific properties against the chosen product's TDS.)*

> Practical rule the agent should surface: **match repair-material properties to the parent concrete**, not "stronger is better" (see §7). The TDS governs mix, thickness limits, and cure.

## 2. Surface preparation

Bond is made or lost at the prepared surface. The governing reference is **ICRI Guideline No. 310.2R-2013** ("Selecting and Specifying Concrete Surface Preparation for Sealers, Coatings, Polymer Overlays, and Concrete Repair") [ICRI 310.2R-2013].

- **Concrete Surface Profile (CSP):** ICRI defines **10 profiles, CSP 1 (nearly flat) through CSP 10 (very rough)**, used as visual/tactile comparator "chips" to specify and inspect roughness. **CSP 10 was added in the 2013 edition specifically to reflect the more aggressive profile used for concrete repair** [ICRI 310.2R-2013; DeFelsko CSP reference]. Higher-CSP (rougher) profiles are generally specified for structural repair/overlays; low CSP for thin coatings/sealers.
- **Remove all unsound/deteriorated concrete** back to sound substrate; **saw-cut the repair perimeter** to a defined edge (avoid feather-edging, which is a classic debonding origin). *(Standard practice; the depth/extent of removal on a structural element is an EOR call.)*
- **Substrate moisture condition:** cementitious repairs are typically placed on a **saturated surface-dry (SSD)** substrate so the parent concrete doesn't pull water out of the repair (see §4). The required condition is product-specific — **the TDS governs.**

## 3. Reinforcing-steel corrosion

Most structural concrete deterioration SSC repairs is corrosion-driven. Two mechanisms:

- **Chloride-induced corrosion** — chlorides (de-icing salts in garages, marine air) penetrate to the steel and break down its passive layer. Dominant in parking decks.
- **Carbonation-induced corrosion** — atmospheric CO₂ lowers concrete pH over time, de-passivating the steel. More common in older facade elements.

Repair practice:

- **Expose and clean corroded steel to bright metal** (remove rust/scale around the full bar perimeter), and assess section loss — **section-loss evaluation and any need to supplement/replace bars is an EOR decision.** *(Standard practice; verify cleanliness standard against project spec/TDS.)*
- **Incipient-anode / "ring" / "halo" effect (important and counter-intuitive):** patching chloride-contaminated concrete makes the patch a strongly cathodic zone, which **accelerates corrosion in the still-contaminated parent concrete immediately around the patch** — so a well-made patch can trigger new corrosion at its edges. Documented across the repair-corrosion literature [ScienceDirect, "Diagnosing the cause of incipient anodes in repaired reinforced concrete structures"; Sika corrosion-management technical notes].
- **Galvanic (sacrificial) anodes** mitigate the incipient-anode effect: a zinc core embedded at the patch perimeter corrodes preferentially to the steel, protecting adjacent rebar (e.g., **Sika FerroGard-670** discrete embedded galvanic anode) [Sika FerroGard product literature; Sika "Corrosion Management with Sacrificial Anodes"]. *Reported field longevity varies by study — one study reported galvanic-anode control of chloride-induced corrosion for ~10–14 years in a jetty/industrial building, versus conventional patch strategies that can fail within ~5 years* [ScienceDirect, "Long-term performance of galvanic anodes…"] — **treat these durations as study-specific, not a general guarantee.**
- **Corrosion-inhibiting admixtures/treatments** are an additional/alternative measure (product-specific; TDS governs).

## 4. Bonding

- Repairs are placed on a **saturated surface-dry (SSD)** substrate (damp, no standing water) so the parent concrete doesn't dewater the fresh repair; **a bonding agent / bonding slurry** is used where the product calls for it. **Whether a bonding agent is required, and which one, is product-specific — the TDS governs.**
- **Bond verification:** the standard field/lab test is the **direct-tension pull-off test, ASTM C1583** ("Standard Test Method for Tensile Strength of Concrete Surfaces and the Bond Strength or Tensile Strength of Concrete Repair and Overlay Materials by Direct Tension (Pull-off Method)"). It measures both near-surface substrate tensile strength (an indicator of surface-prep adequacy) and the repair-to-substrate bond strength [ASTM C1583; WJE / Intertek test-method summaries].

## 5. Governing standards & references

The agent should name these and route to the controlling document for exact values:

- **ICRI 310.2R-2013** — surface preparation / CSP selection.
- **ASTM C928/C928M-20a** — packaged, dry, rapid-hardening cementitious repair materials (spec).
- **ASTM C1583** — repair bond strength / substrate tensile by pull-off.
- **ASTM C109** — compressive strength of hydraulic-cement mortars (commonly referenced for mortar strength). *(Confirm exact applicability for a given product against its TDS.)*
- **ACI PRC-546** (Concrete Repair — Guide) and **ACI PRC-546.3** (Materials Selection for Concrete Repair — Guide) — repair material/method selection.
- **ACI 562** — Code Requirements for Assessment, Repair, and Rehabilitation of Existing Concrete Structures; **used for repair design outside the scope of ACI 318** [ACI 546.3 preview reference]. EOR territory.

## 6. Parking-garage specifics (LL126 work)

- **Slab/deck repair** carries the chloride exposure of §3 plus traffic loading; **traffic-bearing waterproofing/membrane coatings** are typically restored over deck repairs (product/system-specific — TDS governs the coating system and its interface with the repair).
- **POST-TENSIONED decks — critical safety + structural caution.** Many commercial parking structures use bonded or unbonded PT. **Locate tendons before any saw-cutting or coring** — cutting/coring a PT slab without locating strands is described as code-prohibited and requires **engineering approval and a tendon locator (e.g., GPR)** [GPRS, "How to Safely Saw or Drill into Concrete in Post-Tensioned Slabs"; PTI Journal repair guidance].
  - Warning signs: a slab edge may be stamped **"Caution: Post-Tensioned Slab — Do Not Cut or Core,"** and **circular anchor pockets along the perimeter, roughly 30–48 in. apart**, mark stressed/patched live-end anchors [GPRS].
  - **Unbonded** systems use individually greased-and-sheathed strands; **bonded** systems group strands in grouted ducts (common in commercial garages/decks) [Concrete Network / GPRS].
  - **Nicking or cutting a stressed tendon can cause sudden, violent tension release (recoil) — a serious safety hazard — plus loss of load capacity** [GPRS]. Any PT repair is an **EOR/PT-specialist** operation; the agent advises and routes, never green-lights a cut.

## 7. Common failure modes of repairs

- **Delamination / debonding / spalling of the patch** — loss of bond at the repair interface; the most common repair failure. Drivers include inadequate surface prep (wrong/low CSP), feather-edges, contamination, or poor consolidation [ICRI 310.2R; ICRI CR Terminology 2022; Concrete Repair Authority "failure modes"].
- **Material incompatibility** — mismatch in **modulus of elasticity, drying shrinkage, or coefficient of thermal expansion** between repair and parent concrete concentrates stress at the interface and drives cracking/debonding. A frequently-cited illustration is a high-strength repair mortar (e.g., >6,000 psi) over a low-strength substrate (e.g., <3,000 psi) [attributed to ACI 546R guidance via Concrete Repair Authority — **verify the exact figures/section against ACI 546**]. This is the basis of the "match, don't over-strength" rule in §1.
- **Continued / incipient-anode corrosion** — see §3; the repair itself can drive new perimeter corrosion if chloride-contaminated concrete is left and no galvanic protection is used.
- **Drying-shrinkage cracking** of the repair, and **freeze-thaw / de-icing-salt scaling** where durability wasn't matched to exposure.

---

## Sources (retrieved 2026-05-28)

- ICRI Guideline 310.2R-2013 (CSP selection): https://store.icri.org/item/3102r2013-english-pdf-selecting-concrete-surface-preparation-sealers-coatings-polymer-overlays-concrete-repair-342521 ; CSP chip reference: https://www.defelsko.com/csp
- ASTM C928/C928M-20a (packaged dry repair materials): https://store.astm.org/standards/c928
- ASTM C1583 (pull-off bond): https://store.astm.org/standards/c1583 ; https://www.wje.com/expertise/laboratories/testing-standards/astm-c1583
- ACI PRC-546.3 (materials selection, preview): https://www.concrete.org/Portals/0/Files/PDF/Previews/546.3-23_preview.pdf
- Incipient/ring-anode effect: https://www.sciencedirect.com/science/article/abs/pii/S0010938X12005744 ; long-term galvanic performance: https://www.sciencedirect.com/science/article/abs/pii/S2352710221009074
- Galvanic anodes (Sika FerroGard-670): https://usa.sika.com/en/construction/repair-protection/corrosion-protection/anodes/sika-ferrogard-670.html ; https://gbr.sika.com/en/construction/concrete-repair/media/news/2017/corrosion-management-with-sacrificial-anodes.html
- Post-tensioned slab cutting safety: https://www.gp-radar.com/article/how-to-safely-saw-or-drill-into-concrete-in-post-tensioned-slabs ; PTI repair guidance: https://gti-usa.net/wp-content/uploads/2020/04/Repairs-Modifications-and-Strengthening-with-Post-Tensioning-PTI-Journal-July-2006.pdf
- ICRI Concrete Repair Terminology (2022): https://www.icri.org/wp-content/uploads/2024/01/icri-crterminology-2022.pdf
- Concrete repair failure modes (secondary synthesis): https://concreterepairauthority.com/concrete-repair-failure-modes

### Flagged for operator/EOR verification
- The ">6,000 psi over <3,000 psi" incompatibility figures are from a secondary source attributing them to ACI 546R — confirm against the actual ACI 546 text before the agent treats them as a hard threshold.
- Galvanic-anode service-life figures (~10–14 yr) are from one study's specific structures — not a general guarantee.
- ASTM C109 applicability is product-dependent — the TDS governs which strength test/value applies.
