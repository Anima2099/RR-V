from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


LANGUAGE_NAMES: dict[str, str] = {
    "ko": "한국어",
    "en": "영어",
    "en-orig": "영어 원문",
    "ja": "일본어",
    "zh": "중국어",
    "zh-hans": "중국어 간체",
    "zh-hant": "중국어 번체",
    "es": "스페인어",
    "fr": "프랑스어",
    "de": "독일어",
    "it": "이탈리아어",
    "pt": "포르투갈어",
    "pt-br": "포르투갈어 (브라질)",
    "ru": "러시아어",
    "ar": "아랍어",
    "hi": "힌디어",
    "id": "인도네시아어",
    "th": "태국어",
    "vi": "베트남어",
}

QUICK_LANGUAGE_BASES: tuple[str, ...] = ("ko", "en", "ja")


def language_base(code: str) -> str:
    return code.strip().lower().split("-", 1)[0]


def language_display_name(code: str) -> str:
    normalized = code.strip()
    lowered = normalized.lower()
    name = LANGUAGE_NAMES.get(lowered)
    if name:
        return f"{name} ({normalized})"

    base_name = LANGUAGE_NAMES.get(language_base(normalized))
    if base_name:
        return f"{base_name} ({normalized})"
    return normalized


@dataclass(slots=True, frozen=True)
class SubtitleSelection:
    manual: tuple[str, ...] = ()
    automatic: tuple[str, ...] = ()

    @property
    def encoded_tracks(self) -> tuple[str, ...]:
        return tuple(
            [f"manual:{code}" for code in self.manual]
            + [f"auto:{code}" for code in self.automatic]
        )

    @property
    def is_empty(self) -> bool:
        return not self.manual and not self.automatic

    @property
    def summary(self) -> str:
        if self.is_empty:
            return "자막 없음"

        labels = [
            language_display_name(code).rsplit(" (", 1)[0]
            for code in self.manual
        ]
        labels.extend(
            f"{language_display_name(code).rsplit(' (', 1)[0]}(자동)"
            for code in self.automatic
        )

        if len(labels) <= 2:
            return " + ".join(labels)
        return f"{labels[0]} 외 {len(labels) - 1}개"


def default_subtitle_selection(
    manual_languages: tuple[str, ...],
    automatic_languages: tuple[str, ...],
    preferred_bases: tuple[str, ...] = ("ko",),
    allow_automatic: bool = True,
) -> SubtitleSelection:
    """선호 언어를 제공 자막 우선으로 골라 기본 선택을 만든다."""
    manual: list[str] = []
    automatic: list[str] = []

    for preferred in preferred_bases:
        base = language_base(preferred)
        manual_match = next(
            (code for code in manual_languages if language_base(code) == base),
            None,
        )
        if manual_match is not None:
            if manual_match not in manual:
                manual.append(manual_match)
            continue

        if allow_automatic:
            automatic_match = next(
                (
                    code
                    for code in automatic_languages
                    if language_base(code) == base
                ),
                None,
            )
            if automatic_match is not None and automatic_match not in automatic:
                automatic.append(automatic_match)

    if manual or automatic:
        return SubtitleSelection(tuple(manual), tuple(automatic))

    if manual_languages:
        return SubtitleSelection((manual_languages[0],), ())
    if allow_automatic and automatic_languages:
        return SubtitleSelection((), (automatic_languages[0],))
    return SubtitleSelection()


