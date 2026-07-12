from __future__ import annotations

from pagedrop.ui.base_file_card import InternalReorderFileCard
from pagedrop.ui.theme import convert_file_card_stylesheet


class ConvertFileCard(InternalReorderFileCard):
    """Grid card for one image in the Create PDF queue."""

    def __init__(
        self,
        file_index: int,
        path: str,
        dimensions: tuple[int, int],
        parent=None,
    ) -> None:
        self.dimensions = dimensions
        width, height = dimensions
        super().__init__(
            file_index,
            path,
            f"{width} × {height}",
            object_name="ConvertFileCard",
            stylesheet_fn=convert_file_card_stylesheet,
            tooltip=f"{path}\n{width} × {height} px",
            parent=parent,
        )
