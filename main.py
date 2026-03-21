name: AffanMarvel Auto-Poster

on:
  workflow_dispatch:

jobs:
  autopost:
    runs-on: ubuntu-latest

    permissions:
      contents: write

    steps:

      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install Python dependencies
        run: |
          pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run AffanMarvel Auto-Poster
        env:
          GROQ_API_KEY:     ${{ secrets.GROQ_API_KEY }}
          WP_URL:           ${{ secrets.WP_URL }}
          WP_USERNAME:      ${{ secrets.WP_USERNAME }}
          WP_APP_PASSWORD:  ${{ secrets.WP_APP_PASSWORD }}
        run: python main.py

      - name: Commit updated posted_urls.txt back to repo
        run: |
          git config user.name  "affanmarvel-bot"
          git config user.email "bot@affanmarvel.in"
          git add posted_urls.txt
          git diff --staged --quiet || git commit -m "chore: update posted URLs tracker [skip ci]"
          git push
