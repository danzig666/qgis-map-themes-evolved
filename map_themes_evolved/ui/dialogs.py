"""Name dialogs with inline validation and folder autocomplete."""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                                 QVBoxLayout)

from ..core import paths
from .common import tr

_ERROR_STYLE = "color: #c0392b;"
_WARN_STYLE = "color: #b9770e;"
_INFO_STYLE = "color: palette(mid);"


def _folder_combo(service, parent):
    combo = QComboBox(parent)
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    sep, spaced = service.separator, service.spaced
    combo.addItem("")
    for f in sorted(service.folders(), key=lambda f: [paths.natural_key(s) for s in f]):
        combo.addItem(paths.format_folder(f, sep, spaced))
    combo.lineEdit().setPlaceholderText(tr("(top level)"))
    completer = combo.completer()
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    combo.setMinimumContentsLength(30)
    return combo


class _BaseDialog(QDialog):
    def __init__(self, parent, title, ok_text):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.layout_ = QVBoxLayout(self)
        self.form = QFormLayout()
        self.layout_.addLayout(self.form)
        self.preview = QLabel(self)
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message = QLabel(self)
        self.message.setWordWrap(True)
        self.layout_.addWidget(self.preview)
        self.layout_.addWidget(self.message)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.ok_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_text:
            self.ok_button.setText(ok_text)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.layout_.addWidget(self.buttons)
        self.setMinimumWidth(460)

    def _show(self, error=None, warning=None, info=None):
        if error:
            self.message.setStyleSheet(_ERROR_STYLE)
            self.message.setText(error)
        elif warning:
            self.message.setStyleSheet(_WARN_STYLE)
            self.message.setText(warning)
        else:
            self.message.setStyleSheet(_INFO_STYLE)
            self.message.setText(info or "")
        self.ok_button.setEnabled(not error)


class FolderDialog(_BaseDialog):
    """New subfolder, or rename/move a whole folder."""

    def __init__(self, parent, service, title, initial_folder=(), old_folder=None, ok_text=None,
                 allow_existing=False):
        super().__init__(parent, title, ok_text)
        self.service = service
        self.allow_existing = allow_existing
        self.sep = service.separator
        self.spaced = service.spaced
        self.old_folder = tuple(old_folder) if old_folder is not None else None
        self.names = service.names()

        self.path_combo = _folder_combo(service, self)
        text = paths.format_folder(initial_folder, self.sep, self.spaced)
        if self.old_folder is None and text:
            text += f" {self.sep} " if self.spaced else self.sep
        self.path_combo.setEditText(text)
        self.form.addRow(tr("Folder path"), self.path_combo)
        self.path_combo.editTextChanged.connect(self._validate)
        self._validate()
        self.path_combo.setFocus()
        if self.old_folder is not None:
            self.path_combo.lineEdit().selectAll()
        else:
            self.path_combo.lineEdit().end(False)

    def folder(self):
        text = self.path_combo.currentText().strip()
        return tuple(paths.split_path(text, self.sep)) if text else ()

    def mapping(self):
        if self.old_folder is None:
            return {}
        return paths.plan_folder_rename(self.names, self.old_folder, self.folder(),
                                        self.sep, self.spaced)

    def _validate(self, *args):
        text = self.path_combo.currentText()
        error = info = None
        if not text.strip():
            error = tr("Enter a folder path.")
        else:
            error = paths.validate_name(text, set(), self.sep)
        folder = self.folder()
        if not error:
            if self.old_folder is None:
                if folder in self.service.folders():
                    if self.allow_existing:
                        info = tr("The items will be moved into this existing folder.")
                    else:
                        error = tr("This folder already exists.")
            elif folder == self.old_folder:
                error = tr("The folder path is unchanged.")
            else:
                mapping = self.mapping()
                error = paths.check_batch(mapping, set(self.names), self.sep)
                if not error:
                    info = tr("{} theme(s) will be renamed.").format(len(mapping))
        self.preview.setText(tr("Folder: <b>{}</b>").format(
            _esc(paths.format_folder(folder, self.sep, True))) if folder else "")
        self._show(error=error, info=info)


def _esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
