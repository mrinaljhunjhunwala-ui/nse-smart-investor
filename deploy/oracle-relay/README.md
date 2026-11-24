# Live price relay on Oracle Cloud (free)

**Why:** Angel One only answers your SmartAPI app ("ShagStocks") from the static IP address
you registered. Streamlit Cloud and GitHub change IP all the time, so the app's "live" prices
come from Yahoo, which can lag about 15 minutes. This guide sets up a tiny always-free
computer at Oracle with an IP address that never changes. You register that IP with Angel
One. The computer then fetches live prices from Angel every 20 seconds during market hours and
saves them in your database, and the app reads them from there.

You need about an hour, a credit or debit card (Oracle checks it but the Always Free
resources cost nothing), and your Angel One SmartAPI details. Everything is done in a web
browser; you do not need to install anything on Windows.

---

## 1. Create the Oracle Cloud account

1. Go to <https://www.oracle.com/cloud/free/> and click **Start for free**.
2. Fill in the form. For **Home Region** pick **India West (Mumbai)** or
   **India South (Hyderabad)**. You cannot change the home region later.
3. Verify your card (a small temporary hold may appear) and wait for the "account is ready"
   email. Then sign in at <https://cloud.oracle.com>.

## 2. Create the computer (a "VM instance")

1. In the menu (☰ top left): **Compute → Instances → Create instance**.
2. **Name:** `nse-relay`.
3. **Image and shape → Edit:**
   - Image: **Canonical Ubuntu 24.04** (22.04 is fine too).
   - Shape: **Ampere → VM.Standard.A1.Flex** with 1 OCPU and 6 GB memory (Always Free).
     If Oracle says it is out of capacity, choose **Specialty and previous generation →
     VM.Standard.E2.1.Micro** instead (also Always Free; the setup script adds swap
     memory so it copes).
4. **Networking:** keep the default new virtual cloud network and **Assign a public IPv4
   address** (you will swap it for a reserved one in step 3).
5. **Add SSH keys:** choose **Generate a key pair for me** and click **Save private key**
   (keep the file somewhere safe; you will probably never need it, because you will use
   Cloud Shell).
6. Click **Create** and wait until the instance shows **Running**.

## 3. Give it an IP address that never changes

An ordinary public IP can change if the VM is stopped. A **reserved** IP stays yours.

1. Open the instance → **Attached VNICs** (under Resources) → click the VNIC name →
   **IPv4 Addresses** → on the primary private IP click **⋮ → Edit**.
2. Under **Public IP type** choose **No public IP**, click **Update** (this drops the
   temporary IP).
3. Click **⋮ → Edit** again, choose **Reserved public IP → Create new reserved IP**, name it
   `nse-relay-ip`, click **Update**.
4. Write down the IP address now shown (for example `140.238.x.x`). This is the address you
   give Angel One.

(You can also create it first under **Networking → IP Management → Reserved Public IPs** and
then pick it in step 3.)

**No inbound ports need opening.** The relay only makes outgoing connections.

## 4. Open a terminal to the VM in your browser

1. In the Oracle console, click the **Cloud Shell** icon (`>_`, top right). A terminal opens at
   the bottom of the page.
2. Upload the private key you saved in step 2: Cloud Shell menu (⚙ / ☰) → **Upload** → pick
   the `.key` file. Then type (replace the IP and file name):

   ```bash
   chmod 600 ssh-key-*.key
   ssh -i ssh-key-*.key ubuntu@YOUR.RESERVED.IP
   ```

   Answer `yes` to the fingerprint question. The prompt changes to `ubuntu@nse-relay`.

   (Windows alternative: Windows 10/11 has `ssh` built in. Open PowerShell and run the same
   `ssh -i C:\path\to\ssh-key.key ubuntu@YOUR.RESERVED.IP`.)

## 5. Install the relay

Still in that terminal (on the VM), paste:

```bash
curl -fsSL https://raw.githubusercontent.com/mrinaljhunjhunwala-ui/nse-smart-investor/main/deploy/oracle-relay/setup.sh | sudo bash
```

It takes a few minutes. It ends with "Not started yet: put your secrets in
/etc/nse-price-relay.env".

## 6. Put your secrets in

```bash
sudo nano /etc/nse-price-relay.env
```

Fill in after each `=` (no spaces, no quotes):

| Line | What to put |
|---|---|
| `ANGEL_API_KEY` | The API key of the **ShagStocks** SmartAPI app (same as your Streamlit `[angel_one] api_key`) |
| `ANGEL_CLIENT_ID` | Your Angel One client ID |
| `ANGEL_PASSWORD` | Your Angel One login PIN |
| `ANGEL_TOTP_SECRET` | The TOTP secret (the long code from enabling TOTP, not the 6 digits) |
| `DATABASE_URL` | Exactly the same `DATABASE_URL` as in your Streamlit / GitHub secrets |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Optional: remove the `#` and fill in to get one message a day if the relay gets no prices |

Save with **Ctrl+O, Enter**, exit with **Ctrl+X**. The file is readable only by the
administrator (permission 600) and never leaves the VM.

## 7. Register the IP with Angel One

1. Go to <https://smartapi.angelbroking.com> (or smartapi.angelone.in) → sign in →
   **My Apps** → **ShagStocks** → **Edit**.
2. In **Secondary Static IP**, enter the reserved IP from step 3. Leave the primary one as it is.
3. Save. Angel lets you change these IPs **once a week**, so double-check the number first.

## 8. Start it

```bash
sudo systemctl restart nse-price-relay
sudo journalctl -u nse-price-relay -f
```

During market hours (Mon–Fri 09:08–15:35 India time, NSE holidays excluded) you should see a
line every 20 seconds such as:

