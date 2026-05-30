# Canadian Research Watch RSS

This repository generates an RSS feed of recent academic research by Canadian-affiliated scholars or research about Canada.

## Files

- `generate_feed.py` — queries OpenAlex, filters Canadian-relevant research and writes `docs/feed.xml`
- `requirements.txt` — Python package dependencies
- `.github/workflows/update-feed.yml` — GitHub Actions workflow that runs the script daily
- `docs/feed.xml` — generated RSS feed
- `docs/index.html` — generated human-readable page

## Setup

1. Create a new GitHub repository.
2. Upload these files, preserving the folder structure.
3. Go to **Settings → Pages**.
4. Under **Build and deployment**, choose:
   - Source: `Deploy from a branch`
   - Branch: `main`
   - Folder: `/docs`
5. Save.
6. Go to **Actions** and run `Update Canadian research RSS feed` manually once.

Your RSS feed will eventually be available at:

```text
https://YOUR-USERNAME.github.io/YOUR-REPOSITORY/feed.xml
```

## Recommended repository variables

Go to **Settings → Secrets and variables → Actions → Variables** and add:

- `OPENALEX_MAILTO` — your email address, recommended for polite OpenAlex API use
- `FEED_URL` — your final feed URL, for example:
  `https://YOUR-USERNAME.github.io/YOUR-REPOSITORY/feed.xml`

## Tuning

In `.github/workflows/update-feed.yml`, you can adjust:

- `DAYS_BACK`: how far back to scan
- `MAX_ITEMS`: maximum feed items
- `MIN_SCORE`: relevance threshold

Higher `MIN_SCORE` means fewer but more relevant results.
Lower `MIN_SCORE` means broader coverage but more false positives.

## Notes

This uses OpenAlex metadata. It is useful for discovery, but author affiliations and abstracts can be incomplete.
