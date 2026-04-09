import pytest
from memory.episodic import EpisodicMemory, compute_weight


@pytest.fixture
def episodic():
    """Create EpisodicMemory with mock pool (no real DB needed for unit tests)."""
    return EpisodicMemory(pool=None, embedder=None)


def test_confidence_gate_below():
    """Patterns with confidence < 0.5 should be rejected."""
    assert EpisodicMemory.should_store(confidence=0.3) == False


def test_confidence_gate_needs_review():
    """Patterns with confidence 0.5-0.7 should be stored with needs_review."""
    store, review = EpisodicMemory.should_store_with_review(confidence=0.6)
    assert store == True
    assert review == True


def test_confidence_gate_auto_approve():
    """Patterns with confidence > 0.7 should be auto-approved."""
    store, review = EpisodicMemory.should_store_with_review(confidence=0.8)
    assert store == True
    assert review == False


def test_weight_calculation():
    """Test weighted score calculation for retrieval."""
    # Verified, recent, high success → high weight
    w1 = compute_weight(
        confidence=0.9, verified=True, times_applied=5,
        times_failed=0, source="user-correction", days_old=1,
    )

    # Unverified, old, low success → low weight
    w2 = compute_weight(
        confidence=0.5, verified=False, times_applied=1,
        times_failed=3, source="auto-bootstrap", days_old=60,
    )

    assert w1 > w2
