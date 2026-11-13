# README artwork

Text is converted to outlines because GitHub shows README SVGs as images, where web fonts don't load.
The fonts are macOS system fonts (Futura Condensed ExtraBold, DIN Condensed Bold, Menlo).

```bash
cd .github/assets/generate
for l in en ru; do uv run --with fonttools python banner.py $l; done
uv run --with fonttools python flow.py
mv banner-*.svg flow-*-*.svg ..
```