```
tick 10:31:20 IST · 112/115 quotes · 1.4 s · 9.6 KB
```

Outside market hours it says `market closed … sleeping, checking every minute`. That is
normal; the service stays on and wakes up by itself. Press **Ctrl+C** to stop watching (the
relay keeps running). It also starts by itself after a reboot.

If you see `0/115 quotes` with `forbidden` or `login refused`, the IP is not registered yet
(step 7) or a secret is wrong (step 6).

## 9. Check it in the app

During market hours:

- **Markets → Live Ticker:** the Feed box says **Source: Angel via relay, 12 s ago**.
- **My Portfolio:** under the top line, "Prices: live (Angel via relay, 12 s ago)."

If the relay stops during market hours, the app quietly goes back to Yahoo prices, and the
Market Alerts job sends one Telegram message that day: "Live price relay stopped at HH:MM".

## Updating later

Run the same command as step 5 again; it pulls the latest code and restarts the relay:

```bash
curl -fsSL https://raw.githubusercontent.com/mrinaljhunjhunwala-ui/nse-smart-investor/main/deploy/oracle-relay/setup.sh | sudo bash
```

(or `cd /opt/nse-smart-investor && sudo git pull && sudo systemctl restart nse-price-relay`).

## Useful commands

| What | Command |
|---|---|
| Is it running? | `systemctl status nse-price-relay` |
| Live log | `sudo journalctl -u nse-price-relay -f` |
| Today's log | `sudo journalctl -u nse-price-relay --since today` |
| Restart | `sudo systemctl restart nse-price-relay` |
| Stop for good | `sudo systemctl disable --now nse-price-relay` |

## NSE end-of-day downloads

NSE's archive site refuses GitHub's servers (HTTP 403), so the VM also downloads the evening
NSE files: delivery %, F&O open interest, FII index futures and the option chain. A timer runs
them at **19:45 and 22:00 India time, Mon–Fri** and saves them in the same database. setup.sh
turns the timer on once the secrets file is filled in; nothing else to configure.

Then, in GitHub: **Settings → Secrets and variables → Actions → Variables → New repository
variable**, name `EOD_VIA_RELAY`, value `true`. The "Refresh EOD market data" job then skips
those four steps (it still does FII/DII cash flows and the verdict-ledger returns).

| What | Command |
|---|---|
| Next run times | `systemctl list-timers nse-eod-refresh` |
| Run it now | `sudo systemctl start nse-eod-refresh` |
| Last run's log | `sudo journalctl -u nse-eod-refresh -n 80` |

Each run fetches the latest trading day (set `EOD_DAYS=3` in the secrets file to backfill more) and takes about 15–40 minutes, mostly database writes.

## The app's database (Postgres on this VM)

Since Nov 2026 the app's database runs on this VM instead of Neon. Neon's free plan allows
about 5 GB of data transfer a month and locked the database twice; Oracle's Always Free
allowance is about 10 TB. **Keep this account Always Free**: no upgrade, no paid shapes, until
the model's results justify paying for anything.

Set up (or re-run safely) with:

```bash
curl -fsSL https://raw.githubusercontent.com/mrinaljhunjhunwala-ui/nse-smart-investor/main/deploy/oracle-relay/postgres_setup.sh | sudo bash
```

It installs PostgreSQL, creates the `nse` database and `nse_app` user with a generated
password, accepts only encrypted password logins from outside, opens port 5432 in the VM
firewall and backs the database up every night at 01:30 IST (7 days kept in
`/var/backups/nse-postgres`). The connection URL is in `/etc/nse-postgres.url` (root only);
that is the `DATABASE_URL` for Streamlit, GitHub and `/etc/nse-price-relay.env`.

In the Oracle console, port 5432 must also be open: **Networking → Virtual cloud networks →**
your VCN **→ Security Lists → Default Security List → Add Ingress Rules**: source
`0.0.0.0/0`, TCP, destination port `5432`.

| What | Command |
|---|---|
| Is it running? | `systemctl status postgresql` |
| Backups | `ls -lh /var/backups/nse-postgres` |
| Back up now | `sudo systemctl start nse-pg-backup` |
| Restore a backup | `sudo -u postgres pg_restore -d nse --clean /var/backups/nse-postgres/nse-YYYYMMDD.dump` |

## Staying up on Always Free

Oracle may stop an Always Free VM that looks idle for a week (CPU, network and memory all under
20%). `nse-keepbusy.timer` (installed by setup.sh) runs a lowest-priority CPU loop for 20 minutes
each hour between 00:00 and 08:59 IST so the VM never looks idle; it never slows the relay or
the database. If the VM still goes down, the GitHub workflow **Database health** checks the
database every hour and sends a Telegram message (and another when it is back).

## Costs and limits

- Oracle: the A1 / E2.1.Micro VM and one reserved IP are Always Free.
- Database (Neon free plan, 5 GB transfer a month): the relay writes one small document
  (~10 KB for ~110 stocks, ~24 KB at the 250-stock cap) every 20 s, about 12–28 MB per market
  day, plus the app's reads (at most one read per 10 s while a live page is open). That is well
  under 1 GB a month in normal use. To use less, set `RELAY_INTERVAL_S=30` in the secrets file
  and restart.
- The relay keeps the database awake during market hours (about 6½ hours a day), which uses
  some of Neon's free monthly compute time.

## Which stocks it relays

Up to 250, in this order: My Portfolio holdings, your watchlist, open paper trades, today's
Morning Digest picks, today's BUY calls and intraday levels, Nifty 50 / Nifty Bank / India VIX,
Top Picks, Tomorrow's Watchlist, then the rest of the NIFTY 50. The list is re-read every
5 minutes (the two big scan snapshots every 30 minutes). Anything else the app prices
still comes from Yahoo.
