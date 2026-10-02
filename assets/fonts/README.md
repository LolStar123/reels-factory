# Bundled fonts

These six TTF files use the SIL Open Font License 1.1. They come from the font projects below, not a Windows font installation. Keep the full copyright and licence notices beside the font files when copying this directory.

| Family and use | Verified source | Retained licence |
|---|---|---|
| Montserrat 9.000: SemiBold and ExtraBold headlines | [Official source at 555facf](https://github.com/JulietaUla/Montserrat/tree/555facfb2a18c72c3c0380f0d9c0f060453a9058/fonts/ttf) | [Montserrat-OFL.txt](Montserrat-OFL.txt) |
| Inter: Regular and Medium body text | [Official Inter 4.1 release](https://github.com/rsms/inter/releases/tag/v4.1), `extras/ttf/` | [Inter-OFL.txt](Inter-OFL.txt) |
| JetBrains Mono 2.305: Regular and Bold numbers | [Official source at 1937130](https://github.com/JetBrains/JetBrainsMono/tree/19371302b95d218af43299bce79ddbddd0bc364d/fonts/ttf) | [JetBrainsMono-OFL.txt](JetBrainsMono-OFL.txt) |

Each bundled binary was compared byte for byte with its official source on 2 October 2026. [provenance.json](provenance.json) records the complete source revisions and URLs, binary SHA-256 hashes, embedded copyright/version strings and exact licence-file hashes. Inter's release is named 4.1; the TTF metadata reports `Version 4.001;git-9221beed3`. Its source archive hash and member paths are included in the receipt.

`.gitattributes` preserves the upstream licence bytes across Windows checkouts, including their original line endings and trailing whitespace. That keeps the retained licence hashes meaningful without editing the notices.

The Montserrat and JetBrains Mono binaries are unchanged. Inter Regular and Medium were refreshed from the official release so their provenance is exact; their family and weight roles remain the same. No font was converted, subsetted or modified after download.

From the repository root, run:

```sh
python tools/check_font_provenance.py
```

This offline check verifies that every TTF and retained notice still matches the recorded hash. A font update must also update its source receipt and complete licence text, then pass the reel's offline package and render checks. The repository's MIT licence covers its code; it does not replace these font licences.
