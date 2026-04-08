import json
from django.contrib.postgres.fields import JSONField as PGJSONField


class JSONField(PGJSONField):
    """JSONField that works with both PostgreSQL (production) and SQLite (tests)."""

    def get_prep_value(self, value):
        if value is None:
            return None
        # Always return a plain JSON string; PostgreSQL accepts this fine
        # and SQLite can handle strings (unlike PG's JsonAdapter object)
        return json.dumps(value)

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        # PostgreSQL may return a dict/list already; SQLite returns a string
        if isinstance(value, (dict, list, int, float, bool)):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
