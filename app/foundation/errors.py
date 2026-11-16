class AppError(Exception):
    """Raised anywhere below the routes; rendered as JSON (API) or a page."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail
