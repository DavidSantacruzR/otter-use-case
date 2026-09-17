# Commands

Everything that was run to build, run and ship the deals dashboard, in order.

## 1. Environment

The repo already carried a `.venv`, so it was used directly rather than
recreated. From a clean checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` pins what Streamlit Community Cloud installs
(`streamlit`, `pandas`, `altair`) plus `requests` for the scraper.

## 2. Inspecting the data

Before writing any of the app, the CSV was profiled to find out what the NAs
actually mean:

```bash
.venv/bin/python -c "
import pandas as pd
d = pd.read_csv('amazon_deals.csv')
print(d.shape)
print(d.isna().sum().to_string())
print(d.category.value_counts().to_string())
print(d.deal_type.value_counts(dropna=False).to_string())
"
```

Result: 304 rows, 188 with a discount badge and 116 surfaced by the deals page
with no price or badge at all. Those 116 are kept — they still map a brand and
a category, and they are what the discount-coverage views measure.

## 3. Validating the chart palette

The eight categorical hues were checked for colorblind separation before being
written into the theme, in both modes:

```bash
node scripts/validate_palette.js "#2a78d6,#eb6834,#1baf7a,#eda100,#e87ba4,#008300,#4a3aa7,#e34948" --mode light
node scripts/validate_palette.js "#3987e5,#d95926,#199e70,#c98500,#d55181,#008300,#9085e9,#e66767" --mode dark
```

Both passed (worst adjacent CVD ΔE 9.1 light / 8.4 dark, target ≥ 8). The two
palettes live in `.streamlit/config.toml` under `chartCategoricalColors`, so
every chart in the app shares them.

## 4. Running the app locally

```bash
streamlit run streamlit_app.py
```

The exact invocation used here, pinning the port and skipping the browser
auto-open:

```bash
.venv/bin/streamlit run streamlit_app.py --server.port 8501 --server.headless true
```

Then open <http://localhost:8501>. Streamlit hot-reloads on file save.

Check whether it is already listening, and stop it:

```bash
lsof -nP -iTCP:8501 -sTCP:LISTEN
kill $(lsof -t -nP -iTCP:8501 -sTCP:LISTEN)
```

## 5. Testing it headlessly

The app was exercised end to end without a browser, using Streamlit's own test
harness — this is what caught API and empty-filter errors:

```bash
.venv/bin/python -c "
from streamlit.testing.v1 import AppTest
at = AppTest.from_file('streamlit_app.py', default_timeout=90).run()
print('exceptions:', at.exception)
print('charts:', len(at.get('vega_lite_chart')), 'tables:', len(at.dataframe))

at.segmented_control[0].set_value('Lowest price').run(); print(at.exception)
at.slider[0].set_value(80).run(); print(at.exception)
at.text_input[0].set_value('zzzz').run(); print([w.value for w in at.warning])
"
```

## 6. Refreshing the data

```bash
python main.py
```

Re-scrapes amazon.com/deals and rewrites `amazon_deals.csv`. Commit the new CSV
to update the deployed app.

## 7. Deploying to Streamlit Community Cloud

### What was done from here

`amazon_deals.csv` was gitignored, which would have crashed the deployed app on
boot — the dashboard reads it from disk. The ignore rule was removed so the
snapshot travels with the repo, and everything was committed and pushed:

```bash
git check-ignore -v amazon_deals.csv     # confirmed it was ignored
# removed the "amazon_deals.csv" line from .gitignore

git add -A
git commit -m "Add Streamlit deals dashboard"
git push origin master
```

Pushed to `git@github.com:DavidSantacruzR/otter-use-case.git`, branch `master`,
commit `ac68329`.

### What you have to do (browser, your account)

Community Cloud has no CLI or API — deploying is a browser flow tied to your
Streamlit and GitHub accounts, so this part is yours:

1. Go to <https://share.streamlit.io> and sign in with GitHub.
   Sign in as **DavidSantacruzR** — that account owns the repo. (The `gh` CLI
   here is authenticated as `david-santacruz-cleff`, which cannot see it.)
2. Click **Create app** → **Deploy a public app from GitHub**.
   If the repo is private, first use **Settings → Linked accounts** to grant
   Streamlit access to private repositories, otherwise it will not appear.
3. Fill in the form:
   - **Repository:** `DavidSantacruzR/otter-use-case`
   - **Branch:** `master`
   - **Main file path:** `streamlit_app.py`
   - **App URL:** pick a subdomain, e.g. `amazon-deals-of-the-day`
4. **Advanced settings** → set **Python version** to **3.12** (matches the local
   `.venv`; the default is older and `pandas`/`altair` resolve differently).
   No secrets are needed — the app reads a committed CSV and calls no APIs.
5. Click **Deploy**. First build takes a few minutes while it installs
   `requirements.txt`. The build log streams in the right-hand panel.

The app lands at `https://<your-subdomain>.streamlit.app`.

### After deploying

- **Updates are automatic.** Any push to `master` redeploys. To publish fresh
  data: `python main.py && git commit -am "Refresh deals snapshot" && git push`.
- **If the build fails**, read the log panel. The two likely causes are a
  missing dependency in `requirements.txt` and a `FileNotFoundError` on
  `amazon_deals.csv` (meaning it did not get committed — check
  `git ls-files amazon_deals.csv` returns the file).
- **Free-tier apps sleep** after inactivity and wake on the next visit, taking
  a few seconds on the first load.
