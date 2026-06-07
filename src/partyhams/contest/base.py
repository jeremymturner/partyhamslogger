"""The contest abstraction every contest module implements.

The design goal (decision #13): a new contest is a *data-driven definition*, not
new engine code. A :class:`ContestDefinition` declares its exchange schema, legal
bands, dupe rule, per-QSO points, multipliers, scoring, and Cabrillo mapping. The
logging core calls these hooks; it never hard-codes any contest's rules.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from partyhams.core.models import QSO


@dataclass(frozen=True)
class ExchangeField:
    """One field in a contest's received exchange (drives the entry UI + parsing)."""

    name: str  # machine key, e.g. "section"
    label: str  # UI label, e.g. "Section"
    required: bool = True
    # Optional validator; returns True if the raw string is acceptable.
    validator: Callable[[str], bool] | None = None


@dataclass
class ContestConfig:
    """Per-station, per-event settings the operator fills in before logging.

    ``sent_exchange`` holds this station's fixed sent fields (e.g. Field Day
    ``{"class": "3A", "section": "OR"}``). ``extra`` carries contest-specific
    config such as a power category.
    """

    my_call: str = ""
    sent_exchange: dict[str, str] = field(default_factory=dict)
    extra: dict[str, object] = field(default_factory=dict)


@dataclass
class ScoreSummary:
    """The result of scoring a log. Contests may attach detail in ``breakdown``."""

    qso_count: int = 0
    qso_points: int = 0
    mult_count: int = 0
    bonus_points: int = 0
    total: int = 0
    breakdown: dict[str, object] = field(default_factory=dict)


class ContestDefinition(ABC):
    """Base class for a contest module. Subclasses are stateless rule sets."""

    #: Stable machine id, e.g. ``"arrl-field-day"``.
    id: str = ""
    #: Human-readable name shown in the UI.
    name: str = ""

    # --- exchange ---
    @abstractmethod
    def exchange_fields(self) -> list[ExchangeField]:
        """Ordered received-exchange fields (excludes RST, which is universal)."""

    def parse_exchange(self, raw: str) -> dict[str, str]:
        """Parse a typed exchange string into ``{field_name: value}``.

        Default: whitespace-split positionally onto ``exchange_fields()``.
        Contests with fused fields (e.g. Sweepstakes) override this.
        """
        tokens = raw.upper().split()
        fields = self.exchange_fields()
        if len(tokens) < sum(1 for f in fields if f.required):
            raise ValueError(f"exchange '{raw}' has too few fields for {self.id}")
        out: dict[str, str] = {}
        for fld, tok in zip(fields, tokens, strict=False):
            out[fld.name] = tok
        return out

    # --- validity & dupes ---
    @abstractmethod
    def allowed_bands(self) -> set[str]:
        """Set of band labels legal for this contest (e.g. excludes WARC)."""

    @abstractmethod
    def dupe_key(self, qso: QSO) -> tuple:
        """The key two QSOs share iff they are dupes of each other."""

    # --- scoring ---
    @abstractmethod
    def qso_points(self, qso: QSO) -> int:
        """Point value of a single (non-dupe) QSO."""

    def multipliers(self, qso: QSO) -> set[tuple[str, str]]:
        """Multipliers credited by this QSO as ``(mult_type, value)`` pairs.

        Default: none. Mult-bearing contests (CQ WW, WPX) override this.
        """
        return set()

    def score(self, qsos: Iterable[QSO], config: ContestConfig) -> ScoreSummary:
        """Aggregate a full log into a :class:`ScoreSummary`.

        Default model: ``total = qso_points * unique_multipliers``. Contests with a
        different formula (Field Day's power multiplier + bonuses) override this.
        """
        seen_dupes: set[tuple] = set()
        mults: set[tuple[str, str]] = set()
        qso_count = 0
        points = 0
        for q in qsos:
            if q.deleted:
                continue
            key = self.dupe_key(q)
            if key in seen_dupes:
                continue
            seen_dupes.add(key)
            qso_count += 1
            points += self.qso_points(q)
            mults |= self.multipliers(q)
        mult_count = len(mults)
        return ScoreSummary(
            qso_count=qso_count,
            qso_points=points,
            mult_count=mult_count,
            total=points * mult_count if mult_count else points,
        )

    # --- export ---
    @abstractmethod
    def cabrillo_qso_line(self, qso: QSO, config: ContestConfig) -> str:
        """Render a single QSO as a Cabrillo ``QSO:`` line."""
