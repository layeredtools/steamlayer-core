import logging

STOP_WORDS = {"the", "a", "an", "of", "in", "and", "or", "for"}


def configure_logging():
    logger = logging.getLogger("steamlayer_core")
    logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler()
    dt_fmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter("[{asctime}] [{levelname:<8}] {name}: {message}", dt_fmt, style="{")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def meaningful_tokens(tokens: set[str]) -> set[str]:
    return {w for w in tokens - STOP_WORDS if not w.isdigit() and len(w) > 1}