class SubtitleSelectionDialog(QDialog):
    def __init__(
        self,
        manual_languages: tuple[str, ...],
        automatic_languages: tuple[str, ...],
        selected: SubtitleSelection,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("warmDialog")
        self.setWindowTitle("자막 선택")
        self.setModal(True)
        self.resize(480, 500)
        self.setMinimumSize(420, 360)
        self.setMaximumSize(560, 620)

        self.selection = selected
        self._items: list[tuple[QTreeWidgetItem, str, str]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel("받을 자막을 선택해 주세요.")
        title.setObjectName("dialogTitle")

        description = QLabel(
            "여러 언어를 함께 선택할 수 있습니다. 한국어·영어·일본어는 위쪽에 배치했습니다."
        )
        description.setObjectName("emptyDescription")
        description.setWordWrap(True)

        self.none_checkbox = QCheckBox("자막을 받지 않음")
        self.none_checkbox.setObjectName("dialogCheckBox")
        self.none_checkbox.setChecked(selected.is_empty)
        self.none_checkbox.toggled.connect(self._none_toggled)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("dialogSearchInput")
        self.search_input.setPlaceholderText("언어 이름이나 코드 검색")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._filter_items)

        self.tree = QTreeWidget()
        self.tree.setObjectName("subtitleTree")
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAnimated(False)

        quick_manual = tuple(
            code
            for code in manual_languages
            if language_base(code) in QUICK_LANGUAGE_BASES
        )
        quick_automatic = tuple(
            code
            for code in automatic_languages
            if language_base(code) in QUICK_LANGUAGE_BASES
        )
        remaining_manual = tuple(
            code for code in manual_languages if code not in quick_manual
        )
        remaining_automatic = tuple(
            code for code in automatic_languages if code not in quick_automatic
        )

        quick_root = self._add_mixed_group(
            "자주 쓰는 언어",
            quick_manual,
            quick_automatic,
            selected,
        )
        manual_root = self._add_group(
            f"직접 제공된 자막  {len(remaining_manual)}개",
            "manual",
            remaining_manual,
            set(selected.manual),
        )
        automatic_root = self._add_group(
            f"자동 생성 자막  {len(remaining_automatic)}개",
            "auto",
            remaining_automatic,
            set(selected.automatic),
        )

        if quick_root is not None:
            quick_root.setExpanded(True)
        if manual_root is not None:
            manual_root.setExpanded(True)
        if automatic_root is not None:
            automatic_root.setExpanded(False)

        if not manual_languages and not automatic_languages:
            empty_item = QTreeWidgetItem(
                ["이 영상에서 선택 가능한 자막을 찾지 못했습니다."]
            )
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.tree.addTopLevelItem(empty_item)

        button_row = QHBoxLayout()
        button_row.addStretch()

        cancel_button = QPushButton("취소")
        cancel_button.setObjectName("smallSecondaryButton")
        cancel_button.clicked.connect(self.reject)

        apply_button = QPushButton("적용")
        apply_button.setObjectName("primaryButton")
        apply_button.clicked.connect(self._apply)

        button_row.addWidget(cancel_button)
        button_row.addWidget(apply_button)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(self.none_checkbox)
        layout.addWidget(self.search_input)
        layout.addWidget(self.tree, 1)
        layout.addLayout(button_row)

        self._none_toggled(self.none_checkbox.isChecked())

    def _add_mixed_group(
        self,
        label: str,
        manual_languages: tuple[str, ...],
        automatic_languages: tuple[str, ...],
        selected: SubtitleSelection,
    ) -> QTreeWidgetItem | None:
        if not manual_languages and not automatic_languages:
            return None

        root = QTreeWidgetItem([label])
        root.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.tree.addTopLevelItem(root)

        priority = {base: index for index, base in enumerate(QUICK_LANGUAGE_BASES)}
        entries: list[tuple[str, str]] = [
            ("manual", code) for code in manual_languages
        ] + [("auto", code) for code in automatic_languages]
        entries.sort(
            key=lambda item: (
                priority.get(language_base(item[1]), 99),
                0 if item[0] == "manual" else 1,
                item[1].lower(),
            )
        )

        for kind, code in entries:
            suffix = "제공" if kind == "manual" else "자동"
            child = self._create_language_item(
                f"{language_display_name(code)} · {suffix}",
                kind,
                code,
                code in (selected.manual if kind == "manual" else selected.automatic),
            )
            root.addChild(child)
        return root

    def _add_group(
        self,
        label: str,
        kind: str,
        languages: tuple[str, ...],
        selected_codes: set[str],
    ) -> QTreeWidgetItem | None:
        if not languages:
            return None

        root = QTreeWidgetItem([label])
        root.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.tree.addTopLevelItem(root)

        for code in sorted(languages, key=lambda item: language_display_name(item)):
            child = self._create_language_item(
                language_display_name(code),
                kind,
                code,
                code in selected_codes,
            )
            root.addChild(child)
        return root

    def _create_language_item(
        self,
        text: str,
        kind: str,
        code: str,
        checked: bool,
    ) -> QTreeWidgetItem:
        child = QTreeWidgetItem([text])
        child.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable
        )
        child.setCheckState(
            0,
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked,
        )
        self._items.append((child, kind, code))
        return child

    def _none_toggled(self, checked: bool) -> None:
        self.search_input.setEnabled(not checked)
        self.tree.setEnabled(not checked)
        if checked:
            for item, _kind, _code in self._items:
                item.setCheckState(0, Qt.CheckState.Unchecked)

    def _filter_items(self, text: str) -> None:
        query = text.strip().lower()
        for item, _kind, code in self._items:
            visible = (
                not query
                or query in item.text(0).lower()
                or query in code.lower()
            )
            item.setHidden(not visible)

        for index in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(index)
            if root.childCount() == 0:
                continue
            root_visible = any(
                not root.child(child_index).isHidden()
                for child_index in range(root.childCount())
            )
            root.setHidden(bool(query) and not root_visible)
            if query and root_visible:
                root.setExpanded(True)

    def _apply(self) -> None:
        if self.none_checkbox.isChecked():
            self.selection = SubtitleSelection()
            self.accept()
            return

        manual: list[str] = []
        automatic: list[str] = []
        for item, kind, code in self._items:
            if item.checkState(0) != Qt.CheckState.Checked:
                continue
            if kind == "manual":
                manual.append(code)
            else:
                automatic.append(code)

        self.selection = SubtitleSelection(tuple(manual), tuple(automatic))
        self.accept()


def select_subtitles(
    manual_languages: tuple[str, ...],
    automatic_languages: tuple[str, ...],
    selected: SubtitleSelection,
    parent: QWidget | None = None,
) -> SubtitleSelection | None:
    dialog = SubtitleSelectionDialog(
        manual_languages,
        automatic_languages,
        selected,
        parent,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.selection
