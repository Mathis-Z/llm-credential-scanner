# Database models for scanner: Service (discovered HTTP services) and Endpoint (URL paths).

import json
import peewee as pw

from .db import BaseModel

# Common credentials always tested when no service-specific creds are found
DEFAULT_CREDS = [('admin', 'admin'), ('admin', 'password'), ('username', 'password')]


class Service(BaseModel):
    """
    Represents a discovered HTTP/HTTPS service.
    
    Created by NetScanner when HTTP/HTTPS is detected on a host:port.
    Each service has associated endpoints discovered by WebEnumerator.
    """
    pk = pw.AutoField()
    host = pw.CharField(max_length=64)
    port = pw.IntegerField()
    https = pw.BooleanField()
    webenum_done = pw.BooleanField(default=False)
    keyword_extraction_done = pw.BooleanField(default=False)
    _credentials = pw.TextField(null=True, default=None)  # JSON list of (user, pass) tuples

    class Meta:
        constraints = [pw.SQL('UNIQUE (host, port)')]

    def url(self):
        """Construct full URL for this service."""
        protocol = 'https' if self.https else 'http'
        return f"{protocol}://{self.host}:{self.port}"

    def __str__(self):
        return self.url()

    @property
    def credentials(self):
        """Parse JSON credentials into list of (user, pass) tuples."""
        return [tuple(cred_pair) for cred_pair in json.loads(self._credentials)] if self._credentials else None

    @credentials.setter
    def credentials(self, new_value):
        self._credentials = json.dumps(new_value)

    def add_credentials(self, creds: tuple[str, str]):
        """Add credential pair to service, deduplicating existing entries."""
        existing = json.loads(self._credentials or '[]')
        normalized = [tuple(pair) for pair in existing] + [tuple(creds)]
        self.credentials = list(set(normalized))

    def gather_keywords(self):
        """Collect all keywords from endpoints for web search."""
        keywords = set()
        for endpoint in self.endpoints: # pylint: disable=E1101
            keywords = keywords.union(set(endpoint.keywords or []))
        return list(keywords)

    def endpoint_with_working_creds_found(self):
        """Check if any endpoint of this service has verified working credentials."""
        return self.endpoints.where(Endpoint.working_credentials != '').count() > 0


class Endpoint(BaseModel):
    """
    Represents a discovered URL path on a service.
    
    Created by WebEnumerator for paths returning non-error status codes.
    Contains page content and tracks login panel status and tested credentials.
    """
    pk = pw.AutoField()
    service = pw.ForeignKeyField(Service, backref='endpoints')
    path = pw.CharField()
    initial_path = pw.CharField()  # Path before redirects (for deduplication)
    is_login = pw.BooleanField(default=False)  # True if page has password input
    page_source = pw.TextField()  # Raw HTML content
    md_hash = pw.CharField(max_length=32)  # MD5 of markdownified content for deduplication
    _keywords = pw.TextField(null=True, default=None)  # LLM-extracted search keywords
    _tested_credentials = pw.TextField(default="[]")  # JSON list of tested (user, pass)
    working_credentials = pw.CharField(default="")  # Verified working creds (user:pass format)

    class Meta:
        constraints = [pw.SQL('UNIQUE (service_id, path)')]

    def url(self):
        """Construct full URL for this endpoint."""
        return f"{self.service.url()}/{str(self.path).lstrip('/')}"

    @property
    def keywords(self):
        """Parse JSON keywords into list."""
        return json.loads(self._keywords) if self._keywords else None

    @keywords.setter
    def keywords(self, value: list[str]):
        self._keywords = json.dumps(value)

    @property
    def tested_credentials(self):
        """Parse JSON tested credentials into list of (user, pass) tuples."""
        return [tuple(cred_pair) for cred_pair in json.loads(self._tested_credentials)]

    @tested_credentials.setter
    def tested_credentials(self, new_value):
        self._tested_credentials = json.dumps(new_value)

    def add_tested_credentials(self, creds_pair):
        """Mark credential pair as tested."""
        self.tested_credentials = list(set(self.tested_credentials + [creds_pair]))

    def untested_credentials(self):
        """
        Return credentials that haven't been tested yet on this login panel.
        
        Uses service-specific credentials if found, otherwise falls back to DEFAULT_CREDS.
        """
        if self.is_login:
            return list(set(self.service.credentials or DEFAULT_CREDS) - set(self.tested_credentials))
        else:
            return []
