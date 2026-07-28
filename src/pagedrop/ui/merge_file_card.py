from __future__ import annotations

from pagedrop.ui.base_file_card import InternalReorderFileCard


class MergeFileCard(InternalReorderFileCard):
    """Grid card for one PDF in the merge queue."""

    def __init__(
        self,
        file_index: int,
        path: str,
        page_count: int,
        parent=None,
    ) -> None:
        self.page_count = page_count
        noun = "page" if page_count == 1 else "pages"
        super().__init__(
            file_index,
            path,
            f"{page_count} {noun}",
            object_name="MergeFileCard",
            tooltip=path,
            parent=parent,
        )
