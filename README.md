# your_finance_brother study book

A page that lists every reel from [@your_finance_brother](https://www.instagram.com/your_finance_brother/), sorted into topics like interviews, Excel and life on the job. Each row links to the reel and shows what he said: the caption for now, and the transcript once there is one. A GitHub Action checks Instagram every morning and adds his new reels on its own.

The page looks like an Excel workbook. Each topic is a sheet tab at the bottom, the formula bar at the top searches everything he said, and the Text column is color coded: green means there's a transcript, yellow means caption only, red means no text yet.

## How it works

1. `scripts/fetch_posts.py` asks Instagram's official API (Business Discovery) for his newest posts and adds them to `data/posts.json`. The first run walks through his whole account. After that it stops as soon as it reaches posts it already has.
2. `scripts/build_site.py` tags each post with topics from `topics.json`, adds transcripts from `transcripts/`, and writes `site/index.html`.
3. `.github/workflows/update.yml` runs both every day at 11:17 UTC (5:17 am in Chicago in winter), saves the new posts to the repository, and publishes the page with GitHub Pages.

Both scripts use only Python's standard library, so there's nothing to install.

## One-time setup

### 1. Make the repository

Create a new repository on GitHub and upload everything in this folder, including the hidden `.github` folder.

A public repository is the easy option, because GitHub Pages is free for public repositories. On GitHub's free plan, Pages doesn't work with private repositories at all. With GitHub Pro (free with the Student Developer Pack) the repository can be private, but the published page is still public.

### 2. Turn on GitHub Pages

In the repository, go to Settings, then Pages, and set Source to GitHub Actions.

### 3. Make an access token that lasts

The token from the Graph API Explorer expires within a couple of hours, so the daily job needs a Page token instead.

1. Open the [Graph API Explorer](https://developers.facebook.com/tools/explorer/). Pick the Finance Tips app and User Token, add these permissions, and click Generate Access Token: `instagram_basic`, `instagram_manage_insights`, `pages_read_engagement`, `pages_show_list`, `business_management`.
2. Click the blue "i" next to the token, then Open in Access Token Tool. At the bottom of that page, click Extend Access Token and copy the new token. It lasts about 60 days.
3. Back in the Explorer, paste that token into the Access Token box and run `me/accounts?fields=name,access_token`.
4. Copy the `access_token` value next to Finance Lil Brother. That's your Page token.
5. Paste it into the [Access Token Debugger](https://developers.facebook.com/tools/debug/accesstoken/) to check it. Expires should say Never.

Only paste the token into the GitHub secret in the next step. Don't put it in a chat, a file or a commit.

### 4. Add the token to GitHub

In the repository, go to Settings, then Secrets and variables, then Actions, and click New repository secret. Name it `IG_ACCESS_TOKEN` and paste the Page token as the value.

### 5. Run it

Go to the Actions tab, click Update archive, then Run workflow. The first run pages through all of his posts, which takes a minute or two. When it finishes, the page is at https://pjchafloque.github.io/finance_tips/.

## Keeping it running

The job runs every morning. If a run fails, GitHub emails you, and the log under the Actions tab explains why.

If the error mentions the access token, the token stopped working. That can happen if you change your Facebook password or remove the app, and Meta can also cut off the token's data access after about 90 days without a fresh login. Redo step 3 and replace the secret.

## Adding transcripts

Put a plain text file in `transcripts/`, named after the code in the reel's link. For https://www.instagram.com/reel/DfsR8zBy-SD/ the file is `transcripts/DfsR8zBy-SD.txt`. When you commit it, the page rebuilds, the reel's Text cell turns green, and the reel gets sorted into topics based on what the transcript says.

## Sorting a reel by hand

Reels with no caption or transcript land in the Not sorted yet sheet. To file one yourself, add it to `data/topic_overrides.json` with the code from its link:

```json
{
  "DfsR8zBy-SD": ["interviews", "excel"]
}
```

The topic ids are in `topics.json`. A hand-picked list replaces the automatic topics for that reel.

## Changing the topics

Edit `topics.json`. Each topic has a list of keywords. Matching ignores case and only matches whole words, and a keyword ending in `*` also matches longer words, so `recruit*` matches recruiting. Words under `exact_case` must match capital letters exactly, which keeps short ones like `PE` from matching the letters "pe" inside other words.

## Running it on your own computer

```
python3 scripts/build_site.py
open site/index.html
```

To fetch posts locally too, set the token first. It stays in your terminal session only:

```
export IG_ACCESS_TOKEN=...
python3 scripts/fetch_posts.py
```

`python3 scripts/fetch_posts.py --full` re-checks every post, which also picks up edited captions. You can do the same from GitHub by ticking "Re-check every post" when you click Run workflow.

## Files

- `config.json`: which account to follow, your Instagram account's ID and the API version
- `topics.json`: the topics and their keywords
- `data/posts.json`: every post found so far (the job updates this)
- `data/topic_overrides.json`: topics you picked by hand
- `transcripts/`: one text file per reel
- `scripts/`: the fetcher, the page builder and the page template
