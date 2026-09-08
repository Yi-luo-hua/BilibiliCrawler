"""A failed crawl can still own usable records from completed pages."""


class CrawlError(RuntimeError):
    def __init__(self, message: str, records: list[dict] | None = None):
        super().__init__(message)
        self.records = records if records is not None else []
