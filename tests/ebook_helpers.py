from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image


def make_fb2(path: Path) -> None:
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(stream, format="PNG")
    image = base64.b64encode(stream.getvalue()).decode("ascii")
    path.write_text(
        f"""<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"
 xmlns:xlink="http://www.w3.org/1999/xlink">
  <description>
    <title-info>
      <author><first-name>Ivan</first-name><last-name>Author</last-name></author>
      <book-title>Test Book</book-title><lang>en</lang>
      <coverpage><image xlink:href="#cover.png"/></coverpage>
    </title-info>
    <document-info><id>id-1</id></document-info>
  </description>
  <body><section><title><p>Chapter One</p></title><p>Hello book.</p>
    <image xlink:href="#cover.png"/>
  </section></body>
  <binary id="cover.png" content-type="image/png">{image}</binary>
</FictionBook>""",
        encoding="utf-8",
    )
