"""Conservative official result interpretation: a result PDF is NOT proof of coverage."""
from __future__ import annotations
import re
import unicodedata

def norm(text: str) -> str:
    s = unicodedata.normalize("NFKD", text or "").lower()
    return "".join(x for x in s if not unicodedata.combining(x))

UNCOVERED = re.compile(
    r"\bdesert[aoes]?\b|\bsense\s+(?:cap\s+)?(?:person[ae]s?|candidat[se]s?|"
    r"aspirant[se]s?|seleccionad[aoes]?)\b|\bcap\s+(?:candidat|aspirant|persona)\b|"
    r"\bno\s+(?:s.ha\s+)?(?:adjudicat|cobert|seleccionat)\b|"
    r"\bno\s+hi\s+ha\s+(?:hagut\s+)?(?:adjudicaci|candidat)|"
    r"\bsense\s+adjudicacio\b|\brenunci[ae]\b|\banul.lad[aoes]?\b",
    re.I,
)
COVERED = re.compile(
    r"\b(?:placa|lloc|vacant)\s+(?:(?:ha\s+estat|es\s+troba|esta)\s+)?(?:adjudicad|cobert)[aoes]?\b|"
    r"\bs.adjudica\b|\badjudicatari[ae]\b|"
    r"\bpersona\s+(?:adjudicataria|seleccionada|assignada)\b|"
    r"\bdocent\s+(?:assignat|seleccionat)\b|"
    r"\bresultat\s*[:\-]\s*(?:cobert[aoes]?|adjudicad[aoes]?)\b",
    re.I,
)

def classify(text: str) -> str:
    """COVERED, UNFILLED or UNKNOWN. Ambiguous text never closes a place."""
    t = norm(text)
    found_uncovered = bool(UNCOVERED.search(t))
    # A negated result, e.g. "sense cap persona seleccionada", contains a
    # positive-looking substring. Remove negative phrases before positive match.
    found_covered = bool(COVERED.search(UNCOVERED.sub(" ", t)))
    if found_uncovered and not found_covered:
        return "UNFILLED"
    if found_covered and not found_uncovered:
        return "COVERED"
    return "UNKNOWN"
