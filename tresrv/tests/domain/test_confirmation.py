from tresrv.domain.confirmation import needs_confirmation


def test_low_confidence_needs_confirmation():
    assert needs_confirmation(0.5, 400, "text", "kanapka") is True


def test_high_confidence_text_no_confirmation():
    assert needs_confirmation(0.9, 400, "text", "kanapka") is False


def test_none_confidence_needs_confirmation():
    assert needs_confirmation(None, 400, "text", "kanapka") is True


def test_very_large_kcal_needs_confirmation_even_with_high_confidence():
    assert needs_confirmation(0.95, 1500, "text", "wielka pizza") is True


def test_photo_without_gramature_needs_confirmation():
    assert needs_confirmation(0.9, 500, "photo", "kurczak z ryżem i warzywami") is True


def test_photo_with_gramature_no_confirmation():
    assert needs_confirmation(0.9, 500, "photo", "200g kurczaka, 150g ryżu") is False
