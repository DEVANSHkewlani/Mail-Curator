# The Curator Mail

Multi-user bulk email app with authenticated campaigns, per-user attachments, send history, and reply threading.

## Reply Threading

When a logged-in user sends a campaign, the backend stores each successful recipient's RFC 5322 `Message-ID` in `send_results`.

On later sends, `/send/start` checks only that logged-in user's previous successful sends. If a recipient has already received mail from that user, the new email is sent with `In-Reply-To` and `References` headers so mail clients can group it as a reply to the previous message.

## Local Docker Run

1. Copy the environment template:

   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and set a long random `SECRET_KEY` and strong database password.

3. Start the app:

   ```bash
   docker compose up --build
   ```

4. Open:

   ```text
   http://localhost:8000
   ```

## Production Notes

- Set `SECRET_KEY` to a unique random value before deploying.
- Use a persistent Postgres database and persistent upload storage.
- Keep `DATABASE_URL` in `postgresql+asyncpg://...` format.
- Configure SMTP with the provider's app password or API SMTP password from the Send page.
- The app creates tables on startup and applies small compatibility guards for older installs that are missing reply-thread columns.
