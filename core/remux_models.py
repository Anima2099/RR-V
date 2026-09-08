from __future__ import annotations

from dataclasses import dataclass


REMUX_TARGET_MKV = "mkv"
REMUX_TARGET_MP4 = "mp4"
REMUX_TARGET_MOV = "mov"
REMUX_TARGETS = (REMUX_TARGET_MKV, REMUX_TARGET_MP4, REMUX_TARGET_MOV)

REMUX_TARGET_LABELS = {
    REMUX_TARGET_MKV: "MKV",
    REMUX_TARGET_MP4: "MP4",
    REMUX_TARGET_MOV: "MOV",
}


@dataclass(slots=True, frozen=True)
class RemuxCompatibility:
    target_container: str
    supported: bool
    issues: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        if self.supported:
            return "모든 트랙을 재인코딩 없이 그대로 복사할 수 있습니다."
        if not self.issues:
            return "이 컨테이너로 Remux할 수 없습니다."
        if len(self.issues) == 1:
            return self.issues[0]
        return f"{self.issues[0]} · 외 {len(self.issues) - 1}개 문제"


@dataclass(slots=True, frozen=True)
class RemuxResult:
    output_path: str
    size_bytes: int
