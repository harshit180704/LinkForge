"""Controlled local redirect benchmark for LinkForge.

Run only against your own local development instance.
"""
import os
from locust import HttpUser, between, task
from urllib.parse import urlsplit, urlunsplit

ALIAS = os.getenv("LINKFORGE_BENCHMARK_ALIAS", "benchmark-test")
EXPECTED_DESTINATION = os.getenv("LINKFORGE_BENCHMARK_DESTINATION", "https://example.com")


def normalize_destination(value: str) -> str:
    """Treat an empty URL path as /, preserving query and fragment."""
    parts = urlsplit(value)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, parts.fragment))


class RedirectUser(HttpUser):
    wait_time = between(0.5, 1.5)

    @task
    def redirect(self):
        with self.client.get(
            f"/{ALIAS}",
            allow_redirects=False,
            name="GET /{alias} (redirect)",
            catch_response=True,
            timeout=5,
        ) as response:
            if response.status_code not in (301, 302, 307, 308):
                response.failure(f"Expected redirect, got HTTP {response.status_code}")
            elif normalize_destination(response.headers.get("Location", "")) != normalize_destination(EXPECTED_DESTINATION):
                response.failure(
                    f"Unexpected Location header: {response.headers.get('Location')!r}"
                )
            else:
                response.success()
