"""What every notification channel has to provide."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from vinted_sniper.db.repo import PendingNotification
from vinted_sniper.deals import TIERS, Tier


@dataclass(frozen=True, slots=True)
class SendResult:
    """How a send went, in the terms the dispatcher needs to act on."""

    delivered: list[int] = field(default_factory=list)
    retry: list[int] = field(default_factory=list)
    retry_after_s: float | None = None
    permanent_error: str | None = None
    error: str | None = None
    pause_all_for_s: float | None = None

    @classmethod
    def ok(cls, outbox_ids: list[int]) -> SendResult:
        return cls(delivered=outbox_ids)

    @classmethod
    def transient(
        cls, outbox_ids: list[int], error: str, retry_after_s: float | None = None
    ) -> SendResult:
        return cls(delivered=[], retry=outbox_ids, retry_after_s=retry_after_s, error=error)

    @classmethod
    def gone(cls, reason: str) -> SendResult:
        """The destination itself is finished: deleted webhook, blocked bot, wrong chat.

        Retrying these is worse than useless — the rejections count against the allowance
        that keeps the rest of your notifications flowing.
        """
        return cls(delivered=[], permanent_error=reason)


class Sender(Protocol):
    """One notification channel."""

    kind: str

    @property
    def max_batch(self) -> int:
        """How many notifications this channel can take in one go."""
        ...

    async def send(self, batch: list[PendingNotification]) -> SendResult: ...

    async def send_status(self, message: str) -> None:
        """Deliver an operational notice — a warning, a startup message."""
        ...

    async def aclose(self) -> None: ...


class SenderConfigError(ValueError):
    """A destination is missing something it needs, such as a webhook URL."""


def require(config: dict[str, Any], key: str, kind: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SenderConfigError(f"{kind} destination needs a {key!r}")
    return value.strip()


def parse_tiers(config: dict[str, Any], key: str, default: tuple[Tier, ...]) -> frozenset[Tier]:
    """A destination's list of deal tiers ("steal", "deal", "normal") under `key`."""
    raw = config.get(key)
    if raw is None:
        return frozenset(default)
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",") if part.strip()]
    if not isinstance(raw, list):
        raise SenderConfigError(f"{key} must be a list of tiers: steal, deal, normal")
    tiers: set[Tier] = set()
    for value in raw:
        tier = next((known for known in TIERS if known == str(value).strip().lower()), None)
        if tier is None:
            raise SenderConfigError(f"{key} can only hold steal, deal and normal, not {value!r}")
        tiers.add(tier)
    return frozenset(tiers)
