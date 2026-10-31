"""Business identity validation shared by ingestion and public handoff."""


def validate_identity(business_id, version):
    for name, value in (("business_id", business_id), ("version", version)):
        if value is None:
            continue
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a nonempty string or None")
        if not value.strip():
            raise ValueError(f"{name} must be a nonempty string or None")
