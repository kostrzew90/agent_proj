_GRAMATURE_UNITS = ("g", "gram", "ml", "szt")


def needs_confirmation(
    confidence: float | None, kcal: float | None,
    raw_input_type: str, opis: str | None,
) -> bool:
    if confidence is None or confidence < 0.7:
        return True
    if kcal is not None and kcal > 1200:
        return True
    if raw_input_type == "photo" and not _has_gramature(opis):
        return True
    return False


def _has_gramature(opis: str | None) -> bool:
    if not opis:
        return False
    lowered = opis.lower()
    return any(unit in lowered for unit in _GRAMATURE_UNITS)
