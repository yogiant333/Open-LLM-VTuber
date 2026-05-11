import pytest


@pytest.fixture(autouse=True)
def _reset_loguru():
    """Avoid loguru sinks leaking between tests."""
    from loguru import logger

    yield
    # Remove every sink added by tests; restore default sink.
    logger.remove()
    logger.add(lambda msg: None, level="WARNING")
