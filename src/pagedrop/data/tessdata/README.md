# Optional OCR language pack

Place Tesseract ``*.traineddata`` files here (for example ``eng.traineddata``
from [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast)) to ship
an optional English pack with a frozen build.

PageDrop does **not** require this folder at startup. Users can also:

- Point Preferences at any tessdata directory
- Download `eng` into the per-user data folder via Preferences / the OCR configure dialog
- Set `PAGEDROP_TESSDATA` or `TESSDATA_PREFIX`

Do not commit large traineddata binaries to the repository unless deliberately
shipping an optional pack for a release.
