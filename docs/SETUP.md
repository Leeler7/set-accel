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

developers.facebook.com → My Apps → **Create app**.

1. App name (anything) and your contact email.
2. **Business portfolio: select yours.** Do not skip this. A system user token can
   only be issued against an app, so until the portfolio contains an app, the
   Add button under System users refuses with "you must add an app as part of
   your business portfolio". Connecting it later works too, from App settings →
   Basic, or Business settings → Accounts → Apps → Add.
3. Use case: **Other**, then Next.
4. App type: **Business**, then Create app.

Then find **Instagram** in the product list and click **Set up**.

Choose **Instagram API with Facebook Login**, not the Instagram Login variant.
Meta's documentation is explicit that the Facebook Login path is the one
required when the professional account is linked to a Facebook Page, which is
the setup this pipeline assumes.

### A note on permission names

Meta is mid-rename. Depending on the login variant you may be offered the
classic scopes (`instagram_basic`, `instagram_content_publish`,
`pages_show_list`, `pages_read_engagement`) or the newer `instagram_business_*`
equivalents. Either is fine. What matters is that the content-publish scope is
included and the token works against your account ID.

## 5. Find your Instagram user ID

Fastest route: Meta Business Suite → Business settings → Accounts → Instagram
accounts. Select the account and read the **Instagram account ID**. It is a long
number beginning `17841`. That is your `IG_USER_ID`, and its existence is itself
proof that steps 1 and 2 worked, since the ID is only issued to a professional
account linked to a Page.

For this account it is `17841437849221933`.

If you would rather confirm it through the API, in the Graph API Explorer with
`pages_show_list` and `instagram_basic` granted:

    GET /me/accounts
    GET /{PAGE_ID}?fields=instagram_business_account

An empty response there means the Page link never took. Redo step 2.

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

### Shortcut for a first test

The system user token is worth having, but it is not required to prove the
pipeline works. Once the app exists, the Graph API Explorer will mint a
short-lived user token in about a minute: select the app, click Generate Access
Token, grant the publish scopes. It expires in an hour or two, which is fine for
a test and lets you see a real post before doing the durable setup.

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
