# Reel production design

## Product and audience

A command-line pipeline turns a constrained strategy paper into a vertical research reel. The viewer should be able to compare the tested strategy with SPY and trace every displayed number back to the typed result. The repository guide is for someone recreating that package locally, not a fictional hosted service.

## Visual system

The existing brand tokens are authoritative in `config.yaml`: charcoal `#0E1116`, gold `#E8B923`, grey benchmark `#8A9099`, white text, green positive `#2ECC71` and red negative `#E74C3C`. Montserrat supplies headlines, Inter body text and JetBrains Mono numerical labels. The actual bundled TTFs are used by renderers; missing fonts fail rather than silently changing layout. The six TTFs are byte-verified against pinned official sources, with complete SIL OFL 1.1 notices and hashes in [the font source guide](assets/fonts/README.md). Inter Regular and Medium use the official Inter 4.1 static release; Montserrat and JetBrains Mono retain their existing verified binaries. `python tools/check_font_provenance.py` checks the retained files without network access.

The signature is a progressive equity comparison with measured final values, followed by a short statement of what the test found. Do not add decorative numbers, a claim of live trading or paper performance relabelled as observed performance.

## Frame and motion

`layout.py` partitions the 1080 x 1920 frame into title (220-480), chart/content (480-1120), statistics (1120-1330), captions (1330-1500) and watermark (1500-1600). The first 220 and last 320 pixels are reserved for platform UI. Text wrapping uses measured font widths. Captions and chart reveals share the assembly timeline; optional narration timings come from the selected engine, with proportional timing when word boundaries are unavailable.

## Release states

Rendered does not imply QC passed. A rejected package has metadata explaining its failures. A passing package gets `APPROVAL_PENDING` and still awaits a human decision. Offline runs bypass online extraction, voice providers and optional LLM fact-checking; the deterministic numerical check remains active. The package check returns nonzero if QC rejects its output.

## Verification

Run the fixture data/backtest stages, `python -m unittest discover -s tests -v`, then build the package and run the red-team checker. Compare `meta.json`, overlay values and a rendered frame, and inspect the disclaimer, glyphs, caption band and audio stream. Live provider and publication workflows require their own evidence; they are not proved by an offline MP4.

## Editorial check

Named emotions: none. Unsupported release claims: removed. Rejected phrases: "viral content engine", "effortless production", "game-changing research". The README uses actual commands and measured fixture values. Personal costs, sensory details and arbitrary numerical quotas do not fit an operational guide and were not invented. Unresolved: local neural voice models and live provider integrations are absent from the public clone.
