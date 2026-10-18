"""Locust load test for the API gateway.

    make test-load
    # or: uv run locust -f tests/load/locustfile.py --host http://localhost:8000

Each simulated traveler runs a short browse -> quote -> book journey. Requires a
running gateway (``make run``).
"""

from __future__ import annotations

import random
import uuid

from locust import HttpUser, between, task

DESTINATIONS = ["Cartagena", "San Andrés", "Amazonía", "Tayrona", "Medellín"]


class TravelerUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self) -> None:
        self.handle = f"load-{uuid.uuid4()}"

    def _chat(self, text: str) -> None:
        self.client.post(
            "/chat",
            json={"text": text, "handle": self.handle},
            name="/chat",
        )

    @task(3)
    def browse(self) -> None:
        self._chat("recomiéndame un destino de playa en familia")

    @task(2)
    def quote(self) -> None:
        destination = random.choice(DESTINATIONS)
        self._chat(f"cotiza {destination} para 2 personas")

    @task(1)
    def full_journey(self) -> None:
        destination = random.choice(DESTINATIONS)
        self._chat(f"quiero viajar a {destination}")
        self._chat("cotiza para 2 personas")
        self._chat("quiero reservar")

    @task(1)
    def health(self) -> None:
        self.client.get("/health", name="/health")
