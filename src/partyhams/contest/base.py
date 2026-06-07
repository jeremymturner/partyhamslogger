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


@dataclass(frozen=True)
class ConfigField:
    """A per-station setup field for the log-creation screen beyond the exchange.

    ``choices`` of ``(label, value)`` pairs renders a dropdown; ``None`` is a text
    field. Collected into :attr:`ContestConfig.extra` (e.g. Field Day power).
    """

    name: str
    label: str
    choices: tuple[tuple[str, str], ...] | None = None
    default: str = ""


@dataclass
class Macro:
    """One F-key message. For CW/digital ``content`` is text (with ``{VAR}``
    substitutions); for phone it's a ``.wav`` file path."""

    key: int  # 1..12
    label: str
    content: str


def _macros(specs: list[tuple[str, str]]) -> list[Macro]:
    """Build a 12-key bank from ``(label, content)`` pairs (fresh Macro objects)."""
    return [Macro(i + 1, label, content) for i, (label, content) in enumerate(specs)]


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
    #: Cabrillo ``CONTEST:`` identifier, e.g. ``"ARRL-FD"``.
    cabrillo_name: str = ""
    #: Whether a signal report (RST) is part of the exchange. Field Day = False.
    exchanges_rst: bool = True
    #: UI label for this contest's multipliers (e.g. "Zones", "Sections").
    mult_label: str = "Mults"

    # --- F-key macros ---
    def default_macros(self) -> dict[str, list[Macro]]:
        """Default F-key messages, keyed by bank ("CW.RUN", "CW.SP", "PHONE.RUN",
        "PHONE.SP"). Separate Run and S&P banks per mode group, N1MM-style.

        CW content uses ``{VAR}`` substitutions (``{MYCALL}``, ``{CALL}``,
        ``{EXCH}``, ``{LOG}``, ``{WIPE}``, …); phone content is a ``.wav`` path.
        Contests override this with event-specific wording (Field Day does).
        """
        cw_run = [
            ("CQ", "CQ {MYCALL} {MYCALL}"),
            ("Exch", "{EXCH}"),
            ("TU", "TU {MYCALL} {LOG}"),
            ("MyCall", "{MYCALL}"),
            ("HisCall", "{CALL}"),
            ("Repeat", "{EXCH} {EXCH}"),
            ("", ""),
            ("Agn?", "AGN?"),
            ("Nr?", "NR?"),
            ("Call?", "CL?"),
            ("", ""),
            ("Wipe", "{WIPE}"),
        ]
        cw_sp = list(cw_run)
        cw_sp[2] = ("TU", "TU {LOG}")  # S&P: a brief TU
        phone = [("CQ", ""), ("Exch", ""), ("TU", ""), ("QRZ", ""), *[("", "")] * 8]
        return {
            "CW.RUN": _macros(cw_run),
            "CW.SP": _macros(cw_sp),
            "PHONE.RUN": _macros(phone),
            "PHONE.SP": _macros(phone),
        }

    # --- setup / exchange ---
    def config_fields(self) -> list[ConfigField]:
        """Extra per-station setup fields for the log-creation screen.

        Default: none. Field Day adds a power category here. The operator's own
        exchange (e.g. class/section) comes from :meth:`exchange_fields`.
        """
        return []

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

        These are *tracked* for the worked-mult counter and the new-multiplier
        highlight in the entry window. Whether they actually multiply the score is
        up to :meth:`score` — e.g. Field Day exposes sections here (so working a
        new one lights up) but its score doesn't multiply by them. ``mult_type``
        should match the exchange field name where applicable, so the UI can tint
        the right field. Default: none.
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
