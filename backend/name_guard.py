"""Name-consistency guard.

Indian names written in English have no single spelling: Venkata / Venkat /
Vemkata, Subba Rao / Subbarao, initials vs full surnames, surname first vs
last. Different documents of the same person routinely disagree, and an
application typed with the "wrong" one can be rejected for mismatch.

This module is deliberately deterministic (no model call):
1. phonetic_key() folds the spelling variation that Indic-to-Latin
   transliteration produces (anusvara m/n, aspirates, long vowels, w/v,
   doubled letters, trailing schwa).
2. compare() decides: identical / same name, different spelling /
   initial vs full / different person.
3. reconcile() picks the spelling from the primary ID document, lists how
   every other document differs, and builds a letter-by-letter spell-back
   in the user's language so someone who cannot read English can still
   check exactly what will be typed into the form.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

# ------------------------------------------------------------------ keys
_ABBREV = {"mohd": "mohammed", "md": "mohammed", "mohamed": "mohammed", "muhammad": "mohammed",
           "kr": "kumar", "smt": "", "sri": "", "shri": "", "kum": "", "dr": ""}

_RULES = [
    (r"x", "ks"), (r"q", "k"), (r"ph", "f"), (r"w", "v"), (r"(?<=[aeiou])z", "j"),
    (r"([kgcjtdpb])h", r"\1"),  # aspirates: kh gh ch jh th dh ph bh -> plain
    (r"sh", "s"), (r"ee", "i"), (r"oo", "u"), (r"aa", "a"), (r"ou", "u"),
    (r"y", "i"), (r"m(?=[kgcjtdpb])", "n"),  # anusvara: Vemkata == Venkata
    (r"(.)\1+", r"\1"),  # doubled letters
]


def phonetic_key(token: str) -> str:
    t = re.sub(r"[^a-z]", "", token.lower())
    t = _ABBREV.get(t, t)
    for pat, rep in _RULES:
        t = re.sub(pat, rep, t)
    if len(t) > 3 and t.endswith("a"):
        t = t[:-1]  # trailing schwa: Venkata == Venkat
    return t


def tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[\s.,]+", name.strip()) if t]


def _split_initials(name: str) -> tuple[list[str], list[str]]:
    toks = tokens(name)
    initials = [t[0].lower() for t in toks if len(re.sub(r"[^A-Za-z]", "", t)) == 1]
    full = [t for t in toks if len(re.sub(r"[^A-Za-z]", "", t)) > 1]
    return full, initials


def _skeleton(key: str) -> str:
    return re.sub(r"[aeiou]", "", key)


def _words_align(fa: list[str], fb: list[str]) -> bool:
    ka = [phonetic_key(t) for t in fa]
    kb = [phonetic_key(t) for t in fb]
    used = set()
    for x in ka:
        best, bi = -1, None
        for i, y in enumerate(kb):
            if i not in used and fuzz.ratio(x, y) > best:
                best, bi = fuzz.ratio(x, y), i
        if bi is None:
            return False
        used.add(bi)
        y = kb[bi]
        if not x or not y or x[0] != y[0]:
            return False
        sx, sy = _skeleton(x), _skeleton(y)
        if not (sx == sy or (best >= 90 and fuzz.ratio(sx, sy) >= 80)):
            return False
    return True


def compare(a: str, b: str) -> dict:
    """Compare two Latin-script spellings of a name."""
    if a.strip().lower() == b.strip().lower():
        return {"verdict": "identical", "score": 100}
    fa, ia = _split_initials(a)
    fb, ib = _split_initials(b)
    ka = "".join(sorted(phonetic_key(t) for t in fa))
    kb = "".join(sorted(phonetic_key(t) for t in fb))
    # joined keys handle "Subba Rao" vs "Subbarao" regardless of word order
    joined_a = phonetic_key("".join(fa))
    joined_b = phonetic_key("".join(fb))
    score = max(
        fuzz.ratio(ka, kb),
        fuzz.token_set_ratio(" ".join(phonetic_key(t) for t in fa), " ".join(phonetic_key(t) for t in fb)),
        fuzz.ratio("".join(sorted(joined_a)), "".join(sorted(joined_b))) - 5,
    )
    # initials: "K. Venkat Subbarao" vs "Kondapalli Venkata Subba Rao"
    if ia or ib:
        firsts_a = {phonetic_key(t)[0] for t in fa if phonetic_key(t)} | set(ia)
        firsts_b = {phonetic_key(t)[0] for t in fb if phonetic_key(t)} | set(ib)
        inits_ok = set(ia) <= firsts_b and set(ib) <= firsts_a
        core = fuzz.partial_token_set_ratio(
            " ".join(phonetic_key(t) for t in fa), " ".join(phonetic_key(t) for t in fb)
        )
        if inits_ok and core >= 90:
            return {"verdict": "initial_vs_full", "score": int(core)}
    if score >= 88:
        # Guard against merging different people with similar names
        # (Rajesh/Rakesh, Arun/Varun, Kavitha/Kavya): with the same word count,
        # every word must start with the same sound and keep its consonant
        # skeleton; otherwise a human must check.
        if len(fa) == len(fb) and not _words_align(fa, fb):
            return {"verdict": "possible_match_check", "score": int(score)}
        return {"verdict": "same_name_different_spelling", "score": int(score)}
    if score >= 75:
        return {"verdict": "possible_match_check", "score": int(score)}
    return {"verdict": "different", "score": int(score)}


def token_diff(canonical: str, other: str) -> list[dict]:
    """Per-word differences, for the on-screen diff."""
    ca, ob = tokens(canonical), tokens(other)
    used, out = set(), []
    for c in ca:
        best, bi = 0, None
        for i, o in enumerate(ob):
            if i in used:
                continue
            s = fuzz.ratio(phonetic_key(c), phonetic_key(o))
            if o[0].lower() == c[0].lower() and len(o.strip(".")) == 1:
                s = max(s, 80)
            if s > best:
                best, bi = s, i
        if bi is not None and best >= 60:
            used.add(bi)
            o = ob[bi]
            out.append({"expected": c, "found": o, "same": o.lower() == c.lower()})
        else:
            # maybe joined: "Subba"+"Rao" vs "Subbarao"
            out.append({"expected": c, "found": None, "same": False})
    for i, o in enumerate(ob):
        if i not in used and not any(d["found"] == o for d in out):
            out.append({"expected": None, "found": o, "same": False})
    return out


# ------------------------------------------------------------------ spell-back
LETTER_NAMES = {
    "te": dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", [
        "ఏ", "బీ", "సీ", "డీ", "ఈ", "ఎఫ్", "జీ", "హెచ్", "ఐ", "జే", "కే", "ఎల్", "ఎమ్",
        "ఎన్", "ఓ", "పీ", "క్యూ", "ఆర్", "ఎస్", "టీ", "యూ", "వీ", "డబ్ల్యూ", "ఎక్స్", "వై", "జెడ్"])),
    "ta": dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", [
        "ஏ", "பி", "சி", "டி", "ஈ", "எஃப்", "ஜி", "ஹெச்", "ஐ", "ஜே", "கே", "எல்", "எம்",
        "என்", "ஓ", "பி", "க்யூ", "ஆர்", "எஸ்", "டி", "யூ", "வி", "டபிள்யூ", "எக்ஸ்", "ஒய்", "இசட்"])),
    "hi": dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", [
        "ए", "बी", "सी", "डी", "ई", "एफ़", "जी", "एच", "आई", "जे", "के", "एल", "एम",
        "एन", "ओ", "पी", "क्यू", "आर", "एस", "टी", "यू", "वी", "डब्ल्यू", "एक्स", "वाई", "ज़ेड"])),
    "en": {c: c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
}
WORD_SEP = {"te": "  —  ", "ta": "  —  ", "hi": "  —  ", "en": "  —  "}


def spell_back(latin: str, lang: str) -> str:
    names = LETTER_NAMES.get(lang, LETTER_NAMES["en"])
    words = []
    for w in tokens(latin):
        letters = [names.get(ch.upper(), ch) for ch in w if ch.isalpha()]
        words.append(", ".join(letters))
    return WORD_SEP.get(lang, " — ").join(words)


# ------------------------------------------------------------------ reconcile
PRIMARY_ORDER = ["identity_card", "voter_id", "ration_card", "other"]


def reconcile(docs: list[dict], field: str = "name_latin", lang: str = "te") -> dict:
    """docs: [{doc_type, label, <field>: str}]. Returns canonical + per-doc verdicts."""
    have = [d for d in docs if (d.get(field) or "").strip()]
    if not have:
        return {"field": field, "canonical": None, "variants": [], "status": "missing"}
    have.sort(key=lambda d: PRIMARY_ORDER.index(d.get("doc_type")) if d.get("doc_type") in PRIMARY_ORDER else 9)
    primary = have[0]
    canonical = primary[field].strip()
    variants, worst = [], "identical"
    rank = ["identical", "initial_vs_full", "same_name_different_spelling", "possible_match_check", "different"]
    for d in have:
        cmp = compare(canonical, d[field]) if d is not primary else {"verdict": "identical", "score": 100}
        variants.append({
            "doc_type": d.get("doc_type"), "label": d.get("label") or d.get("doc_type"),
            "value": d[field], "verdict": cmp["verdict"], "score": cmp["score"],
            "diff": token_diff(canonical, d[field]) if d is not primary else [],
            "primary": d is primary,
        })
        if rank.index(cmp["verdict"]) > rank.index(worst):
            worst = cmp["verdict"]
    status = {"identical": "consistent", "initial_vs_full": "variant", "same_name_different_spelling": "variant",
              "possible_match_check": "needs_check", "different": "conflict"}[worst]
    return {
        "field": field,
        "canonical": canonical,
        "canonical_source": primary.get("label") or primary.get("doc_type"),
        "variants": variants,
        "status": status,
        "spell_back": spell_back(canonical, lang),
    }


def compare_simple(values: list[tuple[str, str]]) -> dict:
    """For non-name fields (DOB etc.): exact compare after normalising."""
    norm = lambda v: re.sub(r"[^0-9a-z]", "", (v or "").lower())  # noqa: E731
    vals = [(lbl, v) for lbl, v in values if v]
    distinct = {norm(v) for _, v in vals}
    return {"values": [{"label": l, "value": v} for l, v in vals], "consistent": len(distinct) <= 1}
