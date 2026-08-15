from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QSpinBox,
    QVBoxLayout,
)


class NoWheelComboBox(QComboBox):
    """닫힌 상태에서는 마우스 휠로 값이 바뀌지 않는 콤보박스."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        # 팝업 목록이 열려 있으면 목록 안의 휠 스크롤은 그대로 허용한다.
        if self.view().isVisible():
            super().wheelEvent(event)
            return

        # 닫힌 상태에서는 선택값을 바꾸지 않고 부모 스크롤 영역에 넘긴다.
        event.ignore()


class NoWheelSpinBox(QSpinBox):
    """포커스가 있어도 마우스 휠로 값이 바뀌지 않는 스핀박스."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """포커스가 있어도 마우스 휠로 값이 바뀌지 않는 더블 스핀박스."""

    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


def create_card() -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("card")

    layout = QVBoxLayout(card)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)

    return card, layout
