"""Conversion report collection and serialization."""

from dataclasses import dataclass, field


@dataclass
class WarningEntry:
    level: str
    kind: str
    where: str
    detail: str

    def to_dict(self):
        return {
            "level": self.level,
            "kind": self.kind,
            "where": self.where,
            "detail": self.detail,
        }


@dataclass
class Report:
    source: str
    status: str = "ok"
    stats: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    headings: list = field(default_factory=list)

    def add(self, kind, where, detail, level="warn"):
        self.warnings.append(WarningEntry(level, kind, where, detail))

    def add_heading(self, level, text, source, detail, original_level=None, downgraded=False):
        self.headings.append(
            {
                "level": level,
                "original_level": original_level if original_level is not None else level,
                "text": text,
                "source": source,
                "detail": detail,
                "downgraded": downgraded,
            }
        )

    def finalize(self):
        if self.status != "error" and self.warnings:
            self.status = "warn"
        return self

    def to_dict(self):
        return {
            "source": self.source,
            "status": self.status,
            "stats": self.stats,
            "warnings": [w.to_dict() for w in self.warnings],
            "headings": self.headings,
        }

