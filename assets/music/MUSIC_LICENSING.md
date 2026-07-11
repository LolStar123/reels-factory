# Music licensing

Nothing copyrighted is bundled. Every file in this folder must be cleared for commercial use.

## Bundled now
- `ambient_tech_85bpm_synth.wav`- **synthesized from scratch with numpy on 2026-07-11** (A-minor pad progression, sub pulse, 85 BPM, 45.2s, loopable). It is our own work by construction- zero licensing risk. It is the bundled sample bed that makes `--dry-run` fully self-contained.

## Where to add better beds (all cleared/free tiers)
- **YouTube Audio Library** (free, check per-track attribution flag)
- **Pixabay Music** (free, no attribution)
- **Uppbeat** (free tier w/ credit)
- **Free Music Archive** (check per-track CC licence)
- Epidemic Sound / Artlist if a paid sub exists

Drop `.wav`/`.mp3` files here; `audio.py` picks per-reel deterministically (hash of slug) filtered by `music.mood` + `music.bpm_range` from config. Name files `<mood>_<bpm>bpm_<name>.<ext>` so the picker can filter without an ID3 reader.

## The trending-audio layer
IG catalogue audio (e.g. the Succession theme for @priced.in) is added **manually in the IG app at post time**- it legally cannot be baked into the exported mp4. `caption.txt` carries the suggested pick per reel (module 21).
