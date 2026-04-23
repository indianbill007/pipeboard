# Meta System User — Asset Assignment Guide

> **Audience:** Meta (Facebook) Ads administrator at Globussoft.
> **Purpose:** Grant an existing Meta System User access to the ad accounts we want the Pipeboard automation to monitor and manage.

> **📸 Note on screenshots:** This guide is intentionally text-first. Meta's Business Manager UI changes wording and button positions from time to time; the navigation landmarks below are stable. If a step looks different in your view, the text description should still lead you to the right place. Feel free to paste screenshots inline as you work through it.

---

## TL;DR

1. Sign in to https://business.facebook.com/settings as Globussoft admin.
2. Users → **System Users** → click **`claude-mcp`**.
3. **Add Assets → Ad Accounts** → tick every ad account in [the list below](#ad-accounts-to-assign).
4. Enable **View performance** and **Manage campaigns** for each.
5. Save.
6. Reply to confirm, and we'll verify programmatically in under 5 minutes.

---

## What we're asking for

| Item | Value |
|---|---|
| System User | `claude-mcp` |
| Business | **Globussoft** |
| Business ID | `1525787951959331` |
| Permissions on each ad account | **View performance** + **Manage campaigns** (both on) |

Nothing is being deleted, modified, or sent outside your business. The System User only gains read + pause/resume ability on ad accounts you explicitly assign.

---

## Prerequisites

- **Admin** role on the Globussoft Business Manager, or on the specific ad accounts you're assigning.
- Access to https://business.facebook.com/settings while signed in with that account.
- ~5 minutes.

---

## Part 1 — For ad accounts that belong to **Globussoft** business

### Step 1 · Open Business Settings

1. Go to **https://business.facebook.com/settings**.
2. In the top-left business switcher, make sure **Globussoft** is selected.
   (If you only manage one business, there's no switcher — you're already there.)

### Step 2 · Find the System User

1. In the left sidebar, scroll to the **Users** section.
2. Click **System Users**.
3. On the right pane you'll see a list of system users. Click **`claude-mcp`**.

> If `claude-mcp` is **not** in the list, skip to [Appendix A — Creating the System User](#appendix-a--creating-the-claude-mcp-system-user-only-if-missing).

### Step 3 · Assign ad accounts

With `claude-mcp` selected:

1. Click **Add Assets** (sometimes labelled **Assign Assets**).
2. A dialog opens. In its left tab bar, choose **Ad Accounts**.
3. You'll see a list of ad accounts owned by Globussoft.
4. **Tick the checkbox next to every ad account from [the list below](#ad-accounts-to-assign)** that appears here.
5. On the **right side of the same dialog**, there are permission toggles. Turn these **ON**:
   - ✅ **View performance** (read metrics / insights)
   - ✅ **Manage campaigns** (pause / resume / update)
6. Click **Save Changes**.

### Step 4 · If any accounts in the list aren't visible in Globussoft

Some may live in other businesses (client businesses, legacy accounts, etc.). For those → see **Part 2** below.

---

## Part 2 — For ad accounts that belong to a **different** business

Choose **one** of the two options:

### Option A (preferred): Share the ad account into Globussoft as a partner

Do this inside the business that **owns** the ad account:

1. Sign into Business Settings for that business.
2. **Accounts → Ad Accounts** → click the account you want to share.
3. Click **Assign Partner**.
4. Choose **Give a partner access to your assets using a business ID**.
5. Paste Globussoft's business ID: **`1525787951959331`**.
6. Select permissions: **View performance** + **Manage campaigns**.
7. Save.

Then return to **Part 1** inside Globussoft — the newly shared account will now show up for `claude-mcp` to be assigned to.

### Option B: Create a second System User inside the other business

1. Sign into Business Settings for that business.
2. **Users → System Users → Add**.
3. Name: `claude-mcp-external` (or any identifiable name).
4. Role: **Admin** (simpler) or **Employee**.
5. After creation, click **Generate New Token**:
   - **App:** select the app registered for this automation.
   - **Token expiration:** **Never** (non-expiring).
   - **Permissions:** tick `ads_read`, `ads_management`, `business_management`.
6. Copy the token — it's shown only once.
7. Send it securely (not email). Ping us and we'll tell you a secure channel.

---

## Ad accounts to assign

This is a partial list based on what the first automation run observed. **Please assign every ad account that Globussoft should have automated under this System User** — not just these.

| # | Name (as seen in first run) | Ad Account ID |
|---|---|---|
| 1 | AdsGPT | `act_1345383896902910` *(already assigned)* |
| 2 | Globussoft AI | `act_475821441756869` |
| 3 | Social Reel Farm | `act_715702414895109` |
| 4 | AstroLive — Main AC | `act_553290187532903` |
| 5 | Chingari | (ID tbc) |
| 6 | Tivra | (ID tbc) |
| 7 | Biswa01 | (ID tbc) |
| 8 | Biswa02 | (ID tbc) |
| 9 | Biswa03 | (ID tbc) |
| 10 | Biswa04 | (ID tbc) |
| 11 | Biswa05 | (ID tbc) |
| 12 | EmpC_IND Ads AC | (ID tbc) |
| 13–14 | *any others* | — |

> If an account on this list isn't visible from your Business Settings, don't worry — note it and we'll figure out the ownership separately.

---

## Verifying it worked

Once you've finished, send **one** of the following:

- A screenshot of the `claude-mcp` **Assigned Assets** page showing the ad accounts listed, **or**
- A plain-text list of the ad account IDs (`act_...`) you assigned.

We'll run a 10-second check on our side that reads the live asset list visible to the token and confirm it matches. If anything didn't stick, we'll flag specific accounts that still need attention.

---

## Troubleshooting

**"I don't see `claude-mcp` in System Users."**
→ It hasn't been created inside this business yet. See [Appendix A](#appendix-a--creating-the-claude-mcp-system-user-only-if-missing).

**"The ad account is greyed out or says 'Added to other businesses'."**
→ It belongs to a different business. Use [Part 2, Option A](#option-a-preferred-share-the-ad-account-into-globussoft-as-a-partner) to share it in.

**"I can see the account but can't toggle 'Manage campaigns'."**
→ You don't have Admin role on that specific ad account. Ask whoever does to either assign you Admin, or do the assignment themselves.

**"I assigned it but the automation still reports the account as missing."**
→ Two common causes:
1. Only one of the two permission toggles was on. Both **View performance** AND **Manage campaigns** must be checked.
2. Meta caches permission changes. Wait 5–10 min and retry.

**"'The System User is already an admin on this asset' — can I still change permissions?"**
→ Yes. Admin-level users already have full access; the task toggles inside this dialog refine their role. If Admin is selected, both toggles above are implicit.

---

## Appendix A — Creating the `claude-mcp` System User (only if missing)

1. Business Settings → **Users → System Users → Add**.
2. **Name:** `claude-mcp`
3. **Role:** **Admin** (recommended — simpler for asset assignment).
4. Click **Create System User**.
5. With the new user selected, click **Generate New Token**:
   - **App:** select the app registered for this automation.
   - **Token expiration:** **Never**.
   - **Permissions:** tick `ads_read`, `ads_management`, and `business_management`.
6. Copy the generated token — Meta shows it only once.
7. Send the token securely (ping us for a secure channel).

Then proceed with **Part 1, Step 3** to assign ad accounts.

---

## Questions?

If any step is ambiguous or Meta's UI has moved things around, ping the requester — happy to get on a quick screen-share.
