# One-time setup

Everything else in this repo runs itself. This is the part that needs you, and
you only do it once. Budget 30 minutes.

A note on confidence: the repository side of this was built and tested. The Meta
side below was written from Meta's current developer documentation, but it could
not be tested from the environment that built this, because Meta's API hosts are
not reachable from there. Treat the step numbers as a reliable map and the exact
button labels as approximate, since Meta renames things often. Step 7 is where
you find out whether it all worked.

---

## 1. Make @set.accel a professional account

Instagram app, on the @set.accel account:

Settings → Account type and tools → Switch to professional account → Creator or
Business. Either works for publishing.

## 2. Connect it to a Facebook Page

The publishing API reaches Instagram through a Page. There is no way around this.

If you do not have a Page, make an empty one. It never has to be used for
anything and can stay unpublished.

Instagram app → Settings → Account type and tools → Sharing to other apps, or
via Meta Business Suite → Settings → Accounts, and link the Page to @set.accel.

## 3. Create a business portfolio

Go to business.facebook.com. Create a business portfolio if you do not already
have one. Add both the Facebook Page and the @set.accel Instagram account to it
under Business settings → Accounts.

## 4. Create a Meta app

developers.facebook.com → My Apps → Create App.

- Use case: **Other**
- App type: **Business**
- Link it to the business portfolio from step 3

Then add the **Instagram** product to the app.

## 5. Find your Instagram user ID

Open the Graph API Explorer (developers.facebook.com/tools/explorer), select
your app, and grant yourself `pages_show_list` and `instagram_basic`. Then run:

    GET /me/accounts

Find your Page in the response and copy its `id`. Then run:

    GET /{PAGE_ID}?fields=instagram_business_account

The `instagram_business_account.id` in the response is your `IG_USER_ID`. It is
a long number. Save it.

## 6. Generate an access token

Two options. The first is better and is worth the extra five minutes, because it
is the difference between never touching this again and rotating a token every
sixty days.

### Option A: system user token that never expires (recommended)

business.facebook.com → Business settings → Users → **System users** → Add.

1. Create a system user with the **Admin** role.
2. **Assign assets** to it: the Facebook Page and the @set.accel Instagram
   account, both with full control. Skipping this is the single most common
   reason the token comes back working but unable to see the account.
3. Click **Generate new token**.
4. Select your app from step 4.
5. Set **Token expiration: Never**.
6. Select these permissions:
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_read_engagement`
   - `pages_show_list`
   - `business_management`
7. Copy the token immediately. Meta shows it exactly once.

### Option B: long-lived user token (60 days, needs rotating)

If the system user route is unavailable on your account, use the Graph API
Explorer to generate a user token with the same permissions, then exchange it
for a long-lived one:

    GET https://graph.facebook.com/v23.0/oauth/access_token
        ?grant_type=fb_exchange_token
        &client_id={APP_ID}
        &client_secret={APP_SECRET}
        &fb_exchange_token={SHORT_LIVED_TOKEN}

This lasts about 60 days. The health check workflow will open an issue on this
repo two weeks before it dies, so you get warned rather than discovering it from
a silent feed.

## 7. Add the two secrets and test

In this repo: Settings → Secrets and variables → Actions → New repository secret.

| Name | Value |
|---|---|
| `IG_USER_ID` | the number from step 5 |
| `IG_ACCESS_TOKEN` | the token from step 6 |

Then, in the Actions tab:

1. Run **Health check** manually. It should report `token works, account
   @set.accel`. If it does not, the problem is in steps 1 to 6, and the error
   message will say which.
2. Run **Daily post** manually with `dry_run` ticked. It prints the exact caption
   it would publish without publishing anything.
3. Run **Daily post** manually with `dry_run` unticked. Check Instagram.

Once step 3 works, you are done. The schedule takes over.

---

## If something goes wrong

**"Unsupported get request" or "does not exist"**
Usually the account is not actually professional yet, or the Page is not linked.
Redo steps 1 and 2 and give it a few minutes to propagate.

**Token works but returns an empty result for the IG account**
The system user was not assigned the assets. Step 6, item 2.

**"Application does not have permission for this action"**
Your app needs at least Standard Access for `instagram_content_publish`. In the
app dashboard under App Review → Permissions and Features, request or enable it.
Publishing to an account you own from an app you own does not normally require
full App Review, but the permission still has to be switched on.

**The image fails to download**
Instagram fetches the image from `raw.githubusercontent.com`, so this repo has
to stay **public**. If you make it private, publishing breaks immediately.

**Rate limits**
Instagram allows 100 API-published posts per rolling 24 hours. At one a day this
is not a concern, and the health check reports current usage.
