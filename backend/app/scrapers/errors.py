class SourceFetchError(RuntimeError):
    pass


class TransientSourceFetchError(SourceFetchError):
    """A known connection/timeout failure, not an HTTP access restriction."""


class SourceParseError(ValueError):
    pass


class InvalidRecord(ValueError):
    pass
