/**
 * What each finding code *is*, and what colour it may wear.
 *
 * There are twelve codes. Twelve hues cannot survive an all-pairs
 * colour-blindness check on a white surface — in a 3D graph any two nodes can
 * end up adjacent, so "all pairs" is the honest test, and it caps a palette at
 * a handful of hues no matter how they are chosen. Cycling a ninth hue, or
 * nudging steps until the validator stops complaining, would just hide the
 * collapse behind colours nobody can actually tell apart.
 *
 * So colour carries the **family** — five hues plus one reserved neutral,
 * validated all-pairs on white (worst CVD dE 9.1, worst normal-vision dE 16.5)
 * — and the **code** is always present as text: on the filter chip, in the
 * hover label, and in the detail panel. Colour narrows; the word identifies.
 *
 * VISIT_OUT_OF_WINDOW takes the neutral deliberately. It is ~150 of the ~190
 * findings and has no edges, so it is the baseline the picture is read
 * against, not one signal among five. Painting it a sixth hue would give the
 * loudest colour to the least informative category.
 */

export const FAMILIES = {
  PATIENT: {
    id: 'PATIENT',
    label: 'Patient voice',
    blurb: 'what the person said, this session',
    color: '#2597d0',
    token: 'var(--cat-patient)',
  },
  SAFETY: {
    id: 'SAFETY',
    label: 'Safety',
    blurb: 'is a participant being harmed',
    color: '#c62828',
    token: 'var(--cat-safety)',
  },
  ELIGIBILITY: {
    id: 'ELIGIBILITY',
    label: 'Eligibility',
    blurb: 'should they have been enrolled at all',
    color: '#eda100',
    token: 'var(--cat-eligible)',
  },
  INTEGRITY: {
    id: 'INTEGRITY',
    label: 'Data integrity',
    blurb: 'do the records agree with themselves',
    color: '#1baf7a',
    token: 'var(--cat-integrity)',
  },
  TREATMENT: {
    id: 'TREATMENT',
    label: 'Treatment',
    blurb: 'what the participant was actually given',
    color: '#4a3aa7',
    token: 'var(--cat-treatment)',
  },
  CONDUCT: {
    id: 'CONDUCT',
    label: 'Study conduct',
    blurb: 'protocol timing — the baseline, deliberately neutral',
    color: '#8b8b8b',
    token: 'var(--cat-conduct)',
  },
}

/** code -> family id. Anything unmapped falls back to CONDUCT's neutral. */
export const CODE_FAMILY = {
  HYS_LAW_CANDIDATE:      'SAFETY',
  SAE_MISCODED:           'SAFETY',
  AE_BEFORE_FIRST_DOSE:   'SAFETY',
  EXCLUSION_VIOLATION:    'ELIGIBILITY',
  INCLUSION_VIOLATION:    'ELIGIBILITY',
  DOSING_ERROR:           'TREATMENT',
  PROHIBITED_CONMED:      'TREATMENT',
  MISSING_EXPOSURE_RECORD:'INTEGRITY',
  LAB_UNIT_MISMATCH:      'INTEGRITY',
  DUPLICATE_SUBJECT:      'INTEGRITY',
  VISIT_OUT_OF_WINDOW:    'CONDUCT',
  PATIENT_REPORTED:       'PATIENT',
}

/** A one-line gloss per code, for the hover label and the detail panel. */
export const CODE_BLURB = {
  HYS_LAW_CANDIDATE:      'liver-injury signal from paired lab values',
  SAE_MISCODED:           'serious event recorded as non-serious',
  AE_BEFORE_FIRST_DOSE:   'adverse event dated before any exposure',
  EXCLUSION_VIOLATION:    'enrolled despite an exclusion criterion',
  INCLUSION_VIOLATION:    'enrolled without meeting an inclusion criterion',
  DOSING_ERROR:           'dose given outside the protocol range',
  PROHIBITED_CONMED:      'a medication the protocol forbids',
  MISSING_EXPOSURE_RECORD:'visits recorded with no matching exposure',
  LAB_UNIT_MISMATCH:      'the same analyte reported in two units',
  DUPLICATE_SUBJECT:      'one person appears to be enrolled twice',
  VISIT_OUT_OF_WINDOW:    'visit outside its protocol-defined window',
  PATIENT_REPORTED:       'symptoms and medications the patient reported',
}

export const familyOf = (code) => FAMILIES[CODE_FAMILY[code]] || FAMILIES.CONDUCT

/** Hex for a code — used by three.js, which wants a number, and by the DOM. */
export const hexFor = (code) => familyOf(code).color
export const intFor = (code) => parseInt(familyOf(code).color.slice(1), 16)

/** "HYS_LAW_CANDIDATE" -> "Hy's law candidate" is too clever; keep it literal
 *  but readable, and never lowercase an acronym into nonsense. */
export const labelFor = (code) =>
  (code || '').replace(/_/g, ' ').toLowerCase()

/** Families present in a set of nodes, in the palette's fixed slot order so
 *  the legend never reorders itself between renders. */
const ORDER = ['PATIENT', 'SAFETY', 'ELIGIBILITY', 'INTEGRITY', 'TREATMENT', 'CONDUCT']

export function groupCodesByFamily(codeCounts) {
  const byFamily = new Map()
  for (const [code, n] of codeCounts) {
    const fam = familyOf(code)
    if (!byFamily.has(fam.id)) byFamily.set(fam.id, { family: fam, codes: [], total: 0 })
    const bucket = byFamily.get(fam.id)
    bucket.codes.push([code, n])
    bucket.total += n
  }
  for (const bucket of byFamily.values()) bucket.codes.sort((a, b) => b[1] - a[1])
  return ORDER.filter((id) => byFamily.has(id)).map((id) => byFamily.get(id))
}
